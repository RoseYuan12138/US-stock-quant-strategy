#!/usr/bin/env python3
"""
价值策略大规模验证脚本
1. 获取基本面数据 -> 评分筛选
2. 对高分股票做纪律性回测（止盈止损 + 持仓限制）
3. 与 SPY 买入持有对比相对收益
4. 对比旧的纯技术策略
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
from strategy.value_strategy import ValueStrategy, DisciplinedBacktester

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
INITIAL_CASH = 10000
COMMISSION = 10

# 策略参数
STRATEGY_CONFIGS = [
    # 保守型：高门槛选股、宽止损、快止盈
    {
        'name': 'Conservative Value',
        'buy_threshold': 70,
        'take_profit': 0.15,
        'stop_loss': 0.08,
        'max_hold_days': 45,
    },
    # 标准型
    {
        'name': 'Standard Value',
        'buy_threshold': 60,
        'take_profit': 0.20,
        'stop_loss': 0.10,
        'max_hold_days': 60,
    },
    # 激进型：低门槛、宽止盈
    {
        'name': 'Aggressive Value',
        'buy_threshold': 50,
        'take_profit': 0.30,
        'stop_loss': 0.12,
        'max_hold_days': 90,
    },
]


def run_validation():
    price_fetcher = DataFetcher(cache_dir='./data/cache')
    fund_fetcher = FundamentalFetcher(cache_dir='./data/cache/fundamentals')
    screener = ValueScreener()

    print(f"{'='*80}")
    print(f"价值策略大规模验证")
    print(f"标的: {len(TICKERS)} 只  |  周期: {START_DATE} ~ {END_DATE}")
    print(f"初始资金: ${INITIAL_CASH:,}  |  佣金: ${COMMISSION}/笔")
    print(f"{'='*80}")

    # 1. 获取基本面数据并评分
    print(f"\n📊 Step 1: 获取基本面数据并评分...")
    fund_data = fund_fetcher.fetch_batch(TICKERS)
    screening_df = screener.screen_universe(fund_data)

    print(f"\n基本面筛选结果:")
    print(f"{'Ticker':8s} {'Score':>6s} {'Signal':>6s} {'PE':>8s} {'Sector':20s}")
    print("-" * 60)
    for _, row in screening_df.iterrows():
        pe_str = f"{row['pe_ratio']:.1f}" if pd.notna(row.get('pe_ratio')) else "N/A"
        print(f"{row['ticker']:8s} {row['total_score']:6.1f} {row['signal']:>6s} "
              f"{pe_str:>8s} {row.get('sector', ''):20s}")

    # 2. 获取 SPY 基准
    print(f"\n📊 Step 2: 获取基准数据...")
    spy_data = price_fetcher.fetch_historical_data('SPY', start_date=START_DATE, end_date=END_DATE)

    # 3. 对每只股票跑每种策略的回测
    print(f"\n📊 Step 3: 运行回测...")
    all_results = []

    # 基本面评分映射
    score_map = {}
    for _, row in screening_df.iterrows():
        score_map[row['ticker']] = row['total_score']

    for ticker in TICKERS:
        data = price_fetcher.fetch_historical_data(ticker, start_date=START_DATE, end_date=END_DATE)
        if data is None or len(data) < 100:
            print(f"  {ticker}: 跳过 (数据不足)")
            continue

        fund_score = score_map.get(ticker, 50)  # 默认中等评分

        # 买入持有基准
        bnh_start = data['Close'].iloc[0]
        bnh_end = data['Close'].iloc[-1]
        bnh_return = (bnh_end - bnh_start) / bnh_start * 100

        print(f"\n--- {ticker} (基本面分: {fund_score:.0f}, 买入持有: {bnh_return:.1f}%) ---")

        for config in STRATEGY_CONFIGS:
            strategy = ValueStrategy(
                buy_threshold=config['buy_threshold'],
                take_profit=config['take_profit'],
                stop_loss=config['stop_loss'],
                max_hold_days=config['max_hold_days'],
            )

            backtester = DisciplinedBacktester(
                initial_cash=INITIAL_CASH,
                commission=COMMISSION,
                take_profit=config['take_profit'],
                stop_loss=config['stop_loss'],
                max_hold_days=config['max_hold_days'],
            )

            try:
                _, report = backtester.run(
                    data.copy(), strategy,
                    fundamental_score=fund_score,
                    benchmark_data=spy_data
                )
            except Exception as e:
                print(f"  {config['name']}: 回测失败 - {e}")
                continue

            result = {
                'ticker': ticker,
                'strategy': config['name'],
                'fundamental_score': fund_score,
                'total_return_pct': report['total_return_pct'],
                'annual_return_pct': report['annual_return_pct'],
                'max_drawdown_pct': report['max_drawdown_pct'],
                'sharpe_ratio': report['sharpe_ratio'],
                'win_rate': report['win_rate'],
                'total_trades': report['total_trades'],
                'avg_hold_days': report['avg_hold_days'],
                'tp_count': report['tp_count'],
                'sl_count': report['sl_count'],
                'avg_win': report['avg_win'],
                'avg_loss': report['avg_loss'],
                'buy_hold_return_pct': bnh_return,
                'beat_buy_hold': report['total_return_pct'] > bnh_return,
                'benchmark_return_pct': report.get('benchmark_return_pct', 0),
                'alpha_pct': report.get('alpha_pct', 0),
                'beat_benchmark': report.get('beat_benchmark', False),
            }
            all_results.append(result)

            beat = "✅" if result['beat_buy_hold'] else "❌"
            alpha_str = f"{result['alpha_pct']:+.1f}%" if 'alpha_pct' in result else "N/A"
            print(f"  {config['name']:20s} | 收益 {report['total_return_pct']:7.1f}% | "
                  f"BnH {bnh_return:7.1f}% | Alpha {alpha_str:>7s} | "
                  f"夏普 {report['sharpe_ratio']:5.2f} | "
                  f"回撤 {report['max_drawdown_pct']:6.1f}% | "
                  f"胜率 {report['win_rate']:5.1f}% | "
                  f"交易 {report['total_trades']:3d} | {beat}")

    return all_results, screening_df


def generate_report(all_results, screening_df):
    """生成验证报告"""
    df = pd.DataFrame(all_results)
    if df.empty:
        return "没有结果", df

    lines = []
    lines.append("=" * 80)
    lines.append("价值策略验证报告 (Approach #2: 基本面筛选 + 纪律性买入)")
    lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"测试周期: {START_DATE} ~ {END_DATE}")
    lines.append(f"测试标的: {len(TICKERS)} 只")
    lines.append("=" * 80)

    # 基本面筛选摘要
    lines.append(f"\n📊 基本面筛选结果:")
    buy_count = len(screening_df[screening_df['signal'] == 'BUY'])
    hold_count = len(screening_df[screening_df['signal'] == 'HOLD'])
    avoid_count = len(screening_df[screening_df['signal'] == 'AVOID'])
    lines.append(f"  BUY: {buy_count} 只  |  HOLD: {hold_count} 只  |  AVOID: {avoid_count} 只")
    lines.append(f"  平均评分: {screening_df['total_score'].mean():.1f}")

    # 各策略汇总
    lines.append(f"\n{'='*80}")
    lines.append("各策略汇总统计")
    lines.append(f"{'='*80}")

    for strat_name in df['strategy'].unique():
        sdf = df[df['strategy'] == strat_name]
        lines.append(f"\n🔹 {strat_name}")
        lines.append(f"  平均总收益:    {sdf['total_return_pct'].mean():7.1f}%  (中位数 {sdf['total_return_pct'].median():.1f}%)")
        lines.append(f"  平均年化收益:  {sdf['annual_return_pct'].mean():7.1f}%")
        lines.append(f"  平均 Alpha:    {sdf['alpha_pct'].mean():+7.1f}%")
        lines.append(f"  平均夏普比率:  {sdf['sharpe_ratio'].mean():7.2f}")
        lines.append(f"  平均最大回撤:  {sdf['max_drawdown_pct'].mean():7.1f}%")
        lines.append(f"  平均胜率:      {sdf['win_rate'].mean():7.1f}%")
        lines.append(f"  平均持仓天数:  {sdf['avg_hold_days'].mean():7.0f}")
        lines.append(f"  平均交易次数:  {sdf['total_trades'].mean():7.0f}")
        lines.append(f"  跑赢买入持有:  {sdf['beat_buy_hold'].sum()}/{len(sdf)} ({sdf['beat_buy_hold'].mean()*100:.0f}%)")
        lines.append(f"  跑赢 SPY:      {sdf['beat_benchmark'].sum()}/{len(sdf)} ({sdf['beat_benchmark'].mean()*100:.0f}%)")
        lines.append(f"  止盈平均:      {sdf['tp_count'].mean():.1f} 次")
        lines.append(f"  止损平均:      {sdf['sl_count'].mean():.1f} 次")

    # 按基本面评分分组的表现
    lines.append(f"\n{'='*80}")
    lines.append("基本面评分 vs 策略表现 (验证'选股比择时重要')")
    lines.append(f"{'='*80}")

    df['score_bucket'] = pd.cut(df['fundamental_score'],
                                 bins=[0, 50, 60, 70, 100],
                                 labels=['低分(<50)', '中分(50-60)', '高分(60-70)', '优秀(>70)'])

    for bucket in df['score_bucket'].unique():
        if pd.isna(bucket):
            continue
        bdf = df[df['score_bucket'] == bucket]
        lines.append(f"\n  {bucket}: {len(bdf)} 条回测")
        lines.append(f"    平均收益: {bdf['total_return_pct'].mean():.1f}%")
        lines.append(f"    平均 Alpha: {bdf['alpha_pct'].mean():+.1f}%")
        lines.append(f"    跑赢 SPY: {bdf['beat_benchmark'].mean()*100:.0f}%")

    # 验证标准
    lines.append(f"\n{'='*80}")
    lines.append("验证标准检查")
    lines.append(f"{'='*80}")

    for strat_name in df['strategy'].unique():
        sdf = df[df['strategy'] == strat_name]
        avg = sdf.mean(numeric_only=True)

        checks = {
            '年化收益 > 7%': avg['annual_return_pct'] > 7,
            'Alpha > 0 (跑赢 SPY)': avg['alpha_pct'] > 0,
            '夏普 > 0.8': avg['sharpe_ratio'] > 0.8,
            '最大回撤 > -25%': avg['max_drawdown_pct'] > -25,
            '胜率 > 45%': avg['win_rate'] > 45,
        }

        passed = sum(checks.values())
        total = len(checks)
        verdict = "✅ 通过" if passed >= 4 else f"❌ 未通过 ({passed}/{total})"

        lines.append(f"\n🔹 {strat_name}: {verdict}")
        for check_name, result in checks.items():
            icon = "✅" if result else "❌"
            lines.append(f"  {icon} {check_name}")

    # 最终结论
    lines.append(f"\n{'='*80}")
    lines.append("最终结论")
    lines.append(f"{'='*80}")

    best_strat = None
    best_alpha = -999
    for strat_name in df['strategy'].unique():
        sdf = df[df['strategy'] == strat_name]
        avg_alpha = sdf['alpha_pct'].mean()
        if avg_alpha > best_alpha:
            best_alpha = avg_alpha
            best_strat = strat_name

    if best_alpha > 0:
        lines.append(f"✅ 最优策略: {best_strat} (平均 Alpha: {best_alpha:+.1f}%)")
        lines.append(f"  该策略在回测中平均跑赢基准 {best_alpha:.1f} 个百分点")
    else:
        lines.append(f"❌ 所有策略均未跑赢基准")
        lines.append(f"  最接近的: {best_strat} (Alpha: {best_alpha:+.1f}%)")
        lines.append(f"  建议: 考虑定投 SPY/QQQ 作为核心仓位")

    lines.append(f"\n{'='*80}")

    # 详细数据表
    lines.append("\n\n附录: 完整回测数据")
    lines.append("-" * 140)
    lines.append(f"{'Ticker':8s} {'Strategy':20s} {'Score':>5s} {'Return%':>8s} {'BnH%':>8s} "
                 f"{'Alpha%':>7s} {'Beat':>5s} {'Sharpe':>7s} {'MaxDD%':>7s} "
                 f"{'WinR%':>6s} {'Trades':>7s} {'AvgDays':>8s}")
    lines.append("-" * 140)

    for _, row in df.sort_values(['ticker', 'strategy']).iterrows():
        beat = "✅" if row['beat_buy_hold'] else "❌"
        lines.append(
            f"{row['ticker']:8s} {row['strategy']:20s} "
            f"{row['fundamental_score']:5.0f} "
            f"{row['total_return_pct']:7.1f}% {row['buy_hold_return_pct']:7.1f}% "
            f"{row['alpha_pct']:+6.1f}% {beat:>5s} "
            f"{row['sharpe_ratio']:7.2f} {row['max_drawdown_pct']:6.1f}% "
            f"{row['win_rate']:5.1f}% {row['total_trades']:7d} "
            f"{row['avg_hold_days']:7.0f}"
        )

    return "\n".join(lines), df


def main():
    all_results, screening_df = run_validation()

    if not all_results:
        print("\n❌ 没有回测结果")
        return

    report_text, df = generate_report(all_results, screening_df)
    print("\n\n" + report_text)

    # 保存
    output_dir = Path('./reports')
    output_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime('%Y%m%d_%H%M')
    report_file = output_dir / f"value_strategy_validation_{ts}.txt"
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report_text)
    print(f"\n报告已保存: {report_file}")

    json_file = output_dir / f"value_strategy_validation_{ts}.json"
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"JSON 已保存: {json_file}")


if __name__ == '__main__':
    main()
