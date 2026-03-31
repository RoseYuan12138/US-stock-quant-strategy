#!/usr/bin/env python3
"""
策略大规模验证脚本
对 20+ 只美股跑 3 年回测，与 SPY 基准对比
"""

import sys
import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from data.data_fetcher import DataFetcher
from strategy.strategies import SMACrossover, RSIStrategy, MACDStrategy, StrategyEnsemble
from backtest.backtester import BacktestEngine

# 测试标的: 覆盖科技、金融、医疗、消费、能源、工业等板块
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
    # ETF 基准
    'SPY', 'QQQ'
]

START_DATE = '2023-01-01'
END_DATE = '2025-12-31'
INITIAL_CASH = 10000
COMMISSION = 10  # $10/笔

STRATEGIES = [
    SMACrossover(short_window=20, long_window=50),
    RSIStrategy(period=14, oversold=30, overbought=70),
    MACDStrategy(fast=12, slow=26, signal=9),
]


def calculate_buy_and_hold(data, initial_cash=INITIAL_CASH):
    """计算买入持有的收益"""
    if data is None or len(data) < 2:
        return None
    first_price = data['Close'].iloc[0]
    last_price = data['Close'].iloc[-1]
    shares = initial_cash / first_price
    final_value = shares * last_price
    total_return = (final_value - initial_cash) / initial_cash

    # 最大回撤
    values = data['Close'] / data['Close'].iloc[0] * initial_cash
    running_max = values.cummax()
    drawdown = (values - running_max) / running_max
    max_dd = drawdown.min()

    # 夏普比率
    daily_returns = data['Close'].pct_change().dropna()
    excess = daily_returns - 0.02 / 252
    sharpe = (excess.mean() / excess.std() * np.sqrt(252)) if excess.std() != 0 else 0

    # 年化收益
    days = (data.index[-1] - data.index[0]).days
    annual_return = (1 + total_return) ** (365 / days) - 1 if days > 0 else 0

    return {
        'total_return_pct': total_return * 100,
        'annual_return_pct': annual_return * 100,
        'max_drawdown': max_dd * 100,
        'sharpe_ratio': sharpe,
        'final_value': final_value,
    }


def run_all():
    fetcher = DataFetcher(cache_dir='./data/cache')
    all_results = []

    print(f"{'='*80}")
    print(f"策略大规模验证")
    print(f"标的: {len(TICKERS)} 只  |  周期: {START_DATE} ~ {END_DATE}")
    print(f"初始资金: ${INITIAL_CASH:,}  |  佣金: ${COMMISSION}/笔")
    print(f"{'='*80}\n")

    # SPY 基准数据（用于对比）
    spy_data = fetcher.fetch_historical_data('SPY', start_date=START_DATE, end_date=END_DATE)
    spy_bnh = calculate_buy_and_hold(spy_data) if spy_data is not None else None

    for ticker in TICKERS:
        print(f"\n--- {ticker} ---")
        data = fetcher.fetch_historical_data(ticker, start_date=START_DATE, end_date=END_DATE)

        if data is None or len(data) < 100:
            print(f"  跳过: 数据不足 ({len(data) if data is not None else 0} 行)")
            continue

        # 买入持有基准
        bnh = calculate_buy_and_hold(data)

        for strategy in STRATEGIES:
            engine = BacktestEngine(initial_cash=INITIAL_CASH, commission=COMMISSION)
            try:
                _, report = engine.run_backtest(data.copy(), strategy)
            except Exception as e:
                print(f"  {strategy.name}: 回测失败 - {e}")
                continue

            # 年化收益
            days = (data.index[-1] - data.index[0]).days
            total_ret = report['total_return']
            annual_ret = (1 + total_ret) ** (365 / days) - 1 if days > 0 else 0

            # 盈亏比
            avg_win = report.get('avg_win', 0)
            avg_loss = abs(report.get('avg_loss', 1)) or 1
            profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0

            result = {
                'ticker': ticker,
                'strategy': strategy.name,
                'total_return_pct': report['total_return_pct'],
                'annual_return_pct': annual_ret * 100,
                'max_drawdown_pct': report['max_drawdown'] * 100,
                'sharpe_ratio': report['sharpe_ratio'],
                'win_rate_pct': report['win_rate'],
                'total_trades': report['total_trades'],
                'avg_win': avg_win,
                'avg_loss': report.get('avg_loss', 0),
                'profit_loss_ratio': profit_loss_ratio,
                'buy_hold_return_pct': bnh['total_return_pct'] if bnh else 0,
                'beat_buy_hold': report['total_return_pct'] > (bnh['total_return_pct'] if bnh else 0),
                'beat_spy': report['total_return_pct'] > (spy_bnh['total_return_pct'] if spy_bnh else 0),
            }
            all_results.append(result)

            beat = "✅" if result['beat_buy_hold'] else "❌"
            print(f"  {strategy.name:15s} | 收益 {report['total_return_pct']:7.1f}% | "
                  f"买入持有 {bnh['total_return_pct']:7.1f}% | "
                  f"夏普 {report['sharpe_ratio']:5.2f} | "
                  f"回撤 {report['max_drawdown']*100:6.1f}% | "
                  f"胜率 {report['win_rate']:5.1f}% | "
                  f"交易 {report['total_trades']:3d} | {beat}")

    return all_results, spy_bnh


def generate_report(all_results, spy_bnh):
    """生成验证报告"""
    df = pd.DataFrame(all_results)

    report_lines = []
    report_lines.append("=" * 80)
    report_lines.append("策略验证报告")
    report_lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    report_lines.append(f"测试周期: {START_DATE} ~ {END_DATE}")
    report_lines.append(f"测试标的: {len(TICKERS)} 只")
    report_lines.append("=" * 80)

    # SPY 基准
    if spy_bnh:
        report_lines.append(f"\n📊 基准 (SPY 买入持有):")
        report_lines.append(f"  总收益: {spy_bnh['total_return_pct']:.1f}%")
        report_lines.append(f"  年化收益: {spy_bnh['annual_return_pct']:.1f}%")
        report_lines.append(f"  最大回撤: {spy_bnh['max_drawdown']:.1f}%")
        report_lines.append(f"  夏普比率: {spy_bnh['sharpe_ratio']:.2f}")

    # 每个策略的汇总统计
    report_lines.append(f"\n{'='*80}")
    report_lines.append("各策略汇总统计（所有标的平均）")
    report_lines.append(f"{'='*80}")

    for strategy_name in df['strategy'].unique():
        sdf = df[df['strategy'] == strategy_name]
        report_lines.append(f"\n🔹 {strategy_name}")
        report_lines.append(f"  平均总收益:    {sdf['total_return_pct'].mean():.1f}%  (中位数 {sdf['total_return_pct'].median():.1f}%)")
        report_lines.append(f"  平均年化收益:  {sdf['annual_return_pct'].mean():.1f}%")
        report_lines.append(f"  平均夏普比率:  {sdf['sharpe_ratio'].mean():.2f}")
        report_lines.append(f"  平均最大回撤:  {sdf['max_drawdown_pct'].mean():.1f}%")
        report_lines.append(f"  平均胜率:      {sdf['win_rate_pct'].mean():.1f}%")
        report_lines.append(f"  平均盈亏比:    {sdf['profit_loss_ratio'].mean():.2f}")
        report_lines.append(f"  平均交易次数:  {sdf['total_trades'].mean():.0f}")
        report_lines.append(f"  跑赢买入持有:  {sdf['beat_buy_hold'].sum()}/{len(sdf)} ({sdf['beat_buy_hold'].mean()*100:.0f}%)")
        report_lines.append(f"  跑赢 SPY:      {sdf['beat_spy'].sum()}/{len(sdf)} ({sdf['beat_spy'].mean()*100:.0f}%)")

    # 验证标准检查
    report_lines.append(f"\n{'='*80}")
    report_lines.append("验证标准检查")
    report_lines.append(f"{'='*80}")

    spy_ret = spy_bnh['total_return_pct'] if spy_bnh else 0

    for strategy_name in df['strategy'].unique():
        sdf = df[df['strategy'] == strategy_name]
        avg = sdf.mean(numeric_only=True)

        checks = {
            '年化收益 > 7%': avg['annual_return_pct'] > 7,
            f'跑赢SPY ({spy_ret:.0f}%)': avg['total_return_pct'] > spy_ret,
            '夏普 > 1.0': avg['sharpe_ratio'] > 1.0,
            '最大回撤 < 25%': avg['max_drawdown_pct'] > -25,
            '胜率 > 45%': avg['win_rate_pct'] > 45,
            '盈亏比 > 1.5': avg['profit_loss_ratio'] > 1.5,
        }

        passed = sum(checks.values())
        total = len(checks)
        verdict = "✅ 通过" if passed == total else f"❌ 未通过 ({passed}/{total})"

        report_lines.append(f"\n🔹 {strategy_name}: {verdict}")
        for check_name, result in checks.items():
            icon = "✅" if result else "❌"
            report_lines.append(f"  {icon} {check_name}")

    # 最终结论
    report_lines.append(f"\n{'='*80}")
    report_lines.append("最终结论")
    report_lines.append(f"{'='*80}")

    any_passed = False
    for strategy_name in df['strategy'].unique():
        sdf = df[df['strategy'] == strategy_name]
        avg = sdf.mean(numeric_only=True)
        if (avg['annual_return_pct'] > 7 and
            avg['total_return_pct'] > spy_ret and
            avg['sharpe_ratio'] > 1.0 and
            avg['max_drawdown_pct'] > -25 and
            avg['win_rate_pct'] > 45 and
            avg['profit_loss_ratio'] > 1.5):
            any_passed = True
            report_lines.append(f"✅ {strategy_name} 通过所有验证标准，可以用于日报信号")

    if not any_passed:
        report_lines.append("❌ 没有策略通过所有验证标准")
        report_lines.append("建议: 不要用现有策略做交易信号。需要:")
        report_lines.append("  1. 优化策略参数（网格搜索）")
        report_lines.append("  2. 探索新策略（布林带、因子模型等）")
        report_lines.append("  3. 考虑基本面筛选 + 纪律性定投")
        report_lines.append("  4. 或者承认: 对于散户来说，定投 SPY/QQQ 可能是最优解")

    report_lines.append(f"\n{'='*80}")

    # 详细数据表
    report_lines.append("\n\n附录: 完整回测数据")
    report_lines.append("-" * 120)
    report_lines.append(f"{'Ticker':8s} {'Strategy':15s} {'Return%':>8s} {'Annual%':>8s} {'BnH%':>8s} {'Beat?':>6s} {'Sharpe':>7s} {'MaxDD%':>8s} {'WinR%':>7s} {'P/L':>6s} {'Trades':>7s}")
    report_lines.append("-" * 120)

    for _, row in df.sort_values(['ticker', 'strategy']).iterrows():
        beat = "✅" if row['beat_buy_hold'] else "❌"
        report_lines.append(
            f"{row['ticker']:8s} {row['strategy']:15s} "
            f"{row['total_return_pct']:7.1f}% {row['annual_return_pct']:7.1f}% "
            f"{row['buy_hold_return_pct']:7.1f}% {beat:>6s} "
            f"{row['sharpe_ratio']:7.2f} {row['max_drawdown_pct']:7.1f}% "
            f"{row['win_rate_pct']:6.1f}% {row['profit_loss_ratio']:5.2f} "
            f"{row['total_trades']:7d}"
        )

    report_text = "\n".join(report_lines)
    return report_text, df


def main():
    all_results, spy_bnh = run_all()

    if not all_results:
        print("\n❌ 没有回测结果")
        return

    report_text, df = generate_report(all_results, spy_bnh)
    print("\n\n" + report_text)

    # 保存报告
    output_dir = Path('./reports')
    output_dir.mkdir(parents=True, exist_ok=True)

    report_file = output_dir / f"strategy_validation_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report_text)
    print(f"\n报告已保存: {report_file}")

    # 保存 JSON
    json_file = output_dir / f"strategy_validation_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"JSON 已保存: {json_file}")


if __name__ == '__main__':
    main()
