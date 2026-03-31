---
name: run-backtest
description: >
  Run a backtest for the stock-quant system. Trigger when user wants to
  backtest, test a strategy, check performance, or says "run backtest",
  "backtest", "test strategy", "跑回测".
---

# Run Backtest

## Quick Start

```bash
# Default: V7 strategy, 2015-2025
python3 run_backtest.py

# Custom date range
python3 run_backtest.py --start 2020-01-01 --end 2026-03-30

# With strategy selection
python3 run_backtest.py --strategy v7 --start 2025-01-01 --end 2026-03-30

# Custom parameters
python3 run_backtest.py --slippage 15 --top-n 3 --rebalance-days 21
```

## CLI Arguments

| Arg | Default | Description |
|-----|---------|-------------|
| `--strategy` | `v7` | Strategy name (registered in STRATEGIES dict) |
| `--start` | `2015-01-01` | Backtest start date |
| `--end` | `2025-12-31` | Backtest end date |
| `--slippage` | `10.0` | One-way slippage in bps |
| `--top-n` | `2` | Top N stocks per sector |
| `--rebalance-days` | `14` | Rebalance frequency in days |

## Output

Results saved to `reports/`:
- `reports/{strategy}_report.json` — full metrics (alpha, sharpe, IC, etc.)
- `reports/{strategy}_daily_values.csv` — daily portfolio values

## Key Metrics in Report

| Metric | Good Range | Description |
|--------|-----------|-------------|
| `alpha_annual_pct` | > 0 | Annual excess return vs SPY |
| `alpha_t_stat` | > 1.96 | Statistical significance (95%) |
| `sharpe_ratio` | > 1.0 | Risk-adjusted return |
| `max_drawdown_pct` | > -25% | Worst peak-to-trough |
| `information_ratio` | > 0.5 | Alpha per unit tracking error |
| `win_rate_pct` | > 50% | Percentage of profitable trades |

## Common Backtest Scenarios

```bash
# Recent performance check (2026 Q1)
python3 run_backtest.py --start 2026-01-01 --end 2026-03-30

# Match comparison doc period
python3 run_backtest.py --start 2025-01-01 --end 2026-03-30

# Full history
python3 run_backtest.py --start 2015-01-01 --end 2025-12-31

# Stress test: COVID crash
python3 run_backtest.py --start 2020-01-01 --end 2020-12-31

# Sensitivity: higher slippage
python3 run_backtest.py --slippage 20 --start 2020-01-01 --end 2025-12-31
```

## Interpreting Results

- **Alpha negative but t-stat > -1.96**: Not statistically significant underperformance
- **Factor IC hit rate > 60%**: Factor has predictive power
- **IC-IR > 0.5**: Factor is consistently predictive
- **Regime = BEAR with mult 0.4**: Strategy is de-risked, expect less exposure

## Data Requirements

Requires FMP parquet data in `fmp-datasource/cache/`. If missing:
```bash
cd fmp-datasource && python3 run_all.py
```
