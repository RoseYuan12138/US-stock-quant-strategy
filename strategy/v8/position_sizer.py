"""Equal-Weight Position Sizer.

Distributes exposure equally across top-N candidates.
With near-zero factor IC, diversification beats concentration.
Max 20 stocks, each gets an equal share of max_exposure.
"""

import numpy as np
import pandas as pd


class ATRPositionSizer:
    """Equal-weight position sizing across top-N candidates.

    Name kept as ATRPositionSizer for backward compatibility.
    Replaced ATR-based sizing (3-8 positions) with equal-weight (15-20)
    to reduce idiosyncratic risk when factor IC is near zero.
    """

    def __init__(self, risk_pct: float = 0.01, atr_multiplier: float = 2.0,
                 max_single_pct: float = 0.08, max_sector_pct: float = 0.30,
                 target_n: int = 20):
        self.max_single_pct = max_single_pct  # Max 8% per stock
        self.max_sector_pct = max_sector_pct  # Max 30% per sector
        self.target_n = target_n              # Target number of positions

    def size_portfolio(self, candidates: list, price_data: dict,
                       date: pd.Timestamp, portfolio_value: float,
                       max_exposure: float = 1.0,
                       sector_map: dict = None) -> dict:
        """Equal-weight portfolio sizing.

        Takes top-N candidates (by score) and assigns equal weights summing
        to max_exposure, respecting sector and single-stock caps.

        Args:
            candidates: List of {symbol, score, ...} dicts, sorted by score desc
            price_data: {symbol: DataFrame} price data
            date: Current date
            portfolio_value: Total portfolio value
            max_exposure: Maximum total equity exposure (0-1) from ExposureCoach
            sector_map: {symbol: sector} mapping

        Returns:
            {symbol: target_weight} dict
        """
        if not candidates or portfolio_value <= 0:
            return {}

        # Filter to tradeable candidates (have price data)
        tradeable = [
            c for c in candidates
            if c["symbol"] in price_data
            and len(price_data[c["symbol"]][
                price_data[c["symbol"]].index <= date
            ]) >= 20
        ]

        if not tradeable:
            return {}

        # Take top-N
        pool = tradeable[:self.target_n * 2]  # Oversample to handle sector caps

        target = {}
        sector_weights: dict = {}

        # First pass: equal weight across target_n, respecting caps
        equal_w = max_exposure / min(len(pool), self.target_n)
        equal_w = min(equal_w, self.max_single_pct)

        selected = 0
        for cand in pool:
            if selected >= self.target_n:
                break

            sym = cand["symbol"]
            weight = equal_w

            # Sector cap check
            if sector_map:
                sector = sector_map.get(sym, "Unknown")
                used = sector_weights.get(sector, 0.0)
                if used + weight > self.max_sector_pct:
                    weight = max(0.0, self.max_sector_pct - used)
                    if weight < 0.01:
                        continue

            # Total exposure cap
            current_total = sum(target.values())
            if current_total + weight > max_exposure:
                weight = max(0.0, max_exposure - current_total)
                if weight < 0.01:
                    break

            target[sym] = round(weight, 4)
            selected += 1

            if sector_map:
                sector = sector_map.get(sym, "Unknown")
                sector_weights[sector] = sector_weights.get(sector, 0.0) + weight

        return target
