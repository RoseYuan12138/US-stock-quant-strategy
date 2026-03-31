"""
一键下载所有数据
运行方式：
  export FMP_API_KEY=your_key
  python run_all.py               # 全量下载（首次运行）
  python run_all.py --skip-done   # 跳过已缓存，只补充缺失
  python run_all.py --step macro  # 只运行某一步

估计耗时（Premium 750 calls/min）：
  Step 1 成分股：~1 分钟
  Step 2 基本面：~15-20 分钟（~700只股 × 5个端点）
  Step 3 因子：  ~10-15 分钟（~700只股 × 4个端点）
  Step 4 宏观：  ~2 分钟（FRED 免费，无速率限制）
  Step 5 价格：  ~30-60 分钟（~1612只股 × 5年分段）
"""
import os
import sys
import time
import argparse
from datetime import datetime


def check_api_key():
    key = os.environ.get("FMP_API_KEY")
    if not key:
        print("❌ 未设置 FMP_API_KEY")
        print("   运行：export FMP_API_KEY=你的key")
        sys.exit(1)
    print(f"✅ API Key: {key[:8]}...")


def step1_constituents():
    print("\n" + "="*50)
    print("Step 1: 下载 S&P500 成分股数据")
    print("="*50)
    from download_constituents import download_current, download_historical_changes, build_pit_index
    current = download_current()
    changes = download_historical_changes()
    build_pit_index(changes)


def step2_fundamentals(workers: int = 8, force: bool = False):
    print("\n" + "="*50)
    print("Step 2: 下载季度基本面数据")
    print("="*50)
    from download_fundamentals import download_all, merge_all
    download_all(workers=workers, force=force)
    merge_all()


def step3_factors(workers: int = 6, force: bool = False):
    print("\n" + "="*50)
    print("Step 3: 下载因子信号数据")
    print("="*50)
    from download_factors import download_all, build_monthly_signals
    download_all(workers=workers, force=force)
    build_monthly_signals()


def step4_macro():
    print("\n" + "="*50)
    print("Step 4: 下载宏观数据")
    print("="*50)
    from download_macro import download_treasury_rates, download_all_fred, build_macro_features
    download_treasury_rates()
    download_all_fred()
    build_macro_features()


def step5_prices(start: str = "2010-01-01", force: bool = False):
    print("\n" + "="*50)
    print("Step 5: 下载历史日线价格（OHLCV）")
    print("="*50)
    from download_prices import download_all, merge_all, build_monthly_prices
    from download_constituents import get_all_historical_tickers
    tickers = get_all_historical_tickers()
    print(f"  目标：{len(tickers)} 只历史成分股 + SPY")
    download_all(tickers, start=start, skip_existing=not force)
    merge_all()
    build_monthly_prices()


def print_summary():
    print("\n" + "="*50)
    print("数据下载完成！缓存文件概览：")
    print("="*50)
    cache_dir = os.path.join(os.path.dirname(__file__), "cache")

    summary = {
        "S&P500成分股": ["sp500_current.parquet", "sp500_historical_changes.parquet", "sp500_pit_index.parquet"],
        "基本面数据":   ["fundamentals_merged.parquet"],
        "因子数据":     ["factors_merged.parquet"],
        "宏观数据":     ["macro_merged.parquet"],
        "价格数据":     ["prices_merged.parquet"],
    }

    import pandas as pd
    for category, files in summary.items():
        print(f"\n{category}:")
        for f in files:
            path = os.path.join(cache_dir, f)
            if os.path.exists(path):
                df = pd.read_parquet(path)
                size_mb = os.path.getsize(path) / 1024 / 1024
                print(f"  ✅ {f}: {len(df):,} 行 ({size_mb:.1f} MB)")
            else:
                print(f"  ❌ {f}: 未生成")

    # 统计每只股票子目录
    for subdir in ["fundamentals", "earnings", "analyst_grades", "insider_trades", "congressional_trades", "prices"]:
        d = os.path.join(cache_dir, subdir)
        if os.path.exists(d):
            n = len([f for f in os.listdir(d) if f.endswith(".parquet")])
            print(f"  📁 {subdir}/: {n} 只股票")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FMP 数据一键下载")
    parser.add_argument("--step", choices=["constituents", "fundamentals", "factors", "macro", "prices"],
                        help="只运行某一步")
    parser.add_argument("--workers", type=int, default=8, help="并发线程数")
    parser.add_argument("--force", action="store_true", help="强制重新下载（忽略缓存）")
    args = parser.parse_args()

    check_api_key()

    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    start = time.time()

    if args.step == "constituents" or not args.step:
        step1_constituents()
    if args.step == "fundamentals" or not args.step:
        step2_fundamentals(workers=args.workers, force=args.force)
    if args.step == "factors" or not args.step:
        step3_factors(workers=args.workers, force=args.force)
    if args.step == "macro" or not args.step:
        step4_macro()
    if args.step == "prices" or not args.step:
        step5_prices(force=args.force)

    elapsed = time.time() - start
    print(f"\n⏱️  总耗时：{elapsed/60:.1f} 分钟")
    print_summary()
