"""Sector-Neutral Portfolio Construction."""

from typing import Dict

import numpy as np
import pandas as pd

from config import V7Config


class SectorNeutralPortfolio:
    """Build a sector-neutral portfolio from factor scores."""

    def __init__(self, config: V7Config):
        self.config = config

    def construct(self, factors_df: pd.DataFrame,
                  benchmark_sector_weights: Dict[str, float],
                  regime_mult: float = 1.0) -> Dict[str, float]:
        """Construct sector-neutral portfolio.

        Returns: dict of {symbol: target_weight}
        """
        if factors_df.empty or "composite_z" not in factors_df.columns:
            return {}

        portfolio = {}
        total_weight = 0.0

        for sector, group in factors_df.groupby("sector"):
            bench_weight = benchmark_sector_weights.get(sector, 0.0)
            if bench_weight < 0.01:
                continue

            valid = group[group["composite_z"].notna()].sort_values(
                "composite_z", ascending=False
            )

            top_n = min(self.config.top_n_per_sector, len(valid))
            if top_n == 0:
                continue

            selected = valid.head(top_n)

            selected = selected[
                selected["composite_z"] >= self.config.min_zscore
            ]
            if selected.empty:
                continue

            weight_per_stock = bench_weight / len(selected) * regime_mult

            for _, row in selected.iterrows():
                sym = row["symbol"]
                w = min(weight_per_stock, self.config.max_single_weight)
                portfolio[sym] = w
                total_weight += w

        if total_weight > 1.0:
            for sym in portfolio:
                portfolio[sym] /= total_weight

        if len(portfolio) > self.config.max_total_holdings:
            sorted_syms = sorted(
                portfolio.items(), key=lambda x: x[1], reverse=True
            )
            portfolio = dict(sorted_syms[:self.config.max_total_holdings])
            total = sum(portfolio.values())
            if total > 0:
                portfolio = {s: w/total for s, w in portfolio.items()}

        return portfolio
