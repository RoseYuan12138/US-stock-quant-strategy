#!/usr/bin/env python3
"""
Regime Backtester - 3段标准化回测（并行）
==========================================
分别在牛市、黑天鹅、震荡熊市3种市场环境下并行回测策略，
快速验证策略在不同regime下的表现。

Usage:
    python3 run_regime_tests.py [--strategy v7]
    python3 run_regime_tests.py --strategy v8
    python3 run_regime_tests.py --regime bull        # 只跑牛市
"""

import argparse
import json
import os
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(__file__))

STRATEGIES = {
    "v7": "strategy.sector_neutral.SectorNeutralStrategy",
    "v8": "strategy.v8.V8Strategy",
}

REGIMES = {
    "bull": {
        "start": "2017-01-01",
        "end": "2019-12-31",
        "label": "牛市+小熊",
        "desc": "2017-18强牛，2018Q4暴跌20%后V型反弹",
    },
    "crash": {
        "start": "2020-01-01",
        "end": "2020-12-31",
        "label": "黑天鹅",
        "desc": "COVID崩盘-34%，然后暴力反弹",
    },
    "bear": {
        "start": "2022-01-01",
        "end": "2023-12-31",
        "label": "震荡熊市",
        "desc": "加息周期，科技股跌，价值轮动",
    },
}


def run_single_regime(regime_name, strategy_name, config_kwargs, run_dir):
    """Run backtest for a single regime. Designed to run in a subprocess."""
    import warnings
    warnings.filterwarnings("ignore")

    from backtest.engine import Backtester

    regime = REGIMES[regime_name]

    # Create config based on strategy
    if strategy_name == "v8":
        from config import V8Config
        config = V8Config(**{k: v for k, v in config_kwargs.items()
                            if hasattr(V8Config, k)})
    else:
        from config import V7Config
        config = V7Config(**{k: v for k, v in config_kwargs.items()
                            if hasattr(V7Config, k)})

    # Load strategy
    module_path, class_name = STRATEGIES[strategy_name].rsplit(".", 1)
    module = __import__(module_path, fromlist=[class_name])
    strategy_class = getattr(module, class_name)
    strategy = strategy_class(config)

    backtester = Backtester(strategy, config)
    daily_df, report = backtester.run(regime["start"], regime["end"])

    # Save to run directory
    daily_df.to_csv(f"{run_dir}/{regime_name}_daily.csv", index=False)
    with open(f"{run_dir}/{regime_name}_report.json", "w") as f:
        json.dump(report, f, indent=2, default=str)

    return regime_name, report


def print_summary_table(results: dict):
    """Print a comparison table across all regimes."""
    print("\n" + "=" * 80)
    print("  REGIME COMPARISON")
    print("=" * 80)

    header = f"  {'Regime':<15} {'Period':<25} {'Return':>8} {'SPY':>8} {'Alpha':>8} {'t-stat':>7} {'Sharpe':>7} {'MaxDD':>8}"
    print(header)
    print("  " + "-" * 76)

    for regime_name in ["bull", "crash", "bear"]:
        if regime_name not in results:
            continue
        r = results[regime_name]
        regime = REGIMES[regime_name]
        print(
            f"  {regime['label']:<15} "
            f"{regime['start']}~{regime['end'][:4]}  "
            f"{r['total_return_pct']:>+7.1f}% "
            f"{r['spy_total_return_pct']:>+7.1f}% "
            f"{r['alpha_annual_pct']:>+7.1f}% "
            f"{r['alpha_t_stat']:>+6.2f} "
            f"{r['sharpe_ratio']:>6.3f} "
            f"{r['max_drawdown_pct']:>7.1f}%"
        )

    print("  " + "-" * 76)

    # Factor IC across all regimes
    print("\n  FACTOR IC BY REGIME")
    print("  " + "-" * 76)

    all_factors = set()
    for report in results.values():
        all_factors.update(report.get("factor_ic", {}).keys())

    if all_factors:
        regime_order = [r for r in ["bull", "crash", "bear"] if r in results]
        header = f"  {'Factor':<20}"
        for regime_name in regime_order:
            header += f" {REGIMES[regime_name]['label']:>12}"
        print(header)
        print("  " + "-" * 76)

        for factor in sorted(all_factors):
            line = f"  {factor:<20}"
            for regime_name in regime_order:
                ic_data = results[regime_name].get("factor_ic", {}).get(factor, {})
                ic = ic_data.get("mean_ic", 0)
                line += f" {ic:>+11.3f} "
            print(line)

    print("\n" + "=" * 80)


def main():
    parser = argparse.ArgumentParser(description="Regime Backtester (parallel)")
    parser.add_argument("--strategy", default="v7",
                       choices=list(STRATEGIES.keys()))
    parser.add_argument("--regime", default=None,
                       choices=list(REGIMES.keys()),
                       help="Run only one regime (default: all in parallel)")
    parser.add_argument("--slippage", type=float, default=10.0)
    parser.add_argument("--top-n", type=int, default=2)
    parser.add_argument("--rebalance-days", type=int, default=14)
    args = parser.parse_args()

    regimes_to_run = [args.regime] if args.regime else list(REGIMES.keys())
    config_kwargs = dict(
        slippage_bps=args.slippage,
        top_n_per_sector=args.top_n,
        rebalance_days=args.rebalance_days,
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = f"reports/{args.strategy}_{ts}"
    os.makedirs(run_dir, exist_ok=True)

    print(f"Starting {len(regimes_to_run)} regime(s) in parallel...")
    print(f"Output: {run_dir}/\n")
    for r in regimes_to_run:
        regime = REGIMES[r]
        print(f"  [{r.upper()}] {regime['label']}: {regime['start']} ~ {regime['end']}")
    print()

    results = {}

    with ProcessPoolExecutor(max_workers=len(regimes_to_run)) as executor:
        futures = {
            executor.submit(
                run_single_regime, regime_name, args.strategy, config_kwargs, run_dir
            ): regime_name
            for regime_name in regimes_to_run
        }

        for future in as_completed(futures):
            regime_name = futures[future]
            try:
                name, report = future.result()
                results[name] = report
                print(f"  ✓ [{name.upper()}] done — "
                      f"Return: {report['total_return_pct']:+.1f}%, "
                      f"Alpha: {report['alpha_annual_pct']:+.1f}%, "
                      f"Sharpe: {report['sharpe_ratio']:.3f}")
            except Exception as e:
                import traceback
                print(f"  ✗ [{regime_name.upper()}] FAILED: {e}")
                traceback.print_exc()

    # Print comparison table
    if len(results) > 1:
        print_summary_table(results)

    # Save combined summary
    summary = {}
    for regime_name, report in results.items():
        summary[regime_name] = {
            "regime": REGIMES[regime_name],
            "report": report,
        }

    summary_path = f"{run_dir}/summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\nResults saved to {summary_path}")


if __name__ == "__main__":
    main()
