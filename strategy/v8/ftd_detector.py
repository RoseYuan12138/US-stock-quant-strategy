"""Follow-Through Day Detector — O'Neil bottom confirmation signal.

State machine: NO_SIGNAL → CORRECTION → RALLY_ATTEMPT → FTD_CONFIRMED
Solves the "when to get back in after a sell-off" problem.

Key fixes vs original:
- Quality decay computed from _initial_quality (not compound per day)
- Post-FTD dist-day threshold raised from -0.2% to -0.5% (less hair-trigger)
- Post-FTD invalidation count raised from 4 to 8
- Correction threshold raised from -7% to -10%
- NO_SIGNAL exposure raised to 0.95
- When SPY makes new 20-day high in FTD_CONFIRMED, refresh quality to keep invested
"""

import numpy as np
import pandas as pd


class FTDDetector:
    """Detect Follow-Through Days for market re-entry signals."""

    # States
    NO_SIGNAL = "NO_SIGNAL"
    CORRECTION = "CORRECTION"
    RALLY_ATTEMPT = "RALLY_ATTEMPT"
    FTD_WINDOW = "FTD_WINDOW"
    FTD_CONFIRMED = "FTD_CONFIRMED"
    FTD_INVALIDATED = "FTD_INVALIDATED"

    # Parameters
    CORRECTION_THRESHOLD = -0.10  # 10% decline triggers correction
    FTD_MIN_GAIN = 0.0125         # 1.25% gain on FTD day
    FTD_WINDOW_START = 4          # FTD can happen day 4+
    FTD_WINDOW_END = 10           # through day 10
    POST_FTD_DIST_THRESHOLD = -0.005   # -0.5% to count as distribution (was -0.2%)
    POST_FTD_INVALIDATION_COUNT = 8    # 8 dist days to invalidate (was 4)
    QUALITY_DECAY_DAYS = 120      # Decay half-life in days (from initial, not compound)

    def __init__(self):
        self.state = self.NO_SIGNAL
        self._swing_high = None
        self._swing_low = None
        self._rally_start_date = None
        self._rally_day_count = 0
        self._ftd_date = None
        self._ftd_low = None
        self._post_ftd_dist_count = 0
        self._initial_quality_score = 0  # Quality at FTD confirmation (fixed)
        self._quality_score = 0          # Decayed quality (computed each step)

    def update(self, date: pd.Timestamp, price_data: dict) -> dict:
        """Update FTD state machine with new daily data.

        Returns:
            {
                "state": str,
                "quality_score": float (0-100),
                "exposure_guidance": float (0-1),
                "rally_day_count": int,
            }
        """
        spy = price_data.get("SPY")
        qqq = price_data.get("QQQ")

        if spy is None:
            return self._result()

        spy_up_to = spy[spy.index <= date]
        if len(spy_up_to) < 60:
            return self._result()

        close = spy_up_to["Close"]
        current = float(close.iloc[-1])
        prev = float(close.iloc[-2]) if len(close) >= 2 else current
        daily_return = current / prev - 1

        # Volume check
        vol_col = "Volume" if "Volume" in spy_up_to.columns else None
        volume_higher = True
        if vol_col:
            vol = spy_up_to[vol_col]
            if len(vol) >= 2:
                volume_higher = float(vol.iloc[-1]) > float(vol.iloc[-2])

        # 60-day average volume
        vol_above_avg = True
        if vol_col and len(spy_up_to) >= 60:
            vol = spy_up_to[vol_col]
            avg_vol = float(vol.iloc[-60:].mean())
            vol_above_avg = float(vol.iloc[-1]) > avg_vol

        # Track swing high (20-day high for trend strength check)
        recent_high = float(close.iloc[-20:].max()) if len(close) >= 20 else current
        if self._swing_high is None or recent_high > self._swing_high:
            self._swing_high = recent_high

        # --- State machine transitions ---

        if self.state == self.NO_SIGNAL:
            # Enter correction only when 10%+ below recent swing high
            if self._swing_high and current < self._swing_high * (1 + self.CORRECTION_THRESHOLD):
                self.state = self.CORRECTION
                self._swing_low = current
                self._rally_day_count = 0

        elif self.state == self.CORRECTION:
            # Track the low
            if current < (self._swing_low or current):
                self._swing_low = current

            # First up day starts rally attempt
            if daily_return > 0:
                self._rally_day_count += 1
                if self._rally_day_count == 1:
                    self._rally_start_date = date
                    self.state = self.RALLY_ATTEMPT
            else:
                self._rally_day_count = 0

        elif self.state == self.RALLY_ATTEMPT:
            self._rally_day_count += 1

            # Rally failed: broke below swing low
            if self._swing_low and current < self._swing_low:
                self.state = self.CORRECTION
                self._swing_low = current
                self._rally_day_count = 0
                self._rally_start_date = None
            # Enter FTD window on day 4+
            elif self._rally_day_count >= self.FTD_WINDOW_START:
                self.state = self.FTD_WINDOW

        elif self.state == self.FTD_WINDOW:
            self._rally_day_count += 1

            # Check for FTD qualification
            if (daily_return >= self.FTD_MIN_GAIN and vol_above_avg and
                    self._rally_day_count <= self.FTD_WINDOW_END):
                self._confirm_ftd(date, daily_return, volume_higher, spy_up_to, qqq)

            # Late FTD (after window) still counts at reduced quality
            elif self._rally_day_count > self.FTD_WINDOW_END:
                if self._swing_low and current < self._swing_low:
                    self.state = self.CORRECTION
                    self._swing_low = current
                    self._rally_day_count = 0
                elif daily_return >= self.FTD_MIN_GAIN and vol_above_avg:
                    self._confirm_ftd(date, daily_return, volume_higher,
                                      spy_up_to, qqq, late=True)

            # Rally failed
            if self.state == self.FTD_WINDOW and self._swing_low and current < self._swing_low:
                self.state = self.CORRECTION
                self._swing_low = current
                self._rally_day_count = 0

        elif self.state == self.FTD_CONFIRMED:
            # Compute non-compounding quality decay from initial score
            if self._ftd_date:
                days_since = (date - self._ftd_date).days
                # Linear decay from initial, minimum 40% of original
                decay = max(0.40, 1.0 - days_since / self.QUALITY_DECAY_DAYS)
                self._quality_score = self._initial_quality_score * decay

            # Count post-FTD distribution days (stricter -0.5% threshold)
            if daily_return <= self.POST_FTD_DIST_THRESHOLD and volume_higher:
                self._post_ftd_dist_count += 1

            # Refresh: if market breaks to new highs, reset the FTD clock
            if len(close) >= 60:
                high_60 = float(close.iloc[-60:].max())
                if current >= high_60 * 0.99:
                    # New 60-day high — market confirmed healthy, extend FTD
                    self._ftd_date = date
                    self._initial_quality_score = max(
                        self._initial_quality_score, 70.0)
                    self._quality_score = self._initial_quality_score
                    self._post_ftd_dist_count = 0

            # Invalidation: broke below FTD day low OR too many dist days
            if self._ftd_low and current < self._ftd_low:
                self.state = self.FTD_INVALIDATED
                self._quality_score = 0
            elif self._post_ftd_dist_count >= self.POST_FTD_INVALIDATION_COUNT:
                self.state = self.FTD_INVALIDATED
                self._quality_score = 0

        elif self.state == self.FTD_INVALIDATED:
            # Reset to look for next pattern
            self.state = self.NO_SIGNAL
            self._swing_high = current
            self._swing_low = None
            self._rally_day_count = 0
            self._post_ftd_dist_count = 0

        return self._result()

    def _confirm_ftd(self, date, ftd_gain, vol_higher, spy_df, qqq_data,
                     late=False):
        """Transition to FTD_CONFIRMED state."""
        self.state = self.FTD_CONFIRMED
        self._ftd_date = date
        self._ftd_low = self._swing_low
        self._post_ftd_dist_count = 0
        quality = self._compute_quality(ftd_gain, vol_higher, spy_df, qqq_data, date)
        if late:
            quality *= 0.70
        self._initial_quality_score = quality
        self._quality_score = quality

    def _compute_quality(self, ftd_gain: float, vol_higher: bool,
                         spy_df: pd.DataFrame, qqq_data, date) -> float:
        """Compute FTD quality score (0-100)."""
        score = 50  # Base

        # Gain strength
        if ftd_gain >= 0.02:
            score += 15
        elif ftd_gain >= 0.015:
            score += 10
        else:
            score += 5

        # Volume confirmation
        if vol_higher:
            score += 10

        # Day number (earlier = better)
        if 4 <= self._rally_day_count <= 7:
            score += 15  # Sweet spot
        elif self._rally_day_count <= 10:
            score += 5

        # QQQ confirmation
        if qqq_data is not None:
            qqq_up_to = qqq_data[qqq_data.index <= date]
            if len(qqq_up_to) >= 2:
                qqq_ret = (float(qqq_up_to["Close"].iloc[-1]) /
                           float(qqq_up_to["Close"].iloc[-2]) - 1)
                if qqq_ret >= 0.01:
                    score += 10  # Dual-index confirmation

        return min(score, 100)

    def _result(self) -> dict:
        """Build result dict."""
        if self.state == self.FTD_CONFIRMED:
            if self._quality_score >= 80:
                exposure = 0.90
            elif self._quality_score >= 60:
                exposure = 0.80
            elif self._quality_score >= 40:
                exposure = 0.70
            else:
                exposure = 0.65  # Still mostly invested even at low quality
        elif self.state == self.NO_SIGNAL:
            exposure = 0.95  # Fully invested in normal conditions
        elif self.state == self.CORRECTION:
            exposure = 0.30  # In correction: defensive
        elif self.state in (self.RALLY_ATTEMPT, self.FTD_WINDOW):
            exposure = 0.45  # Waiting for confirmation (raised from 0.40)
        else:  # INVALIDATED
            exposure = 0.35

        return {
            "state": self.state,
            "quality_score": round(self._quality_score, 1),
            "exposure_guidance": exposure,
            "rally_day_count": self._rally_day_count,
        }
