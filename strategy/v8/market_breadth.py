"""Market Breadth Analyzer — compute breadth from S&P 500 individual stocks.

Since we don't have pre-computed breadth CSV data, we compute it directly
from our price data: % of S&P 500 stocks above their 200-day and 50-day MA.
"""

import numpy as np
import pandas as pd


class MarketBreadthAnalyzer:
    """Compute market breadth metrics from individual stock prices."""

    def __init__(self):
        self._history = []  # [(date, pct_above_200, pct_above_50)]

    def compute(self, date: pd.Timestamp, universe: list,
                price_data: dict) -> dict:
        """Compute breadth metrics at date.

        Returns:
            {
                "pct_above_200dma": float,  # 0-1
                "pct_above_50dma": float,   # 0-1
                "breadth_score": float,     # 0-100
                "breadth_trend": str,       # "improving", "stable", "deteriorating"
            }
        """
        above_200 = 0
        above_50 = 0
        total = 0

        for sym in universe:
            if sym not in price_data or sym == "SPY":
                continue
            df = price_data[sym]
            df_up_to = df[df.index <= date]
            if len(df_up_to) < 200:
                continue

            close = df_up_to["Close"]
            current = float(close.iloc[-1])
            sma_200 = float(close.iloc[-200:].mean())
            sma_50 = float(close.iloc[-50:].mean()) if len(df_up_to) >= 50 else current

            total += 1
            if current > sma_200:
                above_200 += 1
            if current > sma_50:
                above_50 += 1

        if total == 0:
            return {"pct_above_200dma": 0.5, "pct_above_50dma": 0.5,
                    "breadth_score": 50.0, "breadth_trend": "stable"}

        pct_200 = above_200 / total
        pct_50 = above_50 / total

        # Compute breadth score (0-100)
        # Weighted: 200DMA (60%) + 50DMA (40%)
        raw_score = (pct_200 * 0.6 + pct_50 * 0.4) * 100

        # Trend detection: compare to recent history
        self._history.append((date, pct_200, pct_50))

        trend = "stable"
        if len(self._history) >= 3:
            recent_200 = [h[1] for h in self._history[-3:]]
            if recent_200[-1] > recent_200[0] + 0.03:
                trend = "improving"
            elif recent_200[-1] < recent_200[0] - 0.03:
                trend = "deteriorating"

        # SPX divergence check: if index near highs but breadth weak
        # (checked externally when SPY data available)

        return {
            "pct_above_200dma": round(pct_200, 3),
            "pct_above_50dma": round(pct_50, 3),
            "breadth_score": round(raw_score, 1),
            "breadth_trend": trend,
        }

    def get_exposure_guidance(self, breadth_score: float) -> float:
        """Map breadth score to exposure multiplier.

        Returns:
            float: 0.25 to 1.0
        """
        if breadth_score >= 70:
            return 1.0       # Strong: 90-100% exposure
        elif breadth_score >= 55:
            return 0.85      # Healthy: 75-90%
        elif breadth_score >= 40:
            return 0.70      # Neutral: 60-75%
        elif breadth_score >= 25:
            return 0.50      # Weakening: 40-60%
        else:
            return 0.30      # Critical: 25-40%
