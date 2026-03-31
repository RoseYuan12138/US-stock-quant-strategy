"""Distribution Day Counter — O'Neil institutional selling detection.

Counts days where the index drops >= 0.2% on higher volume than the previous day.
Rolling 25-day window. 4-5 = pressure, 6+ = heavy distribution.
"""

import numpy as np
import pandas as pd


class DistributionDayCounter:
    """Track distribution days on SPY and QQQ."""

    WINDOW = 25  # rolling window in trading days

    def __init__(self):
        self._cache = {}  # {symbol: [(date, is_dist_day), ...]}

    def count(self, date: pd.Timestamp, price_data: dict,
              symbols: list = None) -> dict:
        """Count distribution days for given indices up to date.

        Returns:
            {symbol: {"count": int, "dates": list, "stalling": int}}
        """
        if symbols is None:
            symbols = ["SPY"]

        results = {}
        for sym in symbols:
            if sym not in price_data:
                results[sym] = {"count": 0, "dates": [], "stalling": 0}
                continue

            df = price_data[sym]
            df_up_to = df[df.index <= date]
            if len(df_up_to) < 2:
                results[sym] = {"count": 0, "dates": [], "stalling": 0}
                continue

            # Use last WINDOW+5 days for computation
            recent = df_up_to.iloc[-(self.WINDOW + 5):]

            close = recent["Close"].values
            volume = recent["Volume"].values if "Volume" in recent.columns else None

            dist_dates = []
            stalling_count = 0

            for i in range(1, len(close)):
                pct_change = (close[i] / close[i - 1]) - 1

                vol_higher = True
                if volume is not None and i > 0:
                    vol_higher = volume[i] > volume[i - 1]

                # Distribution day: down >= 0.2% on higher volume
                if pct_change <= -0.002 and vol_higher:
                    dist_dates.append(recent.index[i])

                # Stalling day: up < 0.1% on high volume (churning)
                elif 0 <= pct_change < 0.001 and vol_higher:
                    stalling_count += 1

            # Only count within the rolling window
            cutoff = date - pd.Timedelta(days=self.WINDOW * 1.5)  # ~25 trading days
            dist_dates = [d for d in dist_dates if d >= cutoff]
            dist_dates = dist_dates[-self.WINDOW:]  # cap

            results[sym] = {
                "count": len(dist_dates),
                "dates": dist_dates,
                "stalling": stalling_count,
            }

        return results

    def get_risk_score(self, dist_result: dict) -> float:
        """Convert distribution count to 0-100 risk score.

        Higher = more dangerous.
        """
        count = dist_result.get("count", 0)
        stalling = dist_result.get("stalling", 0)

        # Effective count: stalling days count as 0.5
        effective = count + stalling * 0.5

        if effective <= 1:
            return 0.0
        elif effective <= 2:
            return 15.0
        elif effective <= 3:
            return 30.0
        elif effective <= 4:
            return 50.0
        elif effective <= 5:
            return 70.0
        elif effective <= 6:
            return 85.0
        else:
            return 100.0
