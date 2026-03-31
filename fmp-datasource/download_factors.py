"""
下载因子信号数据
- 盈利惊喜（earnings surprise）
- 分析师评级历史
- 内部人交易（Form 4）
- 国会议员交易（参议院 + 众议院）

输出文件：
  cache/earnings/{TICKER}.parquet
  cache/analyst_grades/{TICKER}.parquet
  cache/insider_trades/{TICKER}.parquet
  cache/congressional_trades/{TICKER}.parquet
  cache/factors_merged.parquet   ← 月度汇总信号表（供回测直接使用）
"""
import os
import time
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from fmp_client import get, ensure_cache_dir
from download_constituents import get_all_historical_tickers


# ─── 各因子下载函数 ────────────────────────────────────────────────

def download_earnings(symbol: str, limit: int = 80) -> pd.DataFrame:
    data = get("earnings", symbol=symbol, limit=limit)
    return pd.DataFrame(data) if data else pd.DataFrame()


def download_analyst_grades(symbol: str, limit: int = 500) -> pd.DataFrame:
    data = get("grades-historical", symbol=symbol, limit=limit)
    return pd.DataFrame(data) if data else pd.DataFrame()


def download_insider_trades(symbol: str, limit: int = 500) -> pd.DataFrame:
    # 注意：必须用 /insider-trading/search 而非 /insider-trading
    data = get("insider-trading/search", symbol=symbol, limit=limit)
    return pd.DataFrame(data) if data else pd.DataFrame()


def download_congressional_trades(symbol: str) -> pd.DataFrame:
    senate = get("senate-trading", symbol=symbol) or []
    house  = get("house-trading",  symbol=symbol) or []
    combined = senate + house
    if not combined:
        return pd.DataFrame()
    df = pd.DataFrame(combined)
    df["chamber"] = (["senate"] * len(senate)) + (["house"] * len(house))
    return df


# ─── 批量下载 ─────────────────────────────────────────────────────

def _download_ticker_factors(symbol: str, force: bool = False) -> dict:
    results = {}
    tasks = {
        "earnings":             (download_earnings,           "earnings"),
        "analyst_grades":       (download_analyst_grades,     "analyst_grades"),
        "insider_trades":       (download_insider_trades,     "insider_trades"),
        "congressional_trades": (download_congressional_trades, "congressional_trades"),
    }
    for name, (fn, subdir) in tasks.items():
        cache_dir = ensure_cache_dir(subdir)
        out_path = os.path.join(cache_dir, f"{symbol}.parquet")
        if not force and os.path.exists(out_path):
            results[name] = True
            continue
        try:
            df = fn(symbol)
            if not df.empty:
                df["symbol"] = symbol
            # 无论是否有数据都写文件，避免下次重复请求
            df.to_parquet(out_path, index=False)
            results[name] = True
        except Exception as e:
            results[name] = False
    return results


def download_all(tickers: list = None, workers: int = 6, force: bool = False):
    if tickers is None:
        tickers = get_all_historical_tickers()

    # 检查哪些 ticker 的四类因子数据都已齐全
    subdirs = ["earnings", "analyst_grades", "insider_trades", "congressional_trades"]
    if not force:
        existing = None
        for subdir in subdirs:
            d = ensure_cache_dir(subdir)
            present = {f.replace(".parquet", "") for f in os.listdir(d) if f.endswith(".parquet")}
            existing = present if existing is None else existing & present
        todo = [t for t in tickers if t not in existing]
    else:
        todo = tickers

    print(f"需要下载因子数据：{len(todo)} 只（已缓存：{len(tickers)-len(todo)} 只）")
    if not todo:
        print("全部已缓存，跳过。")
        return

    success = 0
    start = time.time()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_download_ticker_factors, t, force): t for t in todo}
        for i, future in enumerate(as_completed(futures), 1):
            future.result()
            success += 1
            if i % 50 == 0:
                elapsed = time.time() - start
                eta = (len(todo) - i) / (i / elapsed) if elapsed > 0 else 0
                print(f"  进度 {i}/{len(todo)} | 预计剩余 {eta/60:.1f}min")

    print(f"\n✅ 因子数据下载完成：{success} 只")


# ─── 合并为月度信号表 ──────────────────────────────────────────────

def build_monthly_signals(tickers: list = None) -> pd.DataFrame:
    """
    将各因子数据汇总为月度信号表
    每行：(month_end, symbol, earnings_surprise, analyst_score, insider_net_buy, congress_net_buy)
    供回测直接使用，已做 point-in-time 处理
    """
    if tickers is None:
        tickers = get_all_historical_tickers()

    print("构建月度因子信号表...")
    rows = []

    for symbol in tickers:
        try:
            signals = _build_symbol_signals(symbol)
            rows.extend(signals)
        except Exception:
            pass

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["month_end"] = pd.to_datetime(df["month_end"])
    df = df.sort_values(["month_end", "symbol"]).reset_index(drop=True)

    out = os.path.join(ensure_cache_dir(), "factors_merged.parquet")
    df.to_parquet(out, index=False)
    print(f"✅ 月度信号表：{len(df)} 行 → {out}")
    return df


def _build_symbol_signals(symbol: str) -> list:
    rows = []
    month_ends = pd.date_range("2010-01-31", pd.Timestamp.today(), freq="ME")

    # 加载各因子
    def load(subdir):
        p = os.path.join(ensure_cache_dir(subdir), f"{symbol}.parquet")
        return pd.read_parquet(p) if os.path.exists(p) else pd.DataFrame()

    earnings_df = load("earnings")
    grades_df   = load("analyst_grades")
    insider_df  = load("insider_trades")
    congress_df = load("congressional_trades")

    for month_end in month_ends:
        me_str = month_end.strftime("%Y-%m-%d")
        row = {"month_end": me_str, "symbol": symbol}

        # 盈利惊喜：最近一次已公布的季报
        if not earnings_df.empty and "date" in earnings_df.columns:
            past = earnings_df[earnings_df["date"] <= me_str].copy()
            if not past.empty:
                latest = past.sort_values("date").iloc[-1]
                eps_a = latest.get("epsActual")
                eps_e = latest.get("epsEstimated")
                if eps_a is not None and eps_e and float(eps_e) != 0:
                    row["earnings_surprise"] = (float(eps_a) - float(eps_e)) / abs(float(eps_e))

        # 分析师情绪：过去 90 天内评级，正面比例
        if not grades_df.empty and "date" in grades_df.columns:
            window_start = (month_end - pd.Timedelta("90d")).strftime("%Y-%m-%d")
            recent = grades_df[(grades_df["date"] > window_start) & (grades_df["date"] <= me_str)]
            if not recent.empty:
                positive = recent["newGrade"].str.lower().str.contains("buy|outperform|overweight", na=False).sum()
                row["analyst_positive_pct"] = positive / len(recent)
                row["analyst_count"] = len(recent)

        # 内部人净买入：过去 90 天
        if not insider_df.empty and "transactionDate" in insider_df.columns:
            window_start = (month_end - pd.Timedelta("90d")).strftime("%Y-%m-%d")
            recent = insider_df[(insider_df["transactionDate"] > window_start) &
                                (insider_df["transactionDate"] <= me_str)]
            if not recent.empty:
                buys  = recent[recent["acquisitionOrDisposition"] == "A"]["securitiesTransacted"].fillna(0).astype(float).sum()
                sells = recent[recent["acquisitionOrDisposition"] == "D"]["securitiesTransacted"].fillna(0).astype(float).sum()
                row["insider_net_buy_shares"] = buys - sells
                row["insider_buy_count"] = (recent["acquisitionOrDisposition"] == "A").sum()

        # 国会净买入：过去 180 天（disclosure lag 较长）
        if not congress_df.empty and "disclosureDate" in congress_df.columns:
            window_start = (month_end - pd.Timedelta("180d")).strftime("%Y-%m-%d")
            recent = congress_df[(congress_df["disclosureDate"] > window_start) &
                                 (congress_df["disclosureDate"] <= me_str)]
            if not recent.empty:
                buys  = (recent["type"].str.lower() == "purchase").sum()
                sells = (recent["type"].str.lower() == "sale").sum()
                row["congress_net_buy"] = buys - sells
                row["congress_trade_count"] = len(recent)

        if len(row) > 2:  # 有实际信号才加入
            rows.append(row)

    return rows


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--signals-only", action="store_true", help="只重建信号表，不重新下载")
    args = parser.parse_args()

    if not args.signals_only:
        download_all(workers=args.workers, force=args.force)
    build_monthly_signals()
