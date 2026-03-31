#!/usr/bin/env python3
"""
V5 组合策略验证
改进点（相对V4）：
1. Short Interest 负面过滤：空头比例 > 15% 的股票直接排除
2. Insider Trading 信号：高管集群买入作为选股加分
3. 保留 V4 全部改进（跨资产 Regime Filter）

对比：V5 (全部新信号) vs V4 (无 short/insider) vs V3 baseline
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
from strategy.insider_signal import InsiderSignalScorer
from strategy.portfolio_strategy import PortfolioConfig
from backtest.portfolio_backtester import PortfolioBacktester

# === 标的池：沿用 V3/V4 的 S&P 100 ===
SP100_TICKERS = [
    # 科技
    'AAPL', 'MSFT', 'GOOGL', 'GOOG', 'AMZN', 'NVDA', 'META', 'TSLA',
    'AVGO', 'ORCL', 'CRM', 'AMD', 'ADBE', 'INTC', 'CSCO', 'QCOM',
    'TXN', 'IBM', 'INTU', 'AMAT',
    # 金融
    'JPM', 'BAC', 'GS', 'MS', 'WFC', 'C', 'BLK', 'SCHW', 'AXP', 'BK',
    'USB', 'COF',
    # 医疗
    'UNH', 'JNJ', 'LLY', 'ABBV', 'MRK', 'PFE', 'TMO', 'ABT', 'DHR',
    'BMY', 'AMGN', 'GILD', 'MDT',
    # 消费
    'WMT', 'HD', 'PG', 'KO', 'PEP', 'COST', 'MCD', 'NKE', 'SBUX',
    'TGT', 'LOW',
    # 工业
    'CAT', 'BA', 'HON', 'GE', 'RTX', 'UPS', 'DE', 'LMT', 'MMM',
    # 能源
    'XOM', 'CVX', 'COP', 'SLB',
    # 通信
    'DIS', 'CMCSA', 'NFLX', 'T', 'VZ', 'TMUS',
    # 公用事业/地产
    'NEE', 'DUK', 'SO',
    # 其他
    'V', 'MA', 'PYPL', 'ACN', 'LIN', 'UNP', 'PM',
]

# 宏观数据 ticker
MACRO_TICKERS = {
    'tnx': '^TNX',
    'irx': '^IRX',
    'vix': '^VIX',
    'hyg': 'HYG',
    'lqd': 'LQD',
}

START_DATE = '2018-01-01'
END_DATE = '2025-12-31'
DATA_START = '2017-01-01'

BASE_CONFIG = dict(
    top_n=10, min_combined_score=55, min_momentum_score=40,
    weight_fundamental=0.5, weight_momentum=0.3, weight_analyst=0.2,
    max_single_weight=0.12, spy_base_weight=0.20,
    trailing_stop_pct=0.25, use_regime_filter=True,
    rebalance_freq='monthly', initial_cash=100000, commission=5,
)

CONFIGS = {
    'V5 Full (Regime+SI+Insider)': PortfolioConfig(**BASE_CONFIG),
    'V4 Regime Only (no SI/Insider)': PortfolioConfig(**BASE_CONFIG),
    'V5 Aggressive': PortfolioConfig(
        **{**BASE_CONFIG,
           'top_n': 15, 'min_combined_score': 45, 'min_momentum_score': 30,
           'weight_fundamental': 0.4, 'weight_momentum': 0.4,
           'max_single_weight': 0.10, 'spy_base_weight': 0.10,
           'trailing_stop_pct': 0.30}
    ),
    'V5 Conservative': PortfolioConfig(
        **{**BASE_CONFIG,
           'top_n': 8, 'min_combined_score': 60, 'min_momentum_score': 45,
           'weight_fundamental': 0.6, 'weight_momentum': 0.2,
           'spy_base_weight': 0.25, 'trailing_stop_pct': 0.20}
    ),
}


def fetch_macro_data(price_fetcher):
    """获取跨资产宏观数据"""
    macro_data = {}
    for key, ticker in MACRO_TICKERS.items():
        print(f"  获取 {ticker}...")
        data = price_fetcher.fetch_historical_data(
            ticker, start_date=DATA_START, end_date=END_DATE
        )
        if data is not None and len(data) > 100:
            macro_data[key] = data
            print(f"    {ticker}: {len(data)} 行")
        else:
            print(f"    {ticker}: 获取失败或数据不足")
    return macro_data


def run_validation():
    price_fetcher = DataFetcher(cache_dir='./data/cache')
    fund_fetcher = FundamentalFetcher(cache_dir='./data/cache/fundamentals')
    screener = ValueScreener()
    hist_fund = HistoricalFundamentalFetcher()
    earnings_scorer = EarningsSurpriseScorer()
    insider_scorer = InsiderSignalScorer()

    tickers = list(dict.fromkeys(SP100_TICKERS))

    print(f"{'='*80}")
    print(f"V5 组合策略验证")
    print(f"标的池: S&P 100 ~{len(tickers)} 只")
    print(f"周期: {START_DATE} ~ {END_DATE}")
    print(f"新增: Short Interest 负面过滤 + Insider Trading 加分")
    print(f"保留: 跨资产 Regime Filter (V4)")
    print(f"{'='*80}")

    # 1. 宏观数据
    print(f"\n[Step 1] 获取宏观数据...")
    macro_data = fetch_macro_data(price_fetcher)

    # 2. 价格数据
    print(f"\n[Step 2] 获取价格数据...")
    price_data = {}
    for i, ticker in enumerate(tickers):
        data = price_fetcher.fetch_historical_data(
            ticker, start_date=DATA_START, end_date=END_DATE
        )
        if data is not None and len(data) > 200:
            price_data[ticker] = data
        if (i + 1) % 20 == 0:
            print(f"  已处理 {i+1}/{len(tickers)}...")
    print(f"  有效标的: {len(price_data)}/{len(tickers)}")

    # 3. 基本面 + Short Interest
    print(f"\n[Step 3] 获取基本面数据 + Short Interest...")
    fund_data = fund_fetcher.fetch_batch(list(price_data.keys()))
    screening_df = screener.screen_universe(fund_data)

    fundamental_scores = {}
    short_interest = {}
    for _, row in screening_df.iterrows():
        tk = row['ticker']
        fundamental_scores[tk] = {
            'total_score': row['total_score'],
            'analyst_score': row.get('analyst_score', row['total_score']),
        }

    # 从原始 fund_data 中提取 short interest
    si_count = 0
    for tk, fd in fund_data.items():
        si = fd.get('short_percent_of_float')
        if si is not None:
            short_interest[tk] = si
            si_count += 1

    high_si = {k: v for k, v in short_interest.items() if v > 0.15}
    print(f"  有 Short Interest 数据: {si_count}/{len(fund_data)}")
    if high_si:
        print(f"  高空头比例 (>15%) 被排除: {', '.join(f'{k}({v:.0%})' for k, v in sorted(high_si.items(), key=lambda x: -x[1]))}")

    # 4. 历史基本面
    print(f"\n[Step 4] 加载历史财报数据...")
    hist_loaded = 0
    for i, ticker in enumerate(price_data.keys()):
        data = hist_fund.load_ticker(ticker)
        if data and data.get('quarterly_scores'):
            hist_loaded += 1
        if (i + 1) % 20 == 0:
            print(f"  已处理 {i+1}/{len(price_data)}...")
    print(f"  有历史财报: {hist_loaded}/{len(price_data)}")

    # 5. Earnings surprise
    print(f"\n[Step 5] 加载 Earnings Surprise 数据...")
    earnings_loaded = 0
    for i, ticker in enumerate(price_data.keys()):
        ed = earnings_scorer.get_earnings_data(ticker)
        if ed:
            earnings_loaded += 1
        if (i + 1) % 20 == 0:
            print(f"  已处理 {i+1}/{len(price_data)}...")
    print(f"  有 earnings 数据: {earnings_loaded}/{len(price_data)}")

    # 6. Insider Trading 数据
    print(f"\n[Step 6] 加载 Insider Trading 数据...")
    insider_loaded = 0
    for i, ticker in enumerate(price_data.keys()):
        data = insider_scorer.get_insider_data(ticker)
        if data is not None and not data.empty:
            insider_loaded += 1
        if (i + 1) % 20 == 0:
            print(f"  已处理 {i+1}/{len(price_data)}...")
    print(f"  有 insider 数据: {insider_loaded}/{len(price_data)}")

    # 7. 基准
    print(f"\n[Step 7] 获取 SPY 基准...")
    spy_data = price_fetcher.fetch_historical_data('SPY', start_date=DATA_START, end_date=END_DATE)
    print(f"  SPY: {len(spy_data)} 行")

    # 8. 回测
    print(f"\n[Step 8] 运行回测...")
    all_reports = {}

    for config_name, config in CONFIGS.items():
        print(f"\n  --- {config_name} ---")
        backtester = PortfolioBacktester(config)

        # V4 baseline: 有 macro 但没有 short_interest / insider
        is_v4_baseline = 'V4' in config_name
        current_si = None if is_v4_baseline else short_interest
        current_insider = None if is_v4_baseline else insider_scorer

        try:
            daily_df, report, trade_log = backtester.run(
                price_data, fundamental_scores, spy_data,
                start_date=START_DATE, end_date=END_DATE,
                use_historical_fundamentals=True,
                macro_data=macro_data,
                short_interest=current_si,
                insider_scorer=current_insider,
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

    return all_reports, macro_data, short_interest


def generate_report(all_reports, macro_data, short_interest):
    lines = []
    lines.append("=" * 95)
    lines.append("V5 组合策略验证报告")
    lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"周期: {START_DATE} ~ {END_DATE}")
    lines.append(f"标的池: S&P 100 ~{len(SP100_TICKERS)} 只")
    lines.append(f"新增: Short Interest 过滤 (>15%排除) + Insider Trading 加分")
    lines.append(f"保留: 跨资产 Regime Filter + Earnings Surprise")

    high_si = {k: v for k, v in short_interest.items() if v > 0.15}
    if high_si:
        lines.append(f"被排除 (高空头): {', '.join(f'{k}({v:.0%})' for k, v in sorted(high_si.items(), key=lambda x: -x[1]))}")
    lines.append("=" * 95)

    # 对比表
    lines.append(f"\n{'Config':40s} {'Return%':>9s} {'Annual%':>8s} {'Alpha%':>8s} "
                 f"{'Sharpe':>7s} {'MaxDD%':>7s} {'WinR%':>6s} {'AvgPos':>7s} {'Beat':>5s}")
    lines.append("-" * 95)

    for name, data in all_reports.items():
        r = data['report']
        beat = "Y" if r['beat_benchmark'] else "N"
        lines.append(
            f"{name:40s} {r['total_return_pct']:+8.1f}% {r['annual_return_pct']:+7.1f}% "
            f"{r['alpha_pct']:+7.1f}% {r['sharpe_ratio']:7.2f} {r['max_drawdown_pct']:6.1f}% "
            f"{r['win_rate']:5.0f}% {r['avg_positions']:6.1f} {beat:>5s}"
        )

    if all_reports:
        r = next(iter(all_reports.values()))['report']
        lines.append(
            f"{'SPY Buy & Hold':40s} {r['benchmark_return_pct']:+8.1f}% "
            f"{r['benchmark_annual_pct']:+7.1f}% {'0.0':>7s}% "
            f"{r['benchmark_sharpe']:7.2f} {r['benchmark_max_dd_pct']:6.1f}%"
        )

    # V5 vs V4 对比
    v5_key = 'V5 Full (Regime+SI+Insider)'
    v4_key = 'V4 Regime Only (no SI/Insider)'
    if v5_key in all_reports and v4_key in all_reports:
        r5 = all_reports[v5_key]['report']
        r4 = all_reports[v4_key]['report']
        lines.append(f"\n{'='*95}")
        lines.append("V5 vs V4 对比 (Short Interest + Insider Trading 的增量效果)")
        lines.append(f"{'='*95}")
        lines.append(f"  {'指标':20s} {'V5 (全部)':>14s} {'V4 (仅Regime)':>14s} {'差值':>12s}")
        lines.append(f"  {'-'*65}")
        for key, label in [('total_return_pct', '总收益'),
                           ('annual_return_pct', '年化收益'),
                           ('alpha_pct', 'Alpha'),
                           ('sharpe_ratio', '夏普'),
                           ('max_drawdown_pct', '最大回撤'),
                           ('win_rate', '胜率')]:
            v5 = r5[key]
            v4 = r4[key]
            diff = v5 - v4
            fmt = '.2f' if key == 'sharpe_ratio' else '.1f'
            unit = '' if key == 'sharpe_ratio' else '%'
            lines.append(f"  {label:20s} {v5:>13{fmt}}{unit} {v4:>13{fmt}}{unit} {diff:>+11{fmt}}{unit}")

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
    best = max(all_reports, key=lambda n: all_reports[n]['report']['alpha_pct'])
    ba = all_reports[best]['report']['alpha_pct']
    lines.append(f"最佳配置: {best}  |  Alpha: {ba:+.2f}%")
    lines.append("=" * 95)
    return "\n".join(lines)


def main():
    all_reports, macro_data, short_interest = run_validation()
    if not all_reports:
        print("\n没有结果")
        return

    report_text = generate_report(all_reports, macro_data, short_interest)
    print("\n\n" + report_text)

    output_dir = Path('./reports')
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M')

    with open(output_dir / f"portfolio_v5_{ts}.txt", 'w') as f:
        f.write(report_text)

    json_data = {n: {k: v for k, v in d['report'].items() if k != 'rebalance_log'}
                 for n, d in all_reports.items()}
    with open(output_dir / f"portfolio_v5_{ts}.json", 'w') as f:
        json.dump(json_data, f, indent=2, default=str)

    print(f"\n报告已保存到 reports/portfolio_v5_{ts}.*")


if __name__ == '__main__':
    main()
