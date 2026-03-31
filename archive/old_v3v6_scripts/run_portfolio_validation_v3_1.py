#!/usr/bin/env python3
"""
V3.1 组合策略验证
改进点（相对V3）：
1. S&P 500 核心成分股（~150只，覆盖主要行业龙头）
2. Earnings Surprise 因子（PEAD效应，免费数据）
3. 回测周期尝试拉长（取决于数据可用性）

注意：完整 S&P 500 (500只) 下载时间太长，选取各行业 Top 市值 150 只作为替代
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
from strategy.earnings_surprise import EarningsSurpriseScorer
from strategy.portfolio_strategy import PortfolioConfig
from backtest.portfolio_backtester import PortfolioBacktester

# === S&P 500 核心成分股（约150只，按行业覆盖） ===
SP500_CORE = [
    # === 科技 (30) ===
    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'AVGO',
    'ORCL', 'CRM', 'AMD', 'ADBE', 'INTC', 'CSCO', 'QCOM', 'TXN',
    'IBM', 'INTU', 'AMAT', 'NOW', 'MU', 'LRCX', 'KLAC', 'SNPS',
    'CDNS', 'PANW', 'CRWD', 'FTNT', 'MRVL', 'NXPI',
    # === 金融 (20) ===
    'JPM', 'BAC', 'GS', 'MS', 'WFC', 'C', 'BLK', 'SCHW', 'AXP', 'BK',
    'USB', 'COF', 'PNC', 'TFC', 'ICE', 'CME', 'MCO', 'SPGI', 'AON', 'MMC',
    # === 医疗 (20) ===
    'UNH', 'JNJ', 'LLY', 'ABBV', 'MRK', 'PFE', 'TMO', 'ABT', 'DHR',
    'BMY', 'AMGN', 'GILD', 'MDT', 'ISRG', 'VRTX', 'REGN', 'SYK',
    'EW', 'ZTS', 'HCA',
    # === 消费必需 (12) ===
    'WMT', 'PG', 'KO', 'PEP', 'COST', 'PM', 'MO', 'CL', 'MDLZ',
    'KHC', 'GIS', 'SJM',
    # === 消费可选 (15) ===
    'HD', 'MCD', 'NKE', 'SBUX', 'TGT', 'LOW', 'TJX', 'BKNG',
    'MAR', 'CMG', 'ROST', 'DHI', 'LEN', 'GM', 'F',
    # === 工业 (15) ===
    'CAT', 'BA', 'HON', 'GE', 'RTX', 'UPS', 'DE', 'LMT', 'MMM',
    'UNP', 'CSX', 'NSC', 'WM', 'EMR', 'ITW',
    # === 能源 (8) ===
    'XOM', 'CVX', 'COP', 'SLB', 'EOG', 'MPC', 'PSX', 'VLO',
    # === 通信 (8) ===
    'DIS', 'CMCSA', 'NFLX', 'T', 'VZ', 'TMUS', 'CHTR', 'EA',
    # === 公用事业 (5) ===
    'NEE', 'DUK', 'SO', 'D', 'AEP',
    # === 地产 (5) ===
    'PLD', 'AMT', 'CCI', 'EQIX', 'SPG',
    # === 材料 (5) ===
    'LIN', 'APD', 'SHW', 'ECL', 'FCX',
    # === 支付/金融科技 (5) ===
    'V', 'MA', 'PYPL', 'FIS', 'ACN',
]

START_DATE = '2018-01-01'
END_DATE = '2025-12-31'
DATA_START = '2017-01-01'

CONFIGS = {
    'V3.1 Standard': PortfolioConfig(
        top_n=15, min_combined_score=55, min_momentum_score=40,
        weight_fundamental=0.5, weight_momentum=0.3, weight_analyst=0.2,
        max_single_weight=0.10, spy_base_weight=0.20,
        trailing_stop_pct=0.25, use_regime_filter=True,
        rebalance_freq='monthly', initial_cash=100000, commission=5,
    ),
    'V3.1 Aggressive': PortfolioConfig(
        top_n=20, min_combined_score=45, min_momentum_score=35,
        weight_fundamental=0.4, weight_momentum=0.4, weight_analyst=0.2,
        max_single_weight=0.08, spy_base_weight=0.10,
        trailing_stop_pct=0.30, use_regime_filter=True,
        rebalance_freq='monthly', initial_cash=100000, commission=5,
    ),
    'V3.1 Conservative': PortfolioConfig(
        top_n=10, min_combined_score=60, min_momentum_score=45,
        weight_fundamental=0.6, weight_momentum=0.2, weight_analyst=0.2,
        max_single_weight=0.12, spy_base_weight=0.25,
        trailing_stop_pct=0.20, use_regime_filter=True,
        rebalance_freq='monthly', initial_cash=100000, commission=5,
    ),
    'V3.1 Quarterly': PortfolioConfig(
        top_n=15, min_combined_score=55, min_momentum_score=40,
        weight_fundamental=0.5, weight_momentum=0.3, weight_analyst=0.2,
        max_single_weight=0.10, spy_base_weight=0.20,
        trailing_stop_pct=0.25, use_regime_filter=True,
        rebalance_freq='quarterly', initial_cash=100000, commission=5,
    ),
}


def run_validation():
    price_fetcher = DataFetcher(cache_dir='./data/cache')
    fund_fetcher = FundamentalFetcher(cache_dir='./data/cache/fundamentals')
    screener = ValueScreener()
    hist_fund = HistoricalFundamentalFetcher()
    earnings_scorer = EarningsSurpriseScorer()

    tickers = list(dict.fromkeys(SP500_CORE))  # 去重保序

    print(f"{'='*80}")
    print(f"V3.1 组合策略验证")
    print(f"标的池: S&P 500 核心 ~{len(tickers)} 只")
    print(f"周期: {START_DATE} ~ {END_DATE}")
    print(f"新增: Earnings Surprise 因子 (PEAD)")
    print(f"{'='*80}")

    # 1. 价格数据
    print(f"\n[Step 1] 获取价格数据...")
    price_data = {}
    for i, ticker in enumerate(tickers):
        data = price_fetcher.fetch_historical_data(ticker, start_date=DATA_START, end_date=END_DATE)
        if data is not None and len(data) > 200:
            price_data[ticker] = data
        if (i + 1) % 30 == 0:
            print(f"  已处理 {i+1}/{len(tickers)}...")

    print(f"  有效标的: {len(price_data)}/{len(tickers)}")

    # 2. 当前基本面
    print(f"\n[Step 2] 获取基本面数据...")
    fund_data = fund_fetcher.fetch_batch(list(price_data.keys()))
    screening_df = screener.screen_universe(fund_data)

    fundamental_scores = {}
    for _, row in screening_df.iterrows():
        fundamental_scores[row['ticker']] = {
            'total_score': row['total_score'],
            'analyst_score': row.get('analyst_score', row['total_score']),
        }

    buy_count = len(screening_df[screening_df['signal'] == 'BUY'])
    hold_count = len(screening_df[screening_df['signal'] == 'HOLD'])
    avoid_count = len(screening_df[screening_df['signal'] == 'AVOID'])
    print(f"  BUY: {buy_count} | HOLD: {hold_count} | AVOID: {avoid_count}")

    # 3. 历史基本面
    print(f"\n[Step 3] 加载历史财报数据...")
    hist_loaded = 0
    for i, ticker in enumerate(price_data.keys()):
        data = hist_fund.load_ticker(ticker)
        if data and data.get('quarterly_scores'):
            hist_loaded += 1
        if (i + 1) % 30 == 0:
            print(f"  已处理 {i+1}/{len(price_data)}...")
    print(f"  有历史财报: {hist_loaded}/{len(price_data)}")

    # 4. 预加载 earnings data
    print(f"\n[Step 4] 加载 Earnings Surprise 数据...")
    earnings_loaded = 0
    for i, ticker in enumerate(price_data.keys()):
        ed = earnings_scorer.get_earnings_data(ticker)
        if ed:
            earnings_loaded += 1
        if (i + 1) % 30 == 0:
            print(f"  已处理 {i+1}/{len(price_data)}...")
    print(f"  有 earnings 数据: {earnings_loaded}/{len(price_data)}")

    # 5. 基准
    print(f"\n[Step 5] 获取 SPY 基准...")
    spy_data = price_fetcher.fetch_historical_data('SPY', start_date=DATA_START, end_date=END_DATE)
    print(f"  SPY: {len(spy_data)} 行")

    # 6. 回测
    print(f"\n[Step 6] 运行回测...")
    all_reports = {}

    for config_name, config in CONFIGS.items():
        print(f"\n  --- {config_name} ---")
        backtester = PortfolioBacktester(config)

        try:
            daily_df, report, trade_log = backtester.run(
                price_data, fundamental_scores, spy_data,
                start_date=START_DATE, end_date=END_DATE,
                use_historical_fundamentals=True,
            )
        except Exception as e:
            print(f"  回测失败: {e}")
            import traceback
            traceback.print_exc()
            continue

        if report is None:
            continue

        all_reports[config_name] = {
            'report': report, 'daily_df': daily_df, 'trade_log': trade_log,
        }

        beat = "BEAT" if report['beat_benchmark'] else "MISS"
        print(f"  收益: {report['total_return_pct']:+.1f}%  |  "
              f"年化: {report['annual_return_pct']:+.1f}%  |  "
              f"Alpha: {report['alpha_pct']:+.1f}%  |  "
              f"夏普: {report['sharpe_ratio']:.2f}  |  "
              f"回撤: {report['max_drawdown_pct']:.1f}%  |  "
              f"胜率: {report['win_rate']:.0f}%  |  "
              f"SPY: {beat}")

    return all_reports


def generate_report(all_reports):
    lines = []
    lines.append("=" * 95)
    lines.append("V3.1 组合策略验证报告")
    lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"周期: {START_DATE} ~ {END_DATE}")
    lines.append(f"标的池: S&P 500 核心 ~{len(SP500_CORE)} 只")
    lines.append(f"改进: Earnings Surprise 因子 + 更大标的池")
    lines.append("=" * 95)

    # 对比表
    lines.append(f"\n{'Config':30s} {'Return%':>9s} {'Annual%':>8s} {'Alpha%':>8s} "
                 f"{'Sharpe':>7s} {'MaxDD%':>7s} {'WinR%':>6s} {'AvgPos':>7s} {'Beat':>5s}")
    lines.append("-" * 95)

    for name, data in all_reports.items():
        r = data['report']
        beat = "Y" if r['beat_benchmark'] else "N"
        lines.append(
            f"{name:30s} {r['total_return_pct']:+8.1f}% {r['annual_return_pct']:+7.1f}% "
            f"{r['alpha_pct']:+7.1f}% {r['sharpe_ratio']:7.2f} {r['max_drawdown_pct']:6.1f}% "
            f"{r['win_rate']:5.0f}% {r['avg_positions']:6.1f} {beat:>5s}"
        )

    if all_reports:
        r = next(iter(all_reports.values()))['report']
        lines.append(
            f"{'SPY Buy & Hold':30s} {r['benchmark_return_pct']:+8.1f}% "
            f"{r['benchmark_annual_pct']:+7.1f}% {'0.0':>7s}% "
            f"{r['benchmark_sharpe']:7.2f} {r['benchmark_max_dd_pct']:6.1f}%"
        )

    # 验证
    lines.append(f"\n{'='*95}")
    lines.append("验证标准")
    lines.append(f"{'='*95}")
    for name, data in all_reports.items():
        r = data['report']
        checks = {
            '年化 > 10%': r['annual_return_pct'] > 10,
            'Alpha > 0': r['alpha_pct'] > 0,
            '夏普 > 0.8': r['sharpe_ratio'] > 0.8,
            '回撤 > -25%': r['max_drawdown_pct'] > -25,
            '胜率 > 45%': r['win_rate'] > 45,
        }
        p = sum(checks.values())
        lines.append(f"\n  {name}: {'PASS' if p >= 4 else f'FAIL ({p}/5)'}")
        for ck, ok in checks.items():
            lines.append(f"    [{'Y' if ok else 'N'}] {ck}")

    # 结论
    lines.append(f"\n{'='*95}")
    hist_reports = all_reports
    if hist_reports:
        best = max(hist_reports, key=lambda n: hist_reports[n]['report']['alpha_pct'])
        ba = hist_reports[best]['report']['alpha_pct']
        lines.append(f"最佳: {best}  |  Alpha: {ba:+.2f}%")

    lines.append("=" * 95)
    return "\n".join(lines)


def main():
    all_reports = run_validation()
    if not all_reports:
        print("\n没有结果")
        return

    report_text = generate_report(all_reports)
    print("\n\n" + report_text)

    output_dir = Path('./reports')
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M')

    with open(output_dir / f"portfolio_v3.1_{ts}.txt", 'w') as f:
        f.write(report_text)

    json_data = {n: {k: v for k, v in d['report'].items() if k != 'rebalance_log'}
                 for n, d in all_reports.items()}
    with open(output_dir / f"portfolio_v3.1_{ts}.json", 'w') as f:
        json.dump(json_data, f, indent=2, default=str)

    print(f"\n报告已保存到 reports/portfolio_v3.1_{ts}.*")


if __name__ == '__main__':
    main()
