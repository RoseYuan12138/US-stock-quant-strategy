#!/usr/bin/env python3
"""
组合策略验证脚本
验证「基本面+动量选股 → 月度再平衡 → Trailing Stop → 市场环境过滤」策略

对比：
1. 新组合策略 vs SPY 买入持有
2. 不同配置的效果（保守/标准/激进）
3. 有/无 regime filter 的差异
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
from strategy.momentum import MomentumScorer
from strategy.regime_filter import RegimeFilter
from strategy.portfolio_strategy import PortfolioConfig
from backtest.portfolio_backtester import PortfolioBacktester

# === 配置 ===
TICKERS = [
    # 科技
    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA',
    # 金融
    'JPM', 'BAC', 'GS',
    # 医疗
    'JNJ', 'UNH', 'PFE',
    # 消费
    'WMT', 'KO', 'MCD',
    # 能源
    'XOM', 'CVX',
    # 工业
    'CAT', 'BA',
]

START_DATE = '2023-01-01'
END_DATE = '2025-12-31'

# 多组参数配置
CONFIGS = {
    'Standard (Regime On)': PortfolioConfig(
        top_n=8, min_combined_score=55, min_momentum_score=40,
        weight_fundamental=0.5, weight_momentum=0.3, weight_analyst=0.2,
        max_single_weight=0.15, spy_base_weight=0.20,
        trailing_stop_pct=0.25, use_regime_filter=True,
        rebalance_freq='monthly', initial_cash=100000, commission=10,
    ),
    'Standard (Regime Off)': PortfolioConfig(
        top_n=8, min_combined_score=55, min_momentum_score=40,
        weight_fundamental=0.5, weight_momentum=0.3, weight_analyst=0.2,
        max_single_weight=0.15, spy_base_weight=0.20,
        trailing_stop_pct=0.25, use_regime_filter=False,
        rebalance_freq='monthly', initial_cash=100000, commission=10,
    ),
    'Conservative': PortfolioConfig(
        top_n=5, min_combined_score=65, min_momentum_score=50,
        weight_fundamental=0.6, weight_momentum=0.2, weight_analyst=0.2,
        max_single_weight=0.12, spy_base_weight=0.30,
        trailing_stop_pct=0.20, use_regime_filter=True,
        rebalance_freq='monthly', initial_cash=100000, commission=10,
    ),
    'Aggressive': PortfolioConfig(
        top_n=10, min_combined_score=45, min_momentum_score=30,
        weight_fundamental=0.4, weight_momentum=0.4, weight_analyst=0.2,
        max_single_weight=0.18, spy_base_weight=0.10,
        trailing_stop_pct=0.30, use_regime_filter=True,
        rebalance_freq='monthly', initial_cash=100000, commission=10,
    ),
    'Quarterly Rebalance': PortfolioConfig(
        top_n=8, min_combined_score=55, min_momentum_score=40,
        weight_fundamental=0.5, weight_momentum=0.3, weight_analyst=0.2,
        max_single_weight=0.15, spy_base_weight=0.20,
        trailing_stop_pct=0.25, use_regime_filter=True,
        rebalance_freq='quarterly', initial_cash=100000, commission=10,
    ),
}


def run_validation():
    price_fetcher = DataFetcher(cache_dir='./data/cache')
    fund_fetcher = FundamentalFetcher(cache_dir='./data/cache/fundamentals')
    screener = ValueScreener()

    print(f"{'='*80}")
    print(f"组合策略验证 (Portfolio Backtest)")
    print(f"标的池: {len(TICKERS)} 只  |  周期: {START_DATE} ~ {END_DATE}")
    print(f"{'='*80}")

    # 1. 获取所有价格数据
    print(f"\n[Step 1] 获取价格数据...")
    price_data = {}
    for ticker in TICKERS:
        data = price_fetcher.fetch_historical_data(
            ticker, start_date='2022-01-01', end_date=END_DATE  # 多取1年用于动量计算
        )
        if data is not None and len(data) > 200:
            price_data[ticker] = data
            print(f"  {ticker}: {len(data)} 行")
        else:
            print(f"  {ticker}: 跳过（数据不足）")

    print(f"\n  有效标的: {len(price_data)}/{len(TICKERS)}")

    # 2. 获取基本面数据
    print(f"\n[Step 2] 获取基本面数据并评分...")
    fund_data = fund_fetcher.fetch_batch(list(price_data.keys()))
    screening_df = screener.screen_universe(fund_data)

    # 构建基本面评分字典
    fundamental_scores = {}
    for _, row in screening_df.iterrows():
        ticker = row['ticker']
        fundamental_scores[ticker] = {
            'total_score': row['total_score'],
            'analyst_score': row.get('analyst_score', row['total_score']),
            'signal': row['signal'],
        }

    print(f"\n  基本面筛选:")
    for _, row in screening_df.iterrows():
        print(f"    {row['ticker']:6s} | {row['total_score']:5.1f} | {row['signal']}")

    # 3. 获取基准数据
    print(f"\n[Step 3] 获取 SPY 基准...")
    spy_data = price_fetcher.fetch_historical_data('SPY', start_date='2022-01-01', end_date=END_DATE)
    print(f"  SPY: {len(spy_data)} 行")

    # 4. 市场环境概览
    print(f"\n[Step 4] 市场环境分析...")
    regime_filter = RegimeFilter()
    current_regime = regime_filter.get_regime(spy_data)
    print(f"  当前状态: {current_regime['regime']}")
    print(f"  SPY vs 200SMA: {current_regime['pct_from_sma200']*100:+.1f}%")

    # 5. 跑各配置的回测
    print(f"\n[Step 5] 运行组合回测...")
    all_reports = {}

    for config_name, config in CONFIGS.items():
        print(f"\n  --- {config_name} ---")
        backtester = PortfolioBacktester(config)

        try:
            daily_df, report, trade_log = backtester.run(
                price_data, fundamental_scores, spy_data,
                start_date=START_DATE, end_date=END_DATE
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
    """生成综合报告"""
    lines = []
    lines.append("=" * 90)
    lines.append("组合策略验证报告 (Portfolio Strategy Backtest)")
    lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"测试周期: {START_DATE} ~ {END_DATE}")
    lines.append(f"标的池: {len(TICKERS)} 只")
    lines.append("=" * 90)

    # 前视偏差声明
    lines.append("\n⚠️  重要说明：")
    lines.append("  基本面评分使用的是当前时间点的数据，存在前视偏差。")
    lines.append("  动量评分使用历史价格计算，无前视偏差。")
    lines.append("  回测结果可能偏乐观，实盘效果需进一步验证。")

    # 策略对比表
    lines.append(f"\n{'='*90}")
    lines.append("策略对比")
    lines.append(f"{'='*90}")
    lines.append(f"{'Config':30s} {'Return%':>8s} {'Annual%':>8s} {'Alpha%':>8s} "
                 f"{'Sharpe':>7s} {'MaxDD%':>7s} {'WinR%':>6s} {'Trades':>7s} {'AvgPos':>7s} {'Beat':>5s}")
    lines.append("-" * 90)

    for name, data in all_reports.items():
        r = data['report']
        beat = "Y" if r['beat_benchmark'] else "N"
        lines.append(
            f"{name:30s} {r['total_return_pct']:+7.1f}% {r['annual_return_pct']:+7.1f}% "
            f"{r['alpha_pct']:+7.1f}% {r['sharpe_ratio']:7.2f} {r['max_drawdown_pct']:6.1f}% "
            f"{r['win_rate']:5.0f}% {r['total_trades']:7d} {r['avg_positions']:6.1f} {beat:>5s}"
        )

    # SPY 基准行
    if all_reports:
        first_report = next(iter(all_reports.values()))['report']
        lines.append(
            f"{'SPY Buy & Hold':30s} {first_report['benchmark_return_pct']:+7.1f}% "
            f"{first_report['benchmark_annual_pct']:+7.1f}% {'0.0':>7s}% "
            f"{first_report['benchmark_sharpe']:7.2f} {first_report['benchmark_max_dd_pct']:6.1f}% "
            f"{'N/A':>5s}% {'1':>7s} {'1.0':>7s} {'---':>5s}"
        )

    # 各配置详细分析
    for name, data in all_reports.items():
        r = data['report']
        lines.append(f"\n{'='*90}")
        lines.append(f"详细: {name}")
        lines.append(f"{'='*90}")

        lines.append(f"\n  收益指标:")
        lines.append(f"    总收益:     {r['total_return_pct']:+.2f}%")
        lines.append(f"    年化收益:   {r['annual_return_pct']:+.2f}%")
        lines.append(f"    Alpha:      {r['alpha_pct']:+.2f}%")

        lines.append(f"\n  风险指标:")
        lines.append(f"    最大回撤:   {r['max_drawdown_pct']:.2f}%")
        lines.append(f"    夏普比率:   {r['sharpe_ratio']:.2f}")
        lines.append(f"    vs 基准夏普: {r['benchmark_sharpe']:.2f}")

        lines.append(f"\n  交易统计:")
        lines.append(f"    总交易次数:     {r['total_trades']}")
        lines.append(f"    卖出交易:       {r['sell_trades']}")
        lines.append(f"    胜率:           {r['win_rate']:.1f}%")
        lines.append(f"    Trailing Stop:  {r['trailing_stop_count']} 次")
        lines.append(f"    再平衡交易:     {r['rebalance_trade_count']} 次")
        lines.append(f"    平均持仓天数:   {r['avg_hold_days']:.0f} 天")
        lines.append(f"    换手率:         {r['turnover']:.1f}x")

        lines.append(f"\n  组合统计:")
        lines.append(f"    平均持仓数:     {r['avg_positions']:.1f}")
        lines.append(f"    再平衡次数:     {r['total_rebalances']}")
        lines.append(f"    市场环境天数:   {r.get('regime_days', {})}")

        # 再平衡历史
        if r.get('rebalance_log'):
            lines.append(f"\n  再平衡历史:")
            for rb in r['rebalance_log'][:12]:  # 最多显示12次
                tickers_str = ', '.join(rb['selected'][:5])
                if len(rb['selected']) > 5:
                    tickers_str += f" +{len(rb['selected'])-5}more"
                lines.append(f"    {rb['date'].strftime('%Y-%m-%d')} | "
                             f"{rb['regime']:7s} x{rb['multiplier']:.1f} | "
                             f"${rb['total_value']:,.0f} | "
                             f"选股: {tickers_str}")

    # 验证标准
    lines.append(f"\n{'='*90}")
    lines.append("验证标准检查")
    lines.append(f"{'='*90}")

    for name, data in all_reports.items():
        r = data['report']
        checks = {
            '年化收益 > 10%': r['annual_return_pct'] > 10,
            'Alpha > 0 (跑赢 SPY)': r['alpha_pct'] > 0,
            '夏普 > 0.8': r['sharpe_ratio'] > 0.8,
            '最大回撤 > -20%': r['max_drawdown_pct'] > -20,
            '胜率 > 45%': r['win_rate'] > 45,
        }
        passed = sum(checks.values())
        verdict = "PASS" if passed >= 4 else f"FAIL ({passed}/5)"

        lines.append(f"\n  {name}: {verdict}")
        for check_name, result in checks.items():
            icon = "Y" if result else "N"
            lines.append(f"    [{icon}] {check_name}")

    # 结论
    lines.append(f"\n{'='*90}")
    lines.append("结论")
    lines.append(f"{'='*90}")

    if all_reports:
        best_name = max(all_reports, key=lambda n: all_reports[n]['report']['alpha_pct'])
        best_alpha = all_reports[best_name]['report']['alpha_pct']

        if best_alpha > 0:
            lines.append(f"\n  最佳配置: {best_name}")
            lines.append(f"  Alpha: {best_alpha:+.2f}%（年化超额收益）")
            lines.append(f"  策略有效，可以进入下一步优化。")
        else:
            lines.append(f"\n  所有配置均未产生正 Alpha。")
            lines.append(f"  最接近: {best_name} (Alpha: {best_alpha:+.2f}%)")
            lines.append(f"  建议：增加标的池、调整参数、或接受 SPY 作为核心策略。")

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
    report_file = output_dir / f"portfolio_validation_{ts}.txt"
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report_text)
    print(f"\n报告已保存: {report_file}")

    # 保存 JSON（不含 DataFrame）
    json_data = {}
    for name, data in all_reports.items():
        r = data['report'].copy()
        r.pop('rebalance_log', None)  # 太长了不存
        json_data[name] = r

    json_file = output_dir / f"portfolio_validation_{ts}.json"
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, indent=2, default=str)
    print(f"JSON 已保存: {json_file}")


if __name__ == '__main__':
    main()
