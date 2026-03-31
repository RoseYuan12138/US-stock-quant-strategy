"""
下载所有历史 S&P500 成分股的季度基本面数据
- 利润表、资产负债表、现金流、Key Metrics、Ratios
- 使用 filingDate 做 point-in-time 防前视偏差
- 多线程下载，充分利用 Premium 750 calls/min

输出文件：
  cache/fundamentals/{TICKER}.parquet   ← 每只股票一个文件
  cache/fundamentals_merged.parquet     ← 合并后的全量数据
"""
import os
import time
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from fmp_client import get, ensure_cache_dir
from download_constituents import get_all_historical_tickers

FUND_DIR = "fundamentals"
LIMIT = 80  # 每只股票最多拉 80 个季度 = 20 年


def _fetch_statement(symbol: str, endpoint: str) -> pd.DataFrame:
    data = get(endpoint, symbol=symbol, period="quarter", limit=LIMIT)
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    df["_source"] = endpoint
    return df


def download_ticker(symbol: str, force: bool = False) -> bool:
    """下载单只股票的全部基本面数据，合并后存为一个 parquet"""
    cache_dir = ensure_cache_dir(FUND_DIR)
    out_path = os.path.join(cache_dir, f"{symbol}.parquet")

    if not force and os.path.exists(out_path):
        return True  # 已缓存，跳过

    try:
        frames = {}
        for endpoint in ["income-statement", "balance-sheet-statement",
                          "cash-flow-statement", "key-metrics", "ratios"]:
            df = _fetch_statement(symbol, endpoint)
            if not df.empty and "filingDate" in df.columns:
                frames[endpoint] = df

        if not frames:
            return False

        # 以 income-statement 为主表，按 filingDate merge 其他表
        base = frames.get("income-statement", list(frames.values())[0])
        base["filingDate"] = pd.to_datetime(base["filingDate"], errors="coerce")
        base = base.dropna(subset=["filingDate"]).sort_values("filingDate").reset_index(drop=True)

        for name, df in frames.items():
            if name == "income-statement":
                continue
            df["filingDate"] = pd.to_datetime(df["filingDate"], errors="coerce")
            df = df.dropna(subset=["filingDate"]).sort_values("filingDate").reset_index(drop=True)
            # 只取新增列，避免重复
            new_cols = [c for c in df.columns if c not in base.columns or c == "filingDate"]
            if len(new_cols) <= 1:
                continue
            base = pd.merge_asof(
                base, df[new_cols],
                on="filingDate", direction="backward", tolerance=pd.Timedelta("45d")
            )

        base["symbol"] = symbol
        base.to_parquet(out_path, index=False)
        return True

    except PermissionError as e:
        print(f"  ⛔ {symbol}: {e}")
        return False
    except Exception as e:
        print(f"  ❌ {symbol}: {e}")
        return False


def download_all(tickers: list = None, workers: int = 8, force: bool = False):
    """多线程下载所有 ticker 的基本面数据"""
    if tickers is None:
        tickers = get_all_historical_tickers()

    cache_dir = ensure_cache_dir(FUND_DIR)
    # 跳过已有缓存的
    if not force:
        existing = {f.replace(".parquet", "") for f in os.listdir(cache_dir) if f.endswith(".parquet")}
        todo = [t for t in tickers if t not in existing]
    else:
        todo = tickers

    print(f"需要下载：{len(todo)} 只（已缓存：{len(tickers)-len(todo)} 只）")
    if not todo:
        print("全部已缓存，跳过。")
        return

    success, failed = 0, []
    start = time.time()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(download_ticker, t, force): t for t in todo}
        for i, future in enumerate(as_completed(futures), 1):
            ticker = futures[future]
            ok = future.result()
            if ok:
                success += 1
            else:
                failed.append(ticker)
            if i % 50 == 0:
                elapsed = time.time() - start
                rate = i / elapsed * 60
                eta = (len(todo) - i) / (i / elapsed) if i > 0 else 0
                print(f"  进度 {i}/{len(todo)} | 速率 {rate:.0f}只/min | 预计剩余 {eta/60:.1f}min")

    print(f"\n✅ 成功：{success}  ❌ 失败：{len(failed)}")
    if failed:
        print(f"失败列表：{failed[:20]}{'...' if len(failed)>20 else ''}")


def merge_all() -> pd.DataFrame:
    """将所有 ticker 的 parquet 合并为一个大表"""
    cache_dir = ensure_cache_dir(FUND_DIR)
    files = [f for f in os.listdir(cache_dir) if f.endswith(".parquet")]
    print(f"合并 {len(files)} 只股票的数据...")

    dfs = []
    for f in files:
        try:
            dfs.append(pd.read_parquet(os.path.join(cache_dir, f)))
        except Exception:
            pass

    merged = pd.concat(dfs, ignore_index=True)
    out = os.path.join(ensure_cache_dir(), "fundamentals_merged.parquet")
    merged.to_parquet(out, index=False)
    print(f"✅ 合并完成：{len(merged)} 行 × {len(merged.columns)} 列 → {out}")
    return merged


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=8, help="并发线程数")
    parser.add_argument("--force", action="store_true", help="强制重新下载（忽略缓存）")
    parser.add_argument("--merge-only", action="store_true", help="只合并已有缓存")
    args = parser.parse_args()

    if not args.merge_only:
        download_all(workers=args.workers, force=args.force)
    merge_all()
