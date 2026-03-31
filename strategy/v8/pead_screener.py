"""PEAD Screener — Post-Earnings Announcement Drift detection.

Identifies stocks with positive earnings surprises that show
constructive price action (gap-up + consolidation), capturing
the well-documented PEAD anomaly.
"""

import numpy as np
import pandas as pd


class PEADScreener:
    """Screen for Post-Earnings Announcement Drift candidates."""

    # Parameters
    MIN_SURPRISE_PCT = 0.05    # 5% EPS surprise minimum
    MIN_GAP_PCT = 0.03         # 3% gap-up after earnings
    MONITORING_DAYS = 25       # ~5 weeks to form setup
    MIN_VOLUME_RATIO = 1.5     # Volume on gap day vs 20-day avg

    def screen(self, date: pd.Timestamp, universe: list,
               price_data: dict, earnings_data: pd.DataFrame) -> list:
        """Screen for PEAD candidates.

        Args:
            earnings_data: DataFrame with columns [symbol, date, epsActual, epsEstimated]

        Returns:
            List of dicts with PEAD candidates and scores.
        """
        if earnings_data is None or earnings_data.empty:
            return []

        candidates = []

        # Get recent earnings (last 40 trading days)
        cutoff = date - pd.Timedelta(days=60)
        recent_earnings = earnings_data[
            (earnings_data["date"] >= cutoff) &
            (earnings_data["date"] <= date) &
            (earnings_data["epsActual"].notna()) &
            (earnings_data["epsEstimated"].notna())
        ].copy()

        if recent_earnings.empty:
            return []

        for _, row in recent_earnings.iterrows():
            sym = row["symbol"]
            if sym not in universe or sym not in price_data:
                continue

            eps_actual = row["epsActual"]
            eps_estimated = row["epsEstimated"]
            earnings_date = row["date"]

            # Skip negative surprises
            if eps_estimated == 0:
                continue
            surprise_pct = (eps_actual - eps_estimated) / abs(eps_estimated)
            if surprise_pct < self.MIN_SURPRISE_PCT:
                continue

            # Analyze post-earnings price action
            df = price_data[sym]
            df_post = df[(df.index >= earnings_date) & (df.index <= date)]
            df_pre = df[df.index < earnings_date]

            if len(df_post) < 2 or len(df_pre) < 20:
                continue

            close_post = df_post["Close"].values.astype(float)
            close_pre = df_pre["Close"].values.astype(float)

            # Gap calculation
            pre_close = close_pre[-1]
            post_open = close_post[0]
            gap_pct = (post_open / pre_close) - 1

            if gap_pct < self.MIN_GAP_PCT:
                continue

            # Volume on gap day
            vol_ratio = 1.0
            if "Volume" in df_post.columns and "Volume" in df_pre.columns:
                gap_vol = float(df_post["Volume"].iloc[0])
                avg_vol = float(df_pre["Volume"].iloc[-20:].mean())
                if avg_vol > 0:
                    vol_ratio = gap_vol / avg_vol

            # Current price relative to gap
            current = close_post[-1]
            gap_high = np.max(close_post[:3])  # High in first 3 days

            # Has it held the gap? (constructive action)
            held_gap = current >= pre_close * (1 + gap_pct * 0.5)

            # Days since earnings
            days_since = (date - earnings_date).days

            # Score components
            surprise_score = min(surprise_pct / 0.20 * 100, 100)  # Cap at 20% surprise
            gap_score = min(gap_pct / 0.10 * 100, 100)  # Cap at 10% gap
            vol_score = min(vol_ratio / 3.0 * 100, 100)  # Cap at 3x volume
            hold_score = 80 if held_gap else 20

            # Freshness decay
            freshness = max(0, 1 - days_since / 40)

            composite = (
                surprise_score * 0.25 +
                gap_score * 0.20 +
                vol_score * 0.20 +
                hold_score * 0.20 +
                freshness * 100 * 0.15
            )

            candidates.append({
                "symbol": sym,
                "pead_score": round(composite, 1),
                "surprise_pct": round(surprise_pct * 100, 1),
                "gap_pct": round(gap_pct * 100, 1),
                "vol_ratio": round(vol_ratio, 1),
                "held_gap": held_gap,
                "days_since_earnings": days_since,
                "current_price": round(current, 2),
            })

        candidates.sort(key=lambda x: x["pead_score"], reverse=True)
        return candidates
