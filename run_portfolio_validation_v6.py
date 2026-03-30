#!/usr/bin/env python3
"""
V6 策略验证 — 新闻情绪因子
对比: V6 (V5 + News Sentiment) vs V5 (无新闻)
测试期: 2018-01-01 ~ 2020-12-31 (新闻数据覆盖范围)
数据起始: 2017-01-01（给动量因子1年热身）
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
from data.historical_fundamentals import HistoricalFundamentalFetcher
from data.historical_news import HistoricalNewsProvider
from strategy.earnings_surprise import EarningsSurpriseScorer
from strategy.insider_signal import InsiderSignalScorer
from strategy.portfolio_strategy import PortfolioConfig
from backtest.portfolio_backtester import PortfolioBacktester

SP100_TICKERS = [
    'AAPL', 'MSFT', 'GOOGL', 'GOOG', 'AMZN', 'NVDA', 'META', 'TSLA',
    'AVGO', 'ORCL', 'CRM', 'AMD', 'ADBE', 'INTC', 'CSCO', 'QCOM',
    'TXN', 'IBM', 'INTU', 'AMAT',
    'JPM', 'BAC', 'GS', 'MS', 'WFC', 'C', 'BLK', 'SCHW', 'AXP', 'BK',
    'USB', 'COF',
    'UNH', 'JNJ', 'LLY', 'ABBV', 'MRK', 'PFE', 'TMO', 'ABT', 'DHR',
    'BMY', 'AMGN', 'GILD', 'MDT',
    'WMT', 'HD', 'PG', 'KO', 'PEP', 'COST', 'MCD', 'NKE', 'SBUX',
    'TGT', 'LOW',
    'CAT', 'BA', 'HON', 'GE', 'RTX', 'UPS', 'DE', 'LMT', 'MMM',
    'XOM', 'CVX', 'COP', 'SLB',
    'DIS', 'CMCSA', 'NFLX', 'T', 'VZ', 'TMUS',
    'NEE', 'DUK', 'SO',
    'V', 'MA', 'PYPL', 'ACN', 'LIN', 'UNP', 'PM',
]

MACRO_TICKERS = {
    'tnx': '^TNX', 'irx': '^IRX', 'vix': '^VIX', 'hyg': 'HYG', 'lqd': 'LQD',
}

# 新闻数据覆盖 2009-2020，用 2018-2020 做回测
START_DATE = '2018-01-01'
END_DATE = '2020-12-31'
DATA_START = '2017-01-01'

BASE_CONFIG = dict(
    top_n=10, min_combined_score=55, min_momentum_score=40,
    weight_fundamental=0.5, weight_momentum=0.3, weight_analyst=0.2,
    max_single_weight=0.12, spy_base_weight=0.20,
    trailing_stop_pct=0.25, use_regime_filter=True,
    rebalance_freq='monthly', initial_cash=100000, commission=5,
)


def main():
    price_fetcher = DataFetcher(cache_dir='./data/cache')
    fund_fetcher = FundamentalFetcher(cache_dir='./data/cache/fundamentals')
    screener = ValueScreener()
    hist_fund = HistoricalFundamentalFetcher()
    earnings_scorer = EarningsSurpriseScorer()
    insider_scorer = InsiderSignalScorer()
    news_provider = HistoricalNewsProvider()

    tickers = list(dict.fromkeys(SP100_TICKERS))

    print(f"{'='*80}")
    print(f"V6 策略验证 — 新闻情绪因子")
    print(f"对比: V6 (V5 + News) vs V5 (无新闻)")
    print(f"标的池: S&P 100 ~{len(tickers)} 只")
    print(f"周期: {START_DATE} ~ {END_DATE}")
    print(f"{'='*80}")

    # 1. 宏观
    print(f"\n[1] 宏观数据...")
    macro_data = {}
    for key, ticker in MACRO_TICKERS.items():
        data = price_fetcher.fetch_historical_data(ticker, start_date=DATA_START, end_date=END_DATE)
        if data is not None and len(data) > 50:
            macro_data[key] = data

    # 2. 价格
    print(f"\n[2] 价格数据...")
    price_data = {}
    for i, ticker in enumerate(tickers):
        data = price_fetcher.fetch_historical_data(ticker, start_date=DATA_START, end_date=END_DATE)
        if data is not None and len(data) > 100:
            price_data[ticker] = data
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(tickers)}...")
    print(f"  有效: {len(price_data)}/{len(tickers)}")

    # 3. 基本面 + SI
    print(f"\n[3] 基本面...")
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

    # 4. 历史财报
    print(f"\n[4] 历史财报...")
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

    # 7. 新闻数据
    print(f"\n[7] 新闻情绪数据...")
    news_provider.load_data(tickers=list(price_data.keys()))
    coverage = news_provider.get_coverage_stats(list(price_data.keys()))
    print(f"  新闻覆盖: {len(coverage)}/{len(price_data)} tickers")
    if coverage:
        total_news = sum(s['count'] for s in coverage.values())
        print(f"  总新闻数: {total_news:,}")
        # 检查日期范围
        min_dates = [s['min_date'] for s in coverage.values()]
        max_dates = [s['max_date'] for s in coverage.values()]
        print(f"  日期范围: {min(min_dates)} ~ {max(max_dates)}")

    # 8. SPY
    spy_data = price_fetcher.fetch_historical_data('SPY', start_date=DATA_START, end_date=END_DATE)

    # 9. 回测
    print(f"\n[8] 回测...")
    all_reports = {}

    configs = {
        'V6 Standard (News)': (
            PortfolioConfig(**BASE_CONFIG),
            True,  # use_news
        ),
        'V5 Standard (No News)': (
            PortfolioConfig(**BASE_CONFIG),
            False,  # no news
        ),
        'V6 Aggressive (News)': (
            PortfolioConfig(
                **{**BASE_CONFIG,
                   'top_n': 15, 'min_combined_score': 45, 'min_momentum_score': 30,
                   'weight_fundamental': 0.4, 'weight_momentum': 0.4,
                   'max_single_weight': 0.10, 'spy_base_weight': 0.10,
                   'trailing_stop_pct': 0.30}
            ),
            True,
        ),
        'V6 Conservative (News)': (
            PortfolioConfig(
                **{**BASE_CONFIG,
                   'top_n': 8, 'min_combined_score': 60, 'min_momentum_score': 45,
                   'weight_fundamental': 0.6, 'weight_momentum': 0.2,
                   'spy_base_weight': 0.25, 'trailing_stop_pct': 0.20}
            ),
            True,
        ),
    }

    for config_name, (config, use_news) in configs.items():
        print(f"\n  --- {config_name} ---")
        backtester = PortfolioBacktester(config)
        try:
            daily_df, report, trade_log = backtester.run(
                price_data, fundamental_scores, spy_data,
                start_date=START_DATE, end_date=END_DATE,
                use_historical_fundamentals=True,
                macro_data=macro_data,
                short_interest=short_interest,
                insider_scorer=insider_scorer,
                news_provider=news_provider if use_news else None,
            )
        except Exception as e:
            print(f"  失败: {e}")
            import traceback
            traceback.print_exc()
            continue

        if report is None:
            continue

        all_reports[config_name] = {'report': report, 'daily_df': daily_df, 'trade_log': trade_log}

        beat = "BEAT" if report['beat_benchmark'] else "MISS"
        print(f"  收益: {report['total_return_pct']:+.1f}%  |  "
              f"Alpha: {report['alpha_pct']:+.1f}%  |  "
              f"夏普: {report['sharpe_ratio']:.2f}  |  "
              f"回撤: {report['max_drawdown_pct']:.1f}%  |  "
              f"胜率: {report['win_rate']:.0f}%  |  "
              f"SPY: {beat}")

    # 报告
    print(f"\n\n{'='*90}")
    print(f"V6 策略 — 新闻情绪因子 回测报告 ({START_DATE} ~ {END_DATE})")
    print(f"{'='*90}")

    print(f"\n{'Config':30s} {'Return%':>9s} {'Alpha%':>8s} {'Sharpe':>7s} {'MaxDD%':>7s} {'WinR%':>6s} {'AvgPos':>7s} {'Beat':>5s}")
    print("-" * 85)

    for name, data in all_reports.items():
        r = data['report']
        beat = "Y" if r['beat_benchmark'] else "N"
        print(f"{name:30s} {r['total_return_pct']:+8.1f}% {r['alpha_pct']:+7.1f}% "
              f"{r['sharpe_ratio']:7.2f} {r['max_drawdown_pct']:6.1f}% "
              f"{r['win_rate']:5.0f}% {r['avg_positions']:6.1f} {beat:>5s}")

    if all_reports:
        r = next(iter(all_reports.values()))['report']
        print(f"{'SPY Buy & Hold':30s} {r['benchmark_return_pct']:+8.1f}% {'0.0':>7s}% "
              f"{r['benchmark_sharpe']:7.2f} {r['benchmark_max_dd_pct']:6.1f}%")

    # V6 vs V5 对比
    if 'V6 Standard (News)' in all_reports and 'V5 Standard (No News)' in all_reports:
        v6 = all_reports['V6 Standard (News)']['report']
        v5 = all_reports['V5 Standard (No News)']['report']
        print(f"\n--- 新闻因子增量 (V6 - V5) ---")
        print(f"  收益差: {v6['total_return_pct'] - v5['total_return_pct']:+.2f}%")
        print(f"  Alpha差: {v6['alpha_pct'] - v5['alpha_pct']:+.2f}%")
        print(f"  夏普差: {v6['sharpe_ratio'] - v5['sharpe_ratio']:+.3f}")
        print(f"  回撤差: {v6['max_drawdown_pct'] - v5['max_drawdown_pct']:+.2f}%")

    # 保存
    output_dir = Path('./reports')
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M')
    json_data = {n: {k: v for k, v in d['report'].items() if k != 'rebalance_log'}
                 for n, d in all_reports.items()}
    with open(output_dir / f"portfolio_v6_news_{ts}.json", 'w') as f:
        json.dump(json_data, f, indent=2, default=str)
    print(f"\nJSON 已保存: reports/portfolio_v6_news_{ts}.json")


if __name__ == '__main__':
    main()
