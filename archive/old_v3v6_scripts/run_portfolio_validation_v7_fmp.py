#!/usr/bin/env python3
"""
V7 策略验证 — 使用 FMP 数据
改进点：
1. 基本面数据：FMP 季度财报 + filingDate PIT（消灭前视偏差）
2. 股票池：sp500_pit_index 历史成分股（消灭生存者偏差）
3. 回测区间：2010-2024（从 84 个月 → ~168 个月）
"""

import sys
import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from data.data_fetcher import DataFetcher
from data.fundamental_fetcher import FundamentalFetcher, ValueScreener
from data.historical_fundamentals import FMPHistoricalFundamentalFetcher
from data.historical_news import HistoricalNewsProvider
from strategy.earnings_surprise import EarningsSurpriseScorer
from strategy.insider_signal import InsiderSignalScorer
from strategy.portfolio_strategy import PortfolioConfig
from backtest.portfolio_backtester import PortfolioBacktester

MACRO_TICKERS = {
    'tnx': '^TNX', 'irx': '^IRX', 'vix': '^VIX', 'hyg': 'HYG', 'lqd': 'LQD',
}

START_DATE = '2011-01-01'   # 给动量因子1年热身（DATA_START=2010）
END_DATE   = '2024-12-31'
DATA_START = '2010-01-01'

BASE_CONFIG = dict(
    top_n=10, min_combined_score=55, min_momentum_score=40,
    weight_fundamental=0.5, weight_momentum=0.3, weight_analyst=0.2,
    max_single_weight=0.12, spy_base_weight=0.20,
    trailing_stop_pct=0.25, use_regime_filter=True,
    rebalance_freq='monthly', initial_cash=100000, commission=5,
)

PIT_INDEX_PATH = Path(__file__).parent / "fmp-datasource/cache/sp500_pit_index.parquet"


def load_sp500_universe():
    """从 PIT 索引获取回测期间所有出现过的 ticker"""
    pit = pd.read_parquet(PIT_INDEX_PATH)
    pit["date"] = pd.to_datetime(pit["date"])
    in_range = pit[
        (pit["date"] >= DATA_START) &
        (pit["date"] <= END_DATE) &
        (pit["in_index"] == True)
    ]
    tickers = sorted(in_range["symbol"].unique().tolist())
    print(f"  历史 S&P500 universe: {len(tickers)} 只 ({DATA_START} ~ {END_DATE})")
    return tickers


def get_pit_members(target_date: str) -> set:
    """返回某日期 S&P500 成分股集合（用于每月过滤）"""
    pit = pd.read_parquet(PIT_INDEX_PATH)
    pit["date"] = pd.to_datetime(pit["date"])
    target_ts = pd.Timestamp(target_date)
    # 找最近一个月末快照
    avail = pit[pit["date"] <= target_ts]
    if avail.empty:
        return set()
    last_date = avail["date"].max()
    members = pit[(pit["date"] == last_date) & (pit["in_index"] == True)]["symbol"]
    return set(members)


def compute_tstat(monthly_alphas):
    """计算月度 alpha 序列的 t-stat"""
    arr = np.array(monthly_alphas)
    if len(arr) < 2:
        return None
    return arr.mean() / (arr.std(ddof=1) / np.sqrt(len(arr)))


def main():
    price_fetcher = DataFetcher(cache_dir='./data/cache')
    fund_fetcher  = FundamentalFetcher(cache_dir='./data/cache/fundamentals')
    screener      = ValueScreener()
    hist_fund     = FMPHistoricalFundamentalFetcher()   # ← FMP PIT 数据
    earnings_scorer = EarningsSurpriseScorer()
    insider_scorer  = InsiderSignalScorer()
    news_provider   = HistoricalNewsProvider()

    tickers = load_sp500_universe()

    print(f"{'='*80}")
    print(f"V7 策略验证 — FMP 数据 + 历史 S&P500 universe")
    print(f"对比: V7 (FMP数据) vs V6 baseline (yfinance)")
    print(f"标的池: 历史 S&P500 {len(tickers)} 只")
    print(f"周期: {START_DATE} ~ {END_DATE}")
    print(f"{'='*80}")

    # 1. 宏观
    print(f"\n[1] 宏观数据...")
    macro_data = {}
    for key, ticker in MACRO_TICKERS.items():
        data = price_fetcher.fetch_historical_data(ticker, start_date=DATA_START, end_date=END_DATE)
        if data is not None and len(data) > 50:
            macro_data[key] = data

    # 2. 价格（只拉能拿到数据的）
    print(f"\n[2] 价格数据（{len(tickers)} 只，跳过无数据的）...")
    price_data = {}
    for i, ticker in enumerate(tickers):
        data = price_fetcher.fetch_historical_data(ticker, start_date=DATA_START, end_date=END_DATE)
        if data is not None and len(data) > 100:
            price_data[ticker] = data
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(tickers)} — 有效 {len(price_data)} 只...")
    print(f"  有效价格数据: {len(price_data)} 只")

    # 3. 当前基本面快照（供 screener 用）
    print(f"\n[3] 基本面快照...")
    fund_data = fund_fetcher.fetch_batch(list(price_data.keys()))
    screening_df = screener.screen_universe(fund_data)
    fundamental_scores = {}
    short_interest = {}
    for _, row in screening_df.iterrows():
        fundamental_scores[row['ticker']] = {
            'total_score': row['total_score'],
            'analyst_score': row.get('analyst_score', row['total_score']),
        }
    for tk, fd in fund_data.items():
        si = fd.get('short_percent_of_float')
        if si is not None:
            short_interest[tk] = si

    # 4. 预热 FMP PIT 基本面缓存
    print(f"\n[4] 预热 FMP 基本面缓存...")
    for ticker in price_data.keys():
        hist_fund.load_ticker(ticker)

    # 5. Earnings
    print(f"\n[5] Earnings Surprise...")
    for ticker in price_data.keys():
        earnings_scorer.get_earnings_data(ticker)

    # 6. Insider
    print(f"\n[6] Insider Trading...")
    insider_loaded = 0
    for ticker in price_data.keys():
        data = insider_scorer.get_insider_data(ticker)
        if data is not None and not data.empty:
            insider_loaded += 1
    print(f"  有 insider 数据: {insider_loaded}/{len(price_data)}")

    # 7. SPY
    spy_data = price_fetcher.fetch_historical_data('SPY', start_date=DATA_START, end_date=END_DATE)

    # 8. 回测
    print(f"\n[8] 回测...")
    all_reports = {}

    configs = {
        'V7 FMP Standard': (
            PortfolioConfig(**BASE_CONFIG), False,
        ),
        'V7 FMP + News': (
            PortfolioConfig(**BASE_CONFIG), True,
        ),
    }

    for config_name, (config, use_news) in configs.items():
        if use_news:
            news_provider.load_data(tickers=list(price_data.keys()))

        print(f"\n  --- {config_name} ---")
        backtester = PortfolioBacktester(config)
        try:
            daily_df, report, trade_log = backtester.run(
                price_data, fundamental_scores, spy_data,
                start_date=START_DATE, end_date=END_DATE,
                use_historical_fundamentals=True,
                historical_fundamental_fetcher=hist_fund,
                macro_data=macro_data,
                short_interest=short_interest,
                insider_scorer=insider_scorer,
                news_provider=news_provider if use_news else None,
            )
        except Exception as e:
            print(f"  失败: {e}")
            import traceback; traceback.print_exc()
            continue

        if report is None:
            continue

        all_reports[config_name] = {'report': report, 'daily_df': daily_df, 'trade_log': trade_log}

        # 计算 t-stat
        monthly_excess = None
        if daily_df is not None and 'portfolio_return' in daily_df.columns:
            monthly = daily_df.resample('ME').last()
            if 'benchmark_return' in monthly.columns:
                monthly_excess = (monthly['portfolio_return'] - monthly['benchmark_return']).dropna().tolist()

        tstat = compute_tstat(monthly_excess) if monthly_excess else None
        tstat_str = f"{tstat:.3f}" if tstat else "N/A"
        n_months = len(monthly_excess) if monthly_excess else 0
        sig = "✅ 显著" if tstat and abs(tstat) > 1.96 else ("⚠️ 边缘" if tstat and abs(tstat) > 1.5 else "❌ 不显著")

        beat = "BEAT" if report['beat_benchmark'] else "MISS"
        print(f"  收益: {report['total_return_pct']:+.1f}%  |  "
              f"Alpha: {report['alpha_pct']:+.1f}%  |  "
              f"夏普: {report['sharpe_ratio']:.2f}  |  "
              f"回撤: {report['max_drawdown_pct']:.1f}%  |  "
              f"t-stat: {tstat_str} ({n_months}mo) {sig}  |  "
              f"SPY: {beat}")

    # 汇总报告
    print(f"\n\n{'='*90}")
    print(f"V7 回测报告 ({START_DATE} ~ {END_DATE}，FMP PIT 数据)")
    print(f"{'='*90}")
    print(f"{'Config':30s} {'Return%':>9s} {'Alpha%':>8s} {'Sharpe':>7s} {'MaxDD%':>7s} {'t-stat':>8s} {'显著':>6s}")
    print("-" * 85)

    for name, data in all_reports.items():
        r = data['report']
        df = data.get('daily_df')
        monthly_excess = None
        if df is not None and 'portfolio_return' in df.columns and 'benchmark_return' in df.columns:
            monthly = df.resample('ME').last()
            monthly_excess = (monthly['portfolio_return'] - monthly['benchmark_return']).dropna().tolist()
        tstat = compute_tstat(monthly_excess)
        tstat_str = f"{tstat:.3f}" if tstat else "N/A"
        sig = "✅" if tstat and abs(tstat) > 1.96 else ("⚠️" if tstat and abs(tstat) > 1.5 else "❌")
        print(f"{name:30s} {r['total_return_pct']:+8.1f}% {r['alpha_pct']:+7.1f}% "
              f"{r['sharpe_ratio']:7.2f} {r['max_drawdown_pct']:6.1f}% {tstat_str:>8s} {sig:>6s}")

    if all_reports:
        r = next(iter(all_reports.values()))['report']
        print(f"{'SPY Buy & Hold':30s} {r['benchmark_return_pct']:+8.1f}% {'0.0':>7s}% "
              f"{r['benchmark_sharpe']:7.2f} {r['benchmark_max_dd_pct']:6.1f}%")

    # 保存
    output_dir = Path('./reports')
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M')
    json_data = {n: {k: v for k, v in d['report'].items() if k != 'rebalance_log'}
                 for n, d in all_reports.items()}
    with open(output_dir / f"portfolio_v7_fmp_{ts}.json", 'w') as f:
        json.dump(json_data, f, indent=2, default=str)
    print(f"\nJSON 已保存: reports/portfolio_v7_fmp_{ts}.json")


if __name__ == '__main__':
    main()
