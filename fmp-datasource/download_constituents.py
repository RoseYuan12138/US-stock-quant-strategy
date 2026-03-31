"""
下载 S&P 500 历史成分股数据
- 当前成分股（~503只）
- 历史成分变动记录（~1517条）
- 生成任意历史日期的 point-in-time 成分股表

输出文件：
  cache/sp500_current.parquet
  cache/sp500_historical_changes.parquet
  cache/sp500_pit_index.parquet   ← 每月末各股票是否在指数内
"""
import os
import pandas as pd
from datetime import date, timedelta
from fmp_client import get, ensure_cache_dir


def download_current(force=False) -> pd.DataFrame:
    path = os.path.join(ensure_cache_dir(), "sp500_current.parquet")
    if not force and os.path.exists(path):
        print("  ✅ sp500_current.parquet 已缓存，跳过")
        return pd.read_parquet(path)
    print("下载当前 S&P500 成分股...")
    data = get("sp500-constituent")
    df = pd.DataFrame(data)
    df.to_parquet(path, index=False)
    print(f"  ✅ {len(df)} 只股票 → {path}")
    return df


def download_historical_changes(force=False) -> pd.DataFrame:
    path = os.path.join(ensure_cache_dir(), "sp500_historical_changes.parquet")
    if not force and os.path.exists(path):
        print("  ✅ sp500_historical_changes.parquet 已缓存，跳过")
        return pd.read_parquet(path)
    print("下载 S&P500 历史成分变动...")
    data = get("historical-sp500-constituent")
    df = pd.DataFrame(data)
    # 统一日期格式
    for col in ["dateAdded", "date"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime("%Y-%m-%d")
    path = os.path.join(ensure_cache_dir(), "sp500_historical_changes.parquet")
    df.to_parquet(path, index=False)
    print(f"  ✅ {len(df)} 条变动记录 → {path}")
    return df


def build_pit_index(changes_df: pd.DataFrame, start: str = "2010-01-01") -> pd.DataFrame:
    """
    构建 point-in-time 月末成分股表
    每行：(date, symbol, in_index)
    date 是月末日期，in_index=True 表示该股票当时在指数内
    """
    print("构建 point-in-time 成分股索引...")

    # 生成月末日期序列
    start_dt = pd.Timestamp(start)
    end_dt = pd.Timestamp(date.today().strftime("%Y-%m-%d"))
    month_ends = pd.date_range(start_dt, end_dt, freq="ME").strftime("%Y-%m-%d").tolist()

    rows = []
    for target_date in month_ends:
        universe = _get_universe_at_date(changes_df, target_date)
        for sym in universe:
            rows.append({"date": target_date, "symbol": sym, "in_index": True})

    df = pd.DataFrame(rows)
    path = os.path.join(ensure_cache_dir(), "sp500_pit_index.parquet")
    df.to_parquet(path, index=False)
    print(f"  ✅ {len(month_ends)} 个月末，平均 {len(rows)//max(len(month_ends),1)} 只/月 → {path}")
    return df


def _get_universe_at_date(changes_df: pd.DataFrame, target_date: str) -> set:
    """还原某日期的 S&P500 成分股"""
    universe = set()
    for _, row in changes_df.iterrows():
        added = row.get("dateAdded") or ""
        removed = row.get("date") or ""
        symbol = row.get("symbol") or ""
        removed_ticker = row.get("removedTicker") or ""

        if added and str(added) <= target_date and symbol:
            universe.add(symbol)
        if removed and str(removed) <= target_date and removed_ticker:
            universe.discard(removed_ticker)
    return universe


def get_universe_at_date(target_date: str) -> set:
    """从缓存文件获取某日期的 S&P500 成分股（供其他脚本调用）"""
    path = os.path.join(ensure_cache_dir(), "sp500_historical_changes.parquet")
    if not os.path.exists(path):
        raise FileNotFoundError("请先运行 download_constituents.py")
    changes = pd.read_parquet(path)
    return _get_universe_at_date(changes, target_date)


def get_all_historical_tickers() -> list:
    """获取 2010 年以来出现过的所有 ticker（供下载其他数据用）"""
    path = os.path.join(ensure_cache_dir(), "sp500_historical_changes.parquet")
    if not os.path.exists(path):
        raise FileNotFoundError("请先运行 download_constituents.py")
    changes = pd.read_parquet(path)
    current_path = os.path.join(ensure_cache_dir(), "sp500_current.parquet")
    current = pd.read_parquet(current_path) if os.path.exists(current_path) else pd.DataFrame()

    tickers = set()
    if "symbol" in changes.columns:
        tickers.update(changes["symbol"].dropna().tolist())
    if "removedTicker" in changes.columns:
        tickers.update(changes["removedTicker"].dropna().tolist())
    if "symbol" in current.columns:
        tickers.update(current["symbol"].dropna().tolist())

    tickers = sorted(t for t in tickers if t and isinstance(t, str) and len(t) <= 5)
    print(f"历史 ticker 总数：{len(tickers)}")
    return tickers


if __name__ == "__main__":
    current_df = download_current()
    changes_df = download_historical_changes()
    build_pit_index(changes_df)
    tickers = get_all_historical_tickers()
    print(f"\n完成！历史出现过 {len(tickers)} 只股票，可用于后续下载。")
