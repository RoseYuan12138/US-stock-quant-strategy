#!/usr/bin/env python3
"""
V3 组合策略验证脚本
改进点：
1. S&P 100 标的池（从20只扩大到~95只）
2. 2018-2025 回测（7年，覆盖2020新冠崩盘 + 2022加息熊市 + 2023-2025 AI牛市）
3. 使用历史季度财报评分，修复前视偏差
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
from strategy.portfolio_strategy import PortfolioConfig
from backtest.portfolio_backtester import PortfolioBacktester

# === S&P 100 标的池（OEX 成分股，截至 2026 年初） ===
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

# 回测日期
START_DATE = '2018-01-01'
END_DATE = '2025-12-31'
DATA_START = '2017-01-01'  # 多取1年给动量因子

# 策略配置（V2 最佳 + 新增对比）
CONFIGS = {
    'V3 Standard (Historical)': PortfolioConfig(
        top_n=10, min_combined_score=55, min_momentum_score=40,
        weight_fundamental=0.5, weight_momentum=0.3, weight_analyst=0.2,
        max_single_weight=0.12, spy_base_weight=0.20,
        trailing_stop_pct=0.25, use_regime_filter=True,
        rebalance_freq='monthly', initial_cash=100000, commission=5,
    ),
    'V3 Aggressive (Historical)': PortfolioConfig(
        top_n=15, min_combined_score=45, min_momentum_score=30,
        weight_fundamental=0.4, weight_momentum=0.4, weight_analyst=0.2,
        max_single_weight=0.10, spy_base_weight=0.10,
        trailing_stop_pct=0.30, use_regime_filter=True,
        rebalance_freq='monthly', initial_cash=100000, commission=5,
    ),
    'V3 Conservative (Historical)': PortfolioConfig(
        top_n=8, min_combined_score=60, min_momentum_score=45,
        weight_fundamental=0.6, weight_momentum=0.2, weight_analyst=0.2,
        max_single_weight=0.12, spy_base_weight=0.25,
        trailing_stop_pct=0.20, use_regime_filter=True,
        rebalance_freq='monthly', initial_cash=100000, commission=5,
    ),
    'V3 Standard (Static, for comparison)': PortfolioConfig(
        top_n=10, min_combined_score=55, min_momentum_score=40,
        weight_fundamental=0.5, weight_momentum=0.3, weight_analyst=0.2,
        max_single_weight=0.12, spy_base_weight=0.20,
        trailing_stop_pct=0.25, use_regime_filter=True,
        rebalance_freq='monthly', initial_cash=100000, commission=5,
    ),
}


def run_validation():
    price_fetcher = DataFetcher(cache_dir='./data/cache')
    fund_fetcher = FundamentalFetcher(cache_dir='./data/cache/fundamentals')
    screener = ValueScreener()
    hist_fund_fetcher = HistoricalFundamentalFetcher()

    print(f"{'='*80}")
    print(f"V3 组合策略验证")
    print(f"标的池: S&P 100 (~{len(SP100_TICKERS)} 只)")
    print(f"周期: {START_DATE} ~ {END_DATE} (7年)")
    print(f"新增: 历史季度财报评分（修复前视偏差）")
    print(f"{'='*80}")

    # 1. 获取价格数据
    print(f"\n[Step 1] 获取价格数据（这一步可能需要几分钟）...")
    price_data = {}
    failed = []
    for i, ticker in enumerate(SP100_TICKERS):
        data = price_fetcher.fetch_historical_data(
            ticker, start_date=DATA_START, end_date=END_DATE
        )
        if data is not None and len(data) > 200:
            price_data[ticker] = data
        else:
            failed.append(ticker)

        if (i + 1) % 20 == 0:
            print(f"  已处理 {i+1}/{len(SP100_TICKERS)}...")

    print(f"\n  有效标的: {len(price_data)}/{len(SP100_TICKERS)}")
    if failed:
        print(f"  失败: {', '.join(failed)}")

    # 2. 获取当前基本面数据（用于静态对比）
    print(f"\n[Step 2] 获取当前基本面数据...")
    fund_data = fund_fetcher.fetch_batch(list(price_data.keys()))
    screening_df = screener.screen_universe(fund_data)

    fundamental_scores = {}
    for _, row in screening_df.iterrows():
        fundamental_scores[row['ticker']] = {
            'total_score': row['total_score'],
            'analyst_score': row.get('analyst_score', row['total_score']),
            'signal': row['signal'],
        }

    buy_count = len(screening_df[screening_df['signal'] == 'BUY'])
    hold_count = len(screening_df[screening_df['signal'] == 'HOLD'])
    avoid_count = len(screening_df[screening_df['signal'] == 'AVOID'])
    print(f"  BUY: {buy_count} | HOLD: {hold_count} | AVOID: {avoid_count}")

    # 3. 预加载历史基本面数据
    print(f"\n[Step 3] 加载历史季度财报数据...")
    hist_loaded = 0
    for i, ticker in enumerate(price_data.keys()):
        data = hist_fund_fetcher.load_ticker(ticker)
        if data and data.get('quarterly_scores'):
            hist_loaded += 1

        if (i + 1) % 20 == 0:
            print(f"  已处理 {i+1}/{len(price_data)}...")

    print(f"  有历史财报数据: {hist_loaded}/{len(price_data)}")

    # 4. 获取基准
    print(f"\n[Step 4] 获取 SPY 基准...")
    spy_data = price_fetcher.fetch_historical_data('SPY', start_date=DATA_START, end_date=END_DATE)
    print(f"  SPY: {len(spy_data)} 行")

    # 5. 运行回测
    print(f"\n[Step 5] 运行组合回测...")
    all_reports = {}

    for config_name, config in CONFIGS.items():
        print(f"\n  --- {config_name} ---")

        use_hist = 'Historical' in config_name
        backtester = PortfolioBacktester(config)

        try:
            daily_df, report, trade_log = backtester.run(
                price_data, fundamental_scores, spy_data,
                start_date=START_DATE, end_date=END_DATE,
                use_historical_fundamentals=use_hist,
            )
        except Exception as e:
            print(f"  回测失败: {e}")
            import traceback
            traceback.print_exc()
            continue

        if report is None:
            print(f"  回测无结果")
            continue

        all_reports[config_name] = {
            'report': report,
            'daily_df': daily_df,
            'trade_log': trade_log,
        }

        beat = "BEAT" if report['beat_benchmark'] else "MISS"
        print(f"  收益: {report['total_return_pct']:+.1f}%  |  "
              f"年化: {report['annual_return_pct']:+.1f}%  |  "
              f"Alpha: {report['alpha_pct']:+.1f}%  |  "
              f"夏普: {report['sharpe_ratio']:.2f}  |  "
              f"回撤: {report['max_drawdown_pct']:.1f}%  |  "
              f"胜率: {report['win_rate']:.0f}%  |  "
              f"SPY: {beat}")

    return all_reports, screening_df


def generate_report(all_reports, screening_df):
    """生成 V3 报告"""
    lines = []
    lines.append("=" * 90)
    lines.append("V3 组合策略验证报告")
    lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"测试周期: {START_DATE} ~ {END_DATE} (7年)")
    lines.append(f"标的池: S&P 100 (~{len(SP100_TICKERS)} 只)")
    lines.append(f"关键改进: 历史季度财报评分（修复前视偏差）")
    lines.append("=" * 90)

    # 策略对比表
    lines.append(f"\n{'='*90}")
    lines.append("策略对比")
    lines.append(f"{'='*90}")
    lines.append(f"{'Config':40s} {'Return%':>8s} {'Annual%':>8s} {'Alpha%':>8s} "
                 f"{'Sharpe':>7s} {'MaxDD%':>7s} {'WinR%':>6s} {'AvgPos':>7s} {'Beat':>5s}")
    lines.append("-" * 90)

    for name, data in all_reports.items():
        r = data['report']
        beat = "Y" if r['beat_benchmark'] else "N"
        lines.append(
            f"{name:40s} {r['total_return_pct']:+7.1f}% {r['annual_return_pct']:+7.1f}% "
            f"{r['alpha_pct']:+7.1f}% {r['sharpe_ratio']:7.2f} {r['max_drawdown_pct']:6.1f}% "
            f"{r['win_rate']:5.0f}% {r['avg_positions']:6.1f} {beat:>5s}"
        )

    # SPY 基准
    if all_reports:
        r = next(iter(all_reports.values()))['report']
        lines.append(
            f"{'SPY Buy & Hold':40s} {r['benchmark_return_pct']:+7.1f}% "
            f"{r['benchmark_annual_pct']:+7.1f}% {'0.0':>7s}% "
            f"{r['benchmark_sharpe']:7.2f} {r['benchmark_max_dd_pct']:6.1f}% "
            f"{'---':>5s}% {'1.0':>7s} {'---':>5s}"
        )

    # Historical vs Static 对比
    hist_key = 'V3 Standard (Historical)'
    static_key = 'V3 Standard (Static, for comparison)'
    if hist_key in all_reports and static_key in all_reports:
        rh = all_reports[hist_key]['report']
        rs = all_reports[static_key]['report']
        lines.append(f"\n{'='*90}")
        lines.append("前视偏差影响分析 (Historical vs Static)")
        lines.append(f"{'='*90}")
        lines.append(f"  {'指标':20s} {'Historical':>12s} {'Static':>12s} {'差值':>12s}")
        lines.append(f"  {'-'*60}")
        for key, label in [('total_return_pct', '总收益'), ('annual_return_pct', '年化'),
                           ('alpha_pct', 'Alpha'), ('sharpe_ratio', '夏普'),
                           ('max_drawdown_pct', '最大回撤'), ('win_rate', '胜率')]:
            vh = rh[key]
            vs_val = rs[key]
            diff = vh - vs_val
            fmt = '.2f' if key == 'sharpe_ratio' else '.1f'
            lines.append(f"  {label:20s} {vh:>11{fmt}}% {vs_val:>11{fmt}}% {diff:>+11{fmt}}%")

    # 各配置详情
    for name, data in all_reports.items():
        r = data['report']
        lines.append(f"\n{'='*90}")
        lines.append(f"详细: {name}")
        lines.append(f"{'='*90}")
        lines.append(f"  总收益:     {r['total_return_pct']:+.2f}%")
        lines.append(f"  年化收益:   {r['annual_return_pct']:+.2f}%")
        lines.append(f"  Alpha:      {r['alpha_pct']:+.2f}%")
        lines.append(f"  夏普比率:   {r['sharpe_ratio']:.2f}")
        lines.append(f"  最大回撤:   {r['max_drawdown_pct']:.2f}%")
        lines.append(f"  胜率:       {r['win_rate']:.1f}%")
        lines.append(f"  总交易:     {r['total_trades']}")
        lines.append(f"  Trailing Stop: {r['trailing_stop_count']} 次")
        lines.append(f"  平均持仓:   {r['avg_positions']:.1f} 只")
        lines.append(f"  再平衡:     {r['total_rebalances']} 次")
        lines.append(f"  换手率:     {r['turnover']:.1f}x")
        lines.append(f"  市场环境:   {r.get('regime_days', {})}")

    # 验证标准
    lines.append(f"\n{'='*90}")
    lines.append("验证标准检查")
    lines.append(f"{'='*90}")

    for name, data in all_reports.items():
        r = data['report']
        checks = {
            '年化收益 > 10%': r['annual_return_pct'] > 10,
            'Alpha > 0': r['alpha_pct'] > 0,
            '夏普 > 0.8': r['sharpe_ratio'] > 0.8,
            '最大回撤 > -25%': r['max_drawdown_pct'] > -25,
            '胜率 > 45%': r['win_rate'] > 45,
        }
        passed = sum(checks.values())
        verdict = "PASS" if passed >= 4 else f"FAIL ({passed}/5)"
        lines.append(f"\n  {name}: {verdict}")
        for ck, ok in checks.items():
            lines.append(f"    [{'Y' if ok else 'N'}] {ck}")

    # 结论
    lines.append(f"\n{'='*90}")
    lines.append("结论")
    lines.append(f"{'='*90}")

    if all_reports:
        # 只看 Historical 的结果
        hist_reports = {k: v for k, v in all_reports.items() if 'Historical' in k}
        if hist_reports:
            best_name = max(hist_reports, key=lambda n: hist_reports[n]['report']['alpha_pct'])
            best_alpha = hist_reports[best_name]['report']['alpha_pct']
            best_sharpe = hist_reports[best_name]['report']['sharpe_ratio']
            best_dd = hist_reports[best_name]['report']['max_drawdown_pct']

            if best_alpha > 0:
                lines.append(f"\n  最佳配置: {best_name}")
                lines.append(f"  Alpha: {best_alpha:+.2f}%  |  夏普: {best_sharpe:.2f}  |  回撤: {best_dd:.1f}%")
                lines.append(f"  策略在去除前视偏差后仍然有效！可以进入实盘测试。")
            else:
                lines.append(f"\n  所有 Historical 配置均未产生正 Alpha。")
                lines.append(f"  最接近: {best_name} (Alpha: {best_alpha:+.2f}%)")

                # 看看和 Static 差多少
                if hist_key in all_reports and static_key in all_reports:
                    bias = all_reports[static_key]['report']['alpha_pct'] - \
                           all_reports[hist_key]['report']['alpha_pct']
                    lines.append(f"  前视偏差估计: ~{bias:+.1f}%（Static比Historical好这么多）")

    lines.append(f"\n{'='*90}")
    return "\n".join(lines)


def main():
    all_reports, screening_df = run_validation()

    if not all_reports:
        print("\n没有回测结果")
        return

    report_text = generate_report(all_reports, screening_df)
    print("\n\n" + report_text)

    # 保存
    output_dir = Path('./reports')
    output_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime('%Y%m%d_%H%M')
    report_file = output_dir / f"portfolio_v3_validation_{ts}.txt"
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report_text)
    print(f"\n报告已保存: {report_file}")

    json_data = {}
    for name, data in all_reports.items():
        r = data['report'].copy()
        r.pop('rebalance_log', None)
        json_data[name] = r

    json_file = output_dir / f"portfolio_v3_validation_{ts}.json"
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, indent=2, default=str)
    print(f"JSON 已保存: {json_file}")


if __name__ == '__main__':
    main()
