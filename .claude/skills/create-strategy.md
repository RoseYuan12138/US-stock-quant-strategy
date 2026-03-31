---
name: create-strategy
description: >
  Create a new trading strategy for the stock-quant backtesting system.
  Trigger when user wants to add a new strategy, implement a strategy idea,
  or asks "create strategy", "new strategy", "add strategy".
---

# Create New Strategy

## Steps

1. Create `strategy/<name>.py` inheriting from `StrategyBase`
2. Register in `run_backtest.py` STRATEGIES dict
3. Run backtest to verify

## Template

```python
"""<Name> Strategy."""

from typing import Dict
import pandas as pd

from config import V7Config
from strategy.base import StrategyBase


class MyStrategy(StrategyBase):
    """One-line description."""

    name = "My Strategy Name"

    def __init__(self, config: V7Config):
        self.config = config
        # Initialize strategy-specific components

    def initialize(self, data_loader, price_data, spy_prices):
        """Called once before backtest. Store references to data."""
        self.data = data_loader
        self.price_data = price_data
        self.spy_prices = spy_prices

    def on_rebalance(self, date, universe, prev_date=None, prev_factors=None):
        """Core logic: return (target_weights_dict, factors_df_or_None).

        Args:
            date: current rebalance date
            universe: list of tradable symbols (S&P 500 members with data)
            prev_date: previous rebalance date (for IC tracking)
            prev_factors: factors DataFrame from last rebalance

        Returns:
            tuple of (target_weights: Dict[str, float], factors_df: DataFrame or None)
            - target_weights: {symbol: weight}, weights should sum to ~1.0
            - factors_df: for IC tracking (optional, can be None)
        """
        target = {}
        # ... strategy logic here ...
        return target, None

    def get_regime(self):
        """Return current regime label."""
        return "BULL"  # or use RegimeFilter

    def get_diagnostics(self):
        """Return strategy-specific info for the report."""
        return {}  # e.g. {"factor_ic": {...}, "custom_metric": ...}
```

## Register in run_backtest.py

```python
STRATEGIES = {
    "v7": "strategy.sector_neutral.SectorNeutralStrategy",
    "my_strat": "strategy.my_strategy.MyStrategy",  # ← add here
}
```

## Available Data (via data_loader)

| Method | Returns |
|--------|---------|
| `get_sp500_members(date)` | List of symbols in S&P 500 at date |
| `get_sector(symbol)` | Sector string |
| `get_fundamentals_at(date)` | DataFrame: symbol, eps, book, revenue, margins... |
| `get_earnings_at(symbol, date, lookback)` | Earnings history with EPS actual/estimated |
| `get_analyst_grades_at(date)` | Analyst consensus |
| `get_insider_trades(symbol, date, lookback)` | Insider buy/sell |
| `get_congressional_trades(symbol, date, lookback)` | Congressional trades |
| `get_macro_at(date)` | Macro indicators (treasury spread, etc.) |

## Available Components (reuse from strategy/)

- `FactorEngine(data, config)` — 14-factor z-score computation
- `ICTracker(lookback)` — rolling IC tracking + dynamic weights
- `RegimeFilter()` — macro regime detection (BULL/CAUTION/BEAR)
- `SectorNeutralPortfolio(config)` — sector-neutral portfolio construction

## Run

```bash
python3 run_backtest.py --strategy my_strat --start 2020-01-01 --end 2025-12-31
```
