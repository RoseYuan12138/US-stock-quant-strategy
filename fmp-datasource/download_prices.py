"""
Step 5: 下载历史日线价格（OHLCV）
- 从 FMP API 获取所有历史成分股的日线数据
- 每只股票一个 parquet 文件
- 支持增量更新（只下载新数据）
- 合并为 prices_merged.parquet（长表格式）

输出文件：
  cache/prices/{TICKER}.parquet      ← 单股票日线
  cache/prices_merged.parquet        ← 合并后的全量数据
"""
import os
import time
import argparse
import pandas as pd
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed
from fmp_client import get, ensure_cache_dir
from download_constituents import get_all_historical_tickers

SUBDIR = "prices"


def download_one(symbol: str, start: str = "2010-01-01",
                 end: str = None) -> pd.DataFrame:
    """下载单只股票的全量日线数据（分段请求以绕过 API 行数限制）"""
    if end is None:
        end = date.today().strftime("%Y-%m-%d")

    # 分 5 年一段下载，避免 API 截断
    start_dt = pd.Timestamp(start)
    end_dt = pd.Timestamp(end)
    all_dfs = []

    seg_start = start_dt
    while seg_start < end_dt:
        seg_end = min(seg_start + pd.DateOffset(years=5), end_dt)
        try:
            data = get(
                "historical-price-eod/full",
                symbol=symbol,
                **{"from": seg_start.strftime("%Y-%m-%d"),
                   "to": seg_end.strftime("%Y-%m-%d")}
            )
        except PermissionError:
            return pd.DataFrame()
        except Exception:
            seg_start = seg_end
            continue

        if data and isinstance(data, list):
            all_dfs.append(pd.DataFrame(data))
        elif data and isinstance(data, dict):
            hist = data.get("historical", data.get("data", []))
            if hist:
                all_dfs.append(pd.DataFrame(hist))

        seg_start = seg_end + pd.Timedelta(days=1)

    if not all_dfs:
        return pd.DataFrame()

    df = pd.concat(all_dfs, ignore_index=True)

    if df.empty or "date" not in df.columns:
        return pd.DataFrame()

    df["symbol"] = symbol
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df = df.drop_duplicates(subset=["date"])
    df = df.sort_values("date").reset_index(drop=True)

    return df


def _download_one_safe(symbol, start, force):
    """线程安全的单只下载，失败时写空占位文件"""
    cache = ensure_cache_dir(SUBDIR)
    path = os.path.join(cache, f"{symbol}.parquet")

    if not force and os.path.exists(path):
        return "skip"

    df = download_one(symbol, start)
    if df.empty:
        pd.DataFrame().to_parquet(path, index=False)  # 占位，避免重复请求
        return "fail"

    df.to_parquet(path, index=False)
    return "ok"


def download_all(tickers, start="2010-01-01", skip_existing=True, workers=8):
    """多线程批量下载所有股票价格"""
    if "SPY" not in tickers:
        tickers = list(tickers) + ["SPY"]

    cache = ensure_cache_dir(SUBDIR)
    force = not skip_existing
    if not force:
        existing = {f.replace(".parquet", "") for f in os.listdir(cache) if f.endswith(".parquet")}
        todo = [t for t in tickers if t not in existing]
    else:
        todo = tickers

    print(f"需要下载价格数据：{len(todo)} 只（已缓存：{len(tickers) - len(todo)} 只）")
    if not todo:
        print("全部已缓存，跳过。")
        return

    ok, fail = 0, 0
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_download_one_safe, t, start, force): t for t in todo}
        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            if result == "ok":
                ok += 1
            elif result == "fail":
                fail += 1
            if i % 100 == 0:
                elapsed = time.time() - t0
                eta = (len(todo) - i) / (i / elapsed) if elapsed > 0 else 0
                print(f"  进度 {i}/{len(todo)} | ✅{ok} ❌{fail} | 预计剩余 {eta/60:.1f}min")

    print(f"\n✅ 价格下载完成：成功 {ok}  失败/无数据 {fail}")


def merge_all() -> pd.DataFrame:
    """合并所有单股票价格为一张大表"""
    cache = ensure_cache_dir(SUBDIR)
    files = [f for f in os.listdir(cache) if f.endswith(".parquet")]
    print(f"合并 {len(files)} 只股票的价格数据...")

    dfs = []
    for f in files:
        try:
            df = pd.read_parquet(os.path.join(cache, f))
            if not df.empty:
                dfs.append(df)
        except Exception:
            continue

    if not dfs:
        print("❌ 没有找到任何价格数据")
        return pd.DataFrame()

    merged = pd.concat(dfs, ignore_index=True)

    # 标准化列名
    col_map = {}
    for col in merged.columns:
        lower = col.lower()
        if lower in ("open", "high", "low", "close", "volume",
                      "adjclose", "date", "symbol"):
            col_map[col] = lower

    merged = merged.rename(columns=col_map)

    # 确保必要列存在
    required = ["date", "symbol", "open", "high", "low", "close", "volume"]
    available = [c for c in required if c in merged.columns]

    # adjClose 处理
    if "adjclose" in merged.columns:
        available.append("adjclose")
    elif "adjustedclose" in merged.columns.str.lower():
        for c in merged.columns:
            if c.lower() == "adjustedclose":
                merged["adjclose"] = merged[c]
                available.append("adjclose")
                break

    merged = merged[available].copy()
    merged["date"] = pd.to_datetime(merged["date"], errors="coerce")
    merged = merged.dropna(subset=["date"])
    merged = merged.sort_values(["symbol", "date"]).reset_index(drop=True)

    out = os.path.join(ensure_cache_dir(), "prices_merged.parquet")
    merged.to_parquet(out, index=False)
    print(f"✅ 合并完成：{len(merged)} 行 × {len(merged.columns)} 列 → {out}")
    print(f"   股票数：{merged['symbol'].nunique()}")
    print(f"   日期范围：{merged['date'].min()} → {merged['date'].max()}")

    return merged


def build_monthly_prices(start="2010-01-01"):
    """
    从日线数据提取月末复权价，计算月度收益率
    供回测直接使用，point-in-time：用上月末价格算当月收益
    输出：cache/prices_monthly.parquet
    columns: date(月末), symbol, adj_close, monthly_return
    """
    print("构建月末价格 + 月度收益率表...")
    cache = ensure_cache_dir(SUBDIR)
    files = [f for f in os.listdir(cache) if f.endswith(".parquet")]

    frames = []
    for f in files:
        try:
            df = pd.read_parquet(os.path.join(cache, f))
            if df.empty or "date" not in df.columns:
                continue
            price_col = "adjclose" if "adjclose" in df.columns else (
                        "adjClose" if "adjClose" in df.columns else "close")
            if price_col not in df.columns:
                continue
            sub = df[["date", "symbol", price_col]].rename(columns={price_col: "adj_close"})
            sub["date"] = pd.to_datetime(sub["date"])
            sub = sub[sub["date"] >= start]
            frames.append(sub)
        except Exception:
            pass

    if not frames:
        print("  ❌ 无价格数据")
        return pd.DataFrame()

    all_prices = pd.concat(frames, ignore_index=True)
    all_prices["month_end"] = all_prices["date"].dt.to_period("M").dt.to_timestamp("M")

    monthly = (
        all_prices.sort_values("date")
        .groupby(["symbol", "month_end"])
        .last()
        .reset_index()[["symbol", "month_end", "adj_close"]]
        .rename(columns={"month_end": "date"})
    )
    monthly = monthly.sort_values(["symbol", "date"]).reset_index(drop=True)
    monthly["monthly_return"] = monthly.groupby("symbol")["adj_close"].pct_change()

    out = os.path.join(ensure_cache_dir(), "prices_monthly.parquet")
    monthly.to_parquet(out, index=False)
    print(f"✅ 月末价格表：{len(monthly):,} 行，{monthly['symbol'].nunique()} 只股票 → {out}")
    return monthly


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="下载 FMP 历史日线价格")
    parser.add_argument("--start", default="2010-01-01",
                       help="起始日期 (default: 2010-01-01)")
    parser.add_argument("--merge-only", action="store_true",
                       help="只合并已有缓存")
    parser.add_argument("--no-skip", action="store_true",
                       help="强制重新下载所有")
    args = parser.parse_args()

    if not args.merge_only:
        # 下载 SPY 基准
        print("下载 SPY 基准价格...")
        spy_df = download_one("SPY", args.start)
        if not spy_df.empty:
            spy_path = os.path.join(ensure_cache_dir(SUBDIR), "SPY.parquet")
            spy_df.to_parquet(spy_path, index=False)
            print(f"  ✅ SPY: {len(spy_df)} 天")

        # 下载所有历史成分股
        tickers = get_all_historical_tickers()
        print(f"\n开始下载 {len(tickers)} 只股票的日线数据...")
        download_all(tickers, start=args.start,
                    skip_existing=not args.no_skip)

    merge_all()
