#!/usr/bin/env python3
"""
每日信号生成 — 基于 V5 组合策略
使用当前架构：基本面 + 动量 + Regime + Earnings + Insider
输出：当日选股建议 + 市场环境判断
"""

import sys
import json
import argparse
import logging
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from data.data_fetcher import DataFetcher
from data.fundamental_fetcher import FundamentalFetcher, ValueScreener
from strategy.momentum import MomentumScorer
from strategy.regime_filter import RegimeFilter
from strategy.portfolio_strategy import PortfolioConfig, PortfolioStrategy
from strategy.earnings_surprise import EarningsSurpriseScorer
from strategy.insider_signal import InsiderSignalScorer

logging.basicConfig(level=logging.WARNING, format='%(message)s')
logger = logging.getLogger(__name__)

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


def main():
    parser = argparse.ArgumentParser(description='每日选股信号生成')
    parser.add_argument('--tickers', nargs='+', help='自定义股票列表')
    parser.add_argument('--output', type=str, default='./reports', help='输出目录')
    parser.add_argument('--config', type=str, choices=['standard', 'aggressive', 'conservative'],
                        default='standard', help='策略配置档位')
    args = parser.parse_args()

    tickers = args.tickers or SP100_TICKERS
    tickers = list(dict.fromkeys(tickers))

    # 配置档位
    if args.config == 'aggressive':
        config = PortfolioConfig(
            top_n=15, min_combined_score=45, min_momentum_score=30,
            weight_fundamental=0.4, weight_momentum=0.4, weight_analyst=0.2,
            max_single_weight=0.10, spy_base_weight=0.10,
            trailing_stop_pct=0.30, use_regime_filter=True,
        )
    elif args.config == 'conservative':
        config = PortfolioConfig(
            top_n=8, min_combined_score=60, min_momentum_score=45,
            weight_fundamental=0.6, weight_momentum=0.2, weight_analyst=0.2,
            max_single_weight=0.12, spy_base_weight=0.25,
            trailing_stop_pct=0.20, use_regime_filter=True,
        )
    else:
        config = PortfolioConfig(
            top_n=10, min_combined_score=55, min_momentum_score=40,
            weight_fundamental=0.5, weight_momentum=0.3, weight_analyst=0.2,
            max_single_weight=0.12, spy_base_weight=0.20,
            trailing_stop_pct=0.25, use_regime_filter=True,
        )

    strategy = PortfolioStrategy(config)
    momentum_scorer = MomentumScorer()
    regime_filter = RegimeFilter()
    earnings_scorer = EarningsSurpriseScorer()
    insider_scorer = InsiderSignalScorer()
    price_fetcher = DataFetcher(cache_dir='./data/cache')
    fund_fetcher = FundamentalFetcher(cache_dir='./data/cache/fundamentals')
    screener = ValueScreener()

    now = datetime.now()
    print(f"{'='*70}")
    print(f"  每日选股信号 — {now.strftime('%Y-%m-%d %H:%M')}")
    print(f"  配置: {args.config.upper()} | 标的池: {len(tickers)} 只")
    print(f"{'='*70}")

    # 1. 市场环境
    print(f"\n[1] 市场环境...")
    spy_data = price_fetcher.fetch_historical_data('SPY')
    macro_data = {}
    for key, ticker in MACRO_TICKERS.items():
        data = price_fetcher.fetch_historical_data(ticker)
        if data is not None and len(data) > 50:
            macro_data[key] = data

    regime = regime_filter.get_regime(spy_data, macro_data=macro_data)
    regime_name = regime.get('regime', 'UNKNOWN')
    composite = regime.get('composite_score', 0)
    multiplier = regime.get('position_multiplier', 1.0)

    regime_emoji = {'BULL': 'BULL', 'CAUTION': 'CAUTION', 'BEAR': 'BEAR', 'RECOVERY': 'RECOVERY'}
    print(f"  市场环境: {regime_emoji.get(regime_name, regime_name)} (composite={composite:.0f}, 仓位={multiplier:.0%})")

    # 2. 价格 + 动量
    print(f"\n[2] 价格和动量...")
    price_data = {}
    momentum_scores = {}
    for ticker in tickers:
        data = price_fetcher.fetch_historical_data(ticker)
        if data is not None and len(data) > 50:
            price_data[ticker] = data
            mom = momentum_scorer.calculate_momentum(data)
            if mom is not None:
                momentum_scores[ticker] = mom
    print(f"  有效: {len(price_data)}/{len(tickers)}")

    # 3. 基本面
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

    # 4. Earnings Surprise 调整
    print(f"\n[4] Earnings Surprise...")
    for ticker in fundamental_scores:
        earnings_scorer.get_earnings_data(ticker)
        es = earnings_scorer.score_at_date(ticker, datetime.now())
        if es.get('data_available'):
            orig = fundamental_scores[ticker]['total_score']
            adjusted = orig * 0.8 + es['earnings_score'] * 0.2
            fundamental_scores[ticker]['total_score'] = adjusted

    # 5. Insider Trading
    print(f"\n[5] Insider Trading...")
    insider_scores = {}
    for ticker in fundamental_scores:
        insider_scorer.get_insider_data(ticker)
    insider_scores = insider_scorer.score_universe(
        list(fundamental_scores.keys()), datetime.now()
    )

    # 6. 选股
    print(f"\n[6] 选股...")
    selected = strategy.select_stocks(
        fundamental_scores, momentum_scores,
        short_interest=short_interest,
        insider_scores=insider_scores,
    )

    # 输出报告
    print(f"\n{'='*70}")
    print(f"  选股结果 — {args.config.upper()} 配置")
    print(f"  市场: {regime_name} | 建议仓位: {multiplier:.0%}")
    print(f"{'='*70}")

    if not selected:
        print(f"\n  无符合条件的股票。")
    else:
        print(f"\n  {'Rank':>4s} {'Ticker':6s} {'综合分':>6s} {'基本面':>6s} {'动量':>6s} "
              f"{'分析师':>6s} {'Insider':>7s} {'权重':>6s} {'200SMA':>6s}")
        print(f"  {'-'*60}")
        for i, s in enumerate(selected):
            sma = 'Y' if s.get('above_200sma') else 'N'
            print(f"  {i+1:4d} {s['ticker']:6s} {s['combined_score']:6.1f} "
                  f"{s['fundamental_score']:6.1f} {s['momentum_score']:6.1f} "
                  f"{s['analyst_score']:6.1f} {s.get('insider_bonus', 0):+6.1f} "
                  f"{s['weight']:6.1%} {sma:>6s}")

    # 仓位建议
    print(f"\n  --- 仓位建议 ---")
    print(f"  SPY 底仓: {config.spy_base_weight * multiplier:.0%}")
    print(f"  个股总仓位: {(1 - config.spy_base_weight) * multiplier:.0%}")
    print(f"  现金: {1 - multiplier:.0%}")

    # 保存 JSON
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = now.strftime('%Y%m%d_%H%M')

    signal_data = {
        'date': now.isoformat(),
        'config': args.config,
        'regime': {
            'name': regime_name,
            'composite_score': composite,
            'position_multiplier': multiplier,
        },
        'selected': selected,
        'total_candidates': len(fundamental_scores),
        'passed_momentum': len(momentum_scores),
    }

    json_file = output_dir / f"daily_signal_{ts}.json"
    with open(json_file, 'w') as f:
        json.dump(signal_data, f, indent=2, default=str)
    print(f"\n  JSON: {json_file}")


if __name__ == '__main__':
    main()
