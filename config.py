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


@dataclass
class V8Config:
    """V8 strategy configuration — Druckenmiller attack/defense architecture."""
    initial_capital: float = 100_000
    rebalance_days: int = 14           # bi-weekly
    slippage_bps: float = 10.0         # one-way slippage in bps
    commission: float = 0.0            # per-trade commission ($)
    trailing_stop_pct: float = 0.15    # 15% trailing stop (tighter than V7)

    # ATR position sizing
    risk_per_trade: float = 0.01       # 1% risk per trade
    atr_multiplier: float = 2.0        # stop = 2x ATR
    max_single_weight: float = 0.10    # 10% max per stock
    max_sector_weight: float = 0.30    # 30% max per sector

    # Factor engine (reuse V7 params)
    ic_lookback_months: int = 12
    factor_decay_days: int = 60
    top_n_per_sector: int = 3          # used by factor engine
    max_total_holdings: int = 30       # upper bound on positions
    min_zscore: float = -0.5
