#!/usr/bin/env python3
"""
样本外回测 (Out-of-Sample Test)
测试策略在从未调参的时间段上的表现
2016-01-01 ~ 2017-12-31 (策略开发时完全没见过这段数据)
数据起始: 2015-01-01 (给动量因子1年热身)
"""

import sys
import json
import numpy as np
import pandas as pd
import yfinance as yf
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from data.fundamental_fetcher import FundamentalFetcher, ValueScreener
from data.historical_fundamentals import HistoricalFundamentalFetcher
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

START_DATE = '2016-01-01'
END_DATE = '2017-12-31'
DATA_START = '2015-01-01'


def download_prices(tickers, start, end):
    """直接从 yfinance 下载，不走缓存（避免缓存日期不够）"""
    price_data = {}
    failed = []

    for i, ticker in enumerate(tickers):
        try:
            raw = yf.download(ticker, start=start, end=end, progress=False, interval='1d')
            if raw is not None and len(raw) > 100:
                if isinstance(raw.columns, pd.MultiIndex):
                    raw.columns = raw.columns.droplevel(1)
                raw = raw.dropna()
                cols = [c for c in ['Open', 'High', 'Low', 'Close', 'Volume'] if c in raw.columns]
                if cols:
                    price_data[ticker] = raw[cols]
            else:
                failed.append(ticker)
        except Exception:
            failed.append(ticker)

        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(tickers)}...")

    return price_data, failed


def main():
    print(f"{'='*80}")
    print(f"样本外回测 (Out-of-Sample)")
    print(f"这段时间 (2016-2017) 从未用于策略开发/调参")
    print(f"如果 Alpha > 0，说明策略有泛化能力，不是过拟合")
    print(f"{'='*80}")

    # 1. 下载价格（绕过缓存）
    print(f"\n[1] 下载价格数据 (2015-2017)...")
    price_data, failed = download_prices(SP100_TICKERS, DATA_START, END_DATE)
    print(f"  有效: {len(price_data)}/{len(SP100_TICKERS)}")
    if failed:
        print(f"  失败: {', '.join(failed[:10])}{'...' if len(failed) > 10 else ''}")

    # 2. 基本面
    print(f"\n[2] 基本面数据...")
    fund_fetcher = FundamentalFetcher(cache_dir='./data/cache/fundamentals')
    screener = ValueScreener()
    fund_data = fund_fetcher.fetch_batch(list(price_data.keys()))
    screening_df = screener.screen_universe(fund_data)

    fundamental_scores = {}
    for _, row in screening_df.iterrows():
        fundamental_scores[row['ticker']] = {
            'total_score': row['total_score'],
            'analyst_score': row.get('analyst_score', row['total_score']),
        }

    # 3. 历史财报
    print(f"\n[3] 历史财报...")
    hist_fund = HistoricalFundamentalFetcher()
    for ticker in price_data.keys():
        hist_fund.load_ticker(ticker)

    # 4. SPY
    print(f"\n[4] SPY 基准...")
    spy_raw = yf.download('SPY', start=DATA_START, end=END_DATE, progress=False)
    if isinstance(spy_raw.columns, pd.MultiIndex):
        spy_raw.columns = spy_raw.columns.droplevel(1)
    spy_data = spy_raw[['Open', 'High', 'Low', 'Close', 'Volume']].dropna()

    # 5. 宏观数据
    print(f"\n[5] 宏观数据...")
    macro_tickers = {'^TNX': 'tnx', '^IRX': 'irx', '^VIX': 'vix', 'HYG': 'hyg', 'LQD': 'lqd'}
    macro_data = {}
    for yf_ticker, key in macro_tickers.items():
        raw = yf.download(yf_ticker, start=DATA_START, end=END_DATE, progress=False)
        if raw is not None and len(raw) > 50:
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.droplevel(1)
            macro_data[key] = raw.dropna()

    # 6. 回测
    print(f"\n[6] 回测...")

    configs = {
        'Standard': PortfolioConfig(
            top_n=10, min_combined_score=55, min_momentum_score=40,
            weight_fundamental=0.5, weight_momentum=0.3, weight_analyst=0.2,
            max_single_weight=0.12, spy_base_weight=0.20,
            trailing_stop_pct=0.25, use_regime_filter=True,
            rebalance_freq='monthly', initial_cash=100000, commission=5,
        ),
        'Aggressive': PortfolioConfig(
            top_n=15, min_combined_score=45, min_momentum_score=30,
            weight_fundamental=0.4, weight_momentum=0.4, weight_analyst=0.2,
            max_single_weight=0.10, spy_base_weight=0.10,
            trailing_stop_pct=0.30, use_regime_filter=True,
            rebalance_freq='monthly', initial_cash=100000, commission=5,
        ),
        'Conservative': PortfolioConfig(
            top_n=8, min_combined_score=60, min_momentum_score=45,
            weight_fundamental=0.6, weight_momentum=0.2, weight_analyst=0.2,
            max_single_weight=0.12, spy_base_weight=0.25,
            trailing_stop_pct=0.20, use_regime_filter=True,
            rebalance_freq='monthly', initial_cash=100000, commission=5,
        ),
    }

    all_reports = {}

    for name, config in configs.items():
        print(f"\n  --- {name} ---")
        backtester = PortfolioBacktester(config)
        try:
            daily_df, report, trade_log = backtester.run(
                price_data, fundamental_scores, spy_data,
                start_date=START_DATE, end_date=END_DATE,
                use_historical_fundamentals=True,
                macro_data=macro_data,
            )
        except Exception as e:
            print(f"  失败: {e}")
            import traceback
            traceback.print_exc()
            continue

        if report is None:
            continue

        all_reports[name] = report
        beat = "BEAT" if report['beat_benchmark'] else "MISS"
        print(f"  收益: {report['total_return_pct']:+.1f}%  |  "
              f"Alpha: {report['alpha_pct']:+.1f}%  |  "
              f"夏普: {report['sharpe_ratio']:.2f}  |  "
              f"回撤: {report['max_drawdown_pct']:.1f}%  |  "
              f"胜率: {report['win_rate']:.0f}%  |  "
              f"SPY: {beat}")

    # 报告
    print(f"\n\n{'='*80}")
    print(f"样本外回测结果 ({START_DATE} ~ {END_DATE})")
    print(f"{'='*80}")

    print(f"\n{'Config':15s} {'Return%':>9s} {'Alpha%':>8s} {'Sharpe':>7s} {'MaxDD%':>7s} {'WinR%':>6s} {'Beat':>5s}")
    print("-" * 60)

    for name, r in all_reports.items():
        beat = "Y" if r['beat_benchmark'] else "N"
        print(f"{name:15s} {r['total_return_pct']:+8.1f}% {r['alpha_pct']:+7.1f}% "
              f"{r['sharpe_ratio']:7.2f} {r['max_drawdown_pct']:6.1f}% "
              f"{r['win_rate']:5.0f}% {beat:>5s}")

    if all_reports:
        r = next(iter(all_reports.values()))
        print(f"{'SPY':15s} {r['benchmark_return_pct']:+8.1f}% {'0.0':>7s}% "
              f"{r['benchmark_sharpe']:7.2f} {r['benchmark_max_dd_pct']:6.1f}%")

    # 判定
    print(f"\n{'='*80}")
    print("过拟合判定")
    print(f"{'='*80}")
    alphas = [r['alpha_pct'] for r in all_reports.values()]
    avg_alpha = np.mean(alphas) if alphas else 0
    if avg_alpha > 0:
        print(f"  平均 Alpha: {avg_alpha:+.1f}% → 策略在样本外有效，不太可能过拟合")
    elif avg_alpha > -3:
        print(f"  平均 Alpha: {avg_alpha:+.1f}% → 策略在样本外略负，可能有轻度过拟合")
    else:
        print(f"  平均 Alpha: {avg_alpha:+.1f}% → 策略在样本外明显失效，过拟合风险高")

    # 保存
    output_dir = Path('./reports')
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M')
    with open(output_dir / f"oos_test_{ts}.json", 'w') as f:
        json.dump(all_reports, f, indent=2, default=str)
    print(f"\nJSON: reports/oos_test_{ts}.json")


if __name__ == '__main__':
    main()
