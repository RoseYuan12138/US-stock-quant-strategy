"""Regime Filter - Market regime detection using macro + price data."""

from typing import Tuple

import pandas as pd


class RegimeFilter:
    """Simple regime detection using macro + price data."""

    def __init__(self):
        self.current_regime = "BULL"

    def assess(self, date: pd.Timestamp, macro: pd.Series,
               spy_prices: pd.Series) -> Tuple[str, float]:
        """Returns (regime, position_multiplier)."""
        if spy_prices is None or len(spy_prices) < 200:
            return "BULL", 1.0

        spy_up_to = spy_prices[spy_prices.index <= date]
        if len(spy_up_to) < 200:
            return "BULL", 1.0

        current_price = spy_up_to.iloc[-1]
        sma_200 = spy_up_to.iloc[-200:].mean()
        sma_50 = spy_up_to.iloc[-50:].mean() if len(spy_up_to) >= 50 else current_price

        # Yield curve
        spread = macro.get("treasury_spread_10y2y", 1.0) if not macro.empty else 1.0

        score = 0
        if current_price > sma_200:
            score += 2
        elif current_price > sma_200 * 0.95:
            score += 1

        if current_price > sma_50:
            score += 1

        if pd.notna(spread):
            if spread > 0:
                score += 1
            elif spread < -0.5:
                score -= 1

        if score >= 3:
            regime, mult = "BULL", 1.0
        elif score >= 1:
            regime, mult = "CAUTION", 0.7
        else:
            regime, mult = "BEAR", 0.4

        self.current_regime = regime
        return regime, mult
