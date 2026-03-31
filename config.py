"""V7 Strategy Configuration."""

import os
from dataclasses import dataclass

FMP_CACHE = os.path.join(os.path.dirname(__file__), "fmp-datasource", "cache")


@dataclass
class V7Config:
    """V7 strategy configuration."""
    initial_capital: float = 100_000
    top_n_per_sector: int = 2          # pick top N stocks per sector
    max_total_holdings: int = 25       # absolute cap on positions
    min_zscore: float = -0.5           # minimum composite z-score to enter
    rebalance_days: int = 14           # bi-weekly
    slippage_bps: float = 10.0         # one-way slippage in bps
    commission: float = 0.0            # per-trade commission ($)
    trailing_stop_pct: float = 0.20    # 20% trailing stop
    spy_base_weight: float = 0.0       # no SPY ballast (fully sector-neutral)
    max_single_weight: float = 0.08    # 8% max per stock
    ic_lookback_months: int = 12       # IC estimation window
    factor_decay_days: int = 60        # signal half-life for earnings/insider
