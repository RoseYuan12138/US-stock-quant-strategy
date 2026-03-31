#!/usr/bin/env python3
"""
Multi-Strategy Backtester
=========================
Usage:
    python3 run_backtest.py [--strategy v7] [--start 2015-01-01] [--end 2025-12-31]

Available strategies:
    v7  - V7 Sector-Neutral Multi-Factor (default)
"""

import argparse
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(__file__))

from config import V7Config
from backtest.engine import Backtester


# Strategy registry - add new strategies here
STRATEGIES = {
    "v7": "strategy.sector_neutral.SectorNeutralStrategy",
}


def load_strategy(name: str, config):
    """Dynamically load and instantiate a strategy by name."""
    if name not in STRATEGIES:
        print(f"Unknown strategy: {name}")
        print(f"Available: {', '.join(STRATEGIES.keys())}")
        sys.exit(1)

    module_path, class_name = STRATEGIES[name].rsplit(".", 1)
    module = __import__(module_path, fromlist=[class_name])
    strategy_class = getattr(module, class_name)
    return strategy_class(config)


def print_report(report: dict):
    """Pretty-print backtest report."""
    print("\n" + "=" * 70)
    print(f"  {report['strategy']}")
    print(f"  {report['period']}")
    print(f"  {report['n_years']} years, {report['n_trading_days']} trading days")
    print("=" * 70)

    print(f"\n{'PERFORMANCE':=^50}")
    print(f"  Strategy Return:  {report['total_return_pct']:+.2f}% "
          f"({report['annual_return_pct']:+.2f}% ann.)")
    print(f"  SPY Return:       {report['spy_total_return_pct']:+.2f}% "
          f"({report['spy_annual_return_pct']:+.2f}% ann.)")
    print(f"  Max Drawdown:     {report['max_drawdown_pct']:.2f}%")
    print(f"  Sharpe Ratio:     {report['sharpe_ratio']:.3f} "
          f"(SPY: {report['spy_sharpe']:.3f})")
    print(f"  Volatility:       {report['volatility_pct']:.2f}%")

    print(f"\n{'ALPHA ANALYSIS':=^50}")
    sig = "YES" if report['alpha_significant'] else "NO"
    print(f"  Alpha (annual):   {report['alpha_annual_pct']:+.2f}%")
    print(f"  Alpha t-stat:     {report['alpha_t_stat']:+.3f}")
    print(f"  Significant:      {sig}")
    print(f"  Tracking Error:   {report['tracking_error_pct']:.2f}%")
    print(f"  Information Ratio:{report['information_ratio']:+.3f}")

    print(f"\n{'TRADING':=^50}")
    print(f"  Total Trades:     {report['total_trades']}")
    print(f"  Win Rate:         {report['win_rate_pct']:.1f}%")
    print(f"  Avg P&L/Trade:    {report['avg_pnl_pct']:+.2f}%")
    print(f"  Trailing Stops:   {report['trailing_stops']}")
    print(f"  Rebalances:       {report['n_rebalances']}")

    print(f"\n{'SECTOR ALLOCATION (avg %)':=^50}")
    sectors = report.get("avg_sector_allocation", {})
    for s in sorted(sectors, key=sectors.get, reverse=True):
        print(f"  {s:25s} {sectors[s]:5.1f}%")

    # Factor IC (only if strategy provides it)
    ics = report.get("factor_ic", {})
    if ics:
        print(f"\n{'FACTOR IC (Information Coefficient)':=^50}")
        for f in sorted(ics, key=lambda x: abs(ics[x].get("mean_ic", 0)),
                        reverse=True):
            ic = ics[f]
            print(f"  {f:25s} IC={ic['mean_ic']:+.3f}  "
                  f"IC-IR={ic['ic_ir']:+.3f}  "
                  f"Hit={ic['hit_rate']:.0%}")

    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Multi-Strategy Backtester"
    )
    parser.add_argument("--strategy", default="v7",
                       choices=list(STRATEGIES.keys()),
                       help="Strategy to backtest (default: v7)")
    parser.add_argument("--start", default="2015-01-01",
                       help="Backtest start date")
    parser.add_argument("--end", default="2025-12-31",
                       help="Backtest end date")
    parser.add_argument("--slippage", type=float, default=10.0,
                       help="One-way slippage in bps")
    parser.add_argument("--top-n", type=int, default=2,
                       help="Top N stocks per sector")
    parser.add_argument("--rebalance-days", type=int, default=14,
                       help="Rebalance frequency in days")
    args = parser.parse_args()

    config = V7Config(
        slippage_bps=args.slippage,
        top_n_per_sector=args.top_n,
        rebalance_days=args.rebalance_days,
    )

    strategy = load_strategy(args.strategy, config)
    backtester = Backtester(strategy, config)
    daily_df, report = backtester.run(args.start, args.end)

    print_report(report)

    # Save results with timestamp to avoid overwriting
    os.makedirs("reports", exist_ok=True)
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = f"{args.strategy}_{ts}"

    daily_df.to_csv(f"reports/{prefix}_daily_values.csv", index=False)

    with open(f"reports/{prefix}_report.json", "w") as f:
        json.dump(report, f, indent=2, default=str)

    # Also save a "latest" symlink/copy for convenience
    import shutil
    latest_csv = f"reports/{args.strategy}_latest_daily_values.csv"
    latest_json = f"reports/{args.strategy}_latest_report.json"
    shutil.copy2(f"reports/{prefix}_daily_values.csv", latest_csv)
    shutil.copy2(f"reports/{prefix}_report.json", latest_json)

    print(f"\nResults saved to reports/{prefix}_report.json")
    print(f"  (also copied to reports/{args.strategy}_latest_report.json)")


if __name__ == "__main__":
    main()
