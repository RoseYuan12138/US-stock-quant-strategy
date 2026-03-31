"""V7 Sector-Neutral Multi-Factor Strategy."""

from typing import Dict

import pandas as pd

from config import V7Config
from strategy.base import StrategyBase
from strategy.factors import FactorEngine
from strategy.ic_tracker import ICTracker
from strategy.regime import RegimeFilter
from strategy.portfolio import SectorNeutralPortfolio


class SectorNeutralStrategy(StrategyBase):
    """V7: 14-factor sector-neutral strategy with IC-weighted scoring."""

    name = "V7 Sector-Neutral Multi-Factor"

    def __init__(self, config: V7Config):
        self.config = config
        self.factor_engine = None
        self.ic_tracker = ICTracker(config.ic_lookback_months)
        self.regime_filter = RegimeFilter()
        self.portfolio_builder = SectorNeutralPortfolio(config)
        self.data = None
        self.price_data = None
        self.spy_prices = None
        self.benchmark_sector_weights = {}

    def initialize(self, data_loader, price_data, spy_prices):
        self.data = data_loader
        self.price_data = price_data
        self.spy_prices = spy_prices
        self.factor_engine = FactorEngine(data_loader, self.config)
        self.benchmark_sector_weights = self._compute_sector_weights()

    def on_rebalance(self, date, universe, prev_date=None, prev_factors=None):
        # Record IC from previous period
        if prev_factors is not None and prev_date is not None:
            fwd_returns = self._compute_forward_returns(
                prev_factors, prev_date, date
            )
            if fwd_returns:
                self.ic_tracker.record_ic(date, prev_factors, fwd_returns)

        # Compute factors
        factors_df = self.factor_engine.compute_all_factors(
            date, universe, self.price_data
        )

        # Get IC weights
        ic_weights = self.ic_tracker.get_ic_weights() or None

        # Composite score
        factors_df = self.factor_engine.compute_composite_score(
            factors_df, ic_weights
        )

        # Regime
        macro = self.data.get_macro_at(date)
        regime, regime_mult = self.regime_filter.assess(
            date, macro, self.spy_prices
        )

        # Build target portfolio
        target = self.portfolio_builder.construct(
            factors_df, self.benchmark_sector_weights, regime_mult
        )

        return target, factors_df

    def get_regime(self):
        return self.regime_filter.current_regime

    def get_diagnostics(self):
        ic_summary = {}
        if self.ic_tracker.ic_history:
            import numpy as np
            all_ics = {}
            for ic_dict in self.ic_tracker.ic_history:
                for k, v in ic_dict.items():
                    if k not in all_ics:
                        all_ics[k] = []
                    all_ics[k].append(v)
            ic_summary = {
                k.replace("_z", ""): {
                    "mean_ic": np.mean(vs),
                    "ic_ir": (np.mean(vs) / np.std(vs)
                              if np.std(vs) > 0 else 0),
                    "hit_rate": np.mean([1 if v > 0 else 0 for v in vs])
                }
                for k, vs in all_ics.items()
            }
        return {"factor_ic": ic_summary}

    def _compute_forward_returns(self, factors_df, prev_date, current_date):
        fwd_returns = {}
        for sym in factors_df["symbol"].values:
            if sym in self.price_data:
                p = self.price_data[sym]
                prev = p[p.index <= prev_date]
                curr = p[p.index <= current_date]
                if len(prev) > 0 and len(curr) > 0:
                    p0 = float(prev["Close"].iloc[-1])
                    p1 = float(curr["Close"].iloc[-1])
                    if isinstance(p0, pd.Series):
                        p0 = p0.iloc[0]
                    if isinstance(p1, pd.Series):
                        p1 = p1.iloc[0]
                    if p0 > 0:
                        fwd_returns[sym] = p1 / p0 - 1
        return fwd_returns

    def _compute_sector_weights(self):
        sector_counts = {}
        total = 0
        for sym, sector in self.data._sector_map.items():
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
            total += 1
        if total == 0:
            return {}
        return {s: c / total for s, c in sector_counts.items()}
