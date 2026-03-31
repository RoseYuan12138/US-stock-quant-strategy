"""Follow-Through Day Detector — O'Neil bottom confirmation signal.

State machine: NO_SIGNAL → CORRECTION → RALLY_ATTEMPT → FTD_CONFIRMED
Solves the "when to get back in after a sell-off" problem.
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
    CORRECTION_THRESHOLD = -0.07  # 7% decline triggers correction
    CORRECTION_MIN_DAYS = 3       # Minimum down days
    FTD_MIN_GAIN = 0.0125        # 1.25% gain on FTD day
    FTD_WINDOW_START = 4          # FTD can happen day 4+
    FTD_WINDOW_END = 10           # through day 10
    INVALIDATION_DAYS = 25        # Distribution days tracked post-FTD

    def __init__(self):
        self.state = self.NO_SIGNAL
        self._swing_high = None
        self._swing_low = None
        self._rally_start_date = None
        self._rally_day_count = 0
        self._ftd_date = None
        self._ftd_low = None
        self._post_ftd_dist_count = 0
        self._quality_score = 0

    def update(self, date: pd.Timestamp, price_data: dict) -> dict:
        """Update FTD state machine with new daily data.

        Returns:
            {
                "state": str,
                "quality_score": float (0-100),
                "exposure_guidance": float (0-1),
                "days_in_state": int,
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

        # Track swing high
        recent_high = float(close.iloc[-20:].max()) if len(close) >= 20 else current
        if self._swing_high is None or recent_high > self._swing_high:
            self._swing_high = recent_high

        # State machine transitions
        if self.state == self.NO_SIGNAL:
            # Check if we've entered a correction
            if self._swing_high and current < self._swing_high * (1 + self.CORRECTION_THRESHOLD):
                self.state = self.CORRECTION
                self._swing_low = current
                self._rally_day_count = 0

        elif self.state == self.CORRECTION:
            # Track the low
            if current < (self._swing_low or current):
                self._swing_low = current

            # Check for first up day (rally attempt begins)
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

            # Enter FTD window
            elif self._rally_day_count >= self.FTD_WINDOW_START:
                self.state = self.FTD_WINDOW

        elif self.state == self.FTD_WINDOW:
            self._rally_day_count += 1

            # Check for FTD qualification
            if (daily_return >= self.FTD_MIN_GAIN and
                    vol_above_avg and
                    self._rally_day_count <= self.FTD_WINDOW_END):
                self.state = self.FTD_CONFIRMED
                self._ftd_date = date
                self._ftd_low = self._swing_low
                self._post_ftd_dist_count = 0
                self._quality_score = self._compute_quality(
                    daily_return, volume_higher, spy_up_to, qqq, date)

            # Window expired without FTD
            elif self._rally_day_count > self.FTD_WINDOW_END:
                # Check if broke below swing low
                if self._swing_low and current < self._swing_low:
                    self.state = self.CORRECTION
                    self._swing_low = current
                    self._rally_day_count = 0
                else:
                    # Keep monitoring but weaker signal
                    # Late FTDs still count but lower quality
                    if daily_return >= self.FTD_MIN_GAIN and vol_above_avg:
                        self.state = self.FTD_CONFIRMED
                        self._ftd_date = date
                        self._ftd_low = self._swing_low
                        self._post_ftd_dist_count = 0
                        self._quality_score = self._compute_quality(
                            daily_return, volume_higher, spy_up_to, qqq, date) * 0.7

            # Rally failed
            if self._swing_low and current < self._swing_low:
                self.state = self.CORRECTION
                self._swing_low = current
                self._rally_day_count = 0

        elif self.state == self.FTD_CONFIRMED:
            # Monitor for invalidation
            # Count distribution days post-FTD
            if daily_return <= -0.002 and volume_higher:
                self._post_ftd_dist_count += 1

            # Invalidation: broke below FTD day low or too many dist days
            if self._ftd_low and current < self._ftd_low:
                self.state = self.FTD_INVALIDATED
                self._quality_score = 0
            elif self._post_ftd_dist_count >= 4:
                self.state = self.FTD_INVALIDATED
                self._quality_score = 0

            # Gradual quality decay
            if self._ftd_date:
                days_since = (date - self._ftd_date).days
                decay = max(0, 1 - days_since / 60)  # Decay over 60 days
                self._quality_score *= decay

        elif self.state == self.FTD_INVALIDATED:
            # Reset to look for next correction
            self.state = self.NO_SIGNAL
            self._swing_high = current
            self._swing_low = None
            self._rally_day_count = 0

        return self._result()

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
                qqq_ret = float(qqq_up_to["Close"].iloc[-1]) / float(qqq_up_to["Close"].iloc[-2]) - 1
                if qqq_ret >= 0.01:
                    score += 10  # Dual-index confirmation

        return min(score, 100)

    def _result(self) -> dict:
        """Build result dict."""
        # Exposure guidance based on state
        if self.state == self.FTD_CONFIRMED:
            if self._quality_score >= 80:
                exposure = 0.90
            elif self._quality_score >= 60:
                exposure = 0.70
            elif self._quality_score >= 40:
                exposure = 0.50
            else:
                exposure = 0.35
        elif self.state in (self.NO_SIGNAL,):
            exposure = 0.80  # Default: normal conditions
        elif self.state == self.CORRECTION:
            exposure = 0.30  # In correction: defensive
        elif self.state in (self.RALLY_ATTEMPT, self.FTD_WINDOW):
            exposure = 0.40  # Waiting for confirmation
        else:  # INVALIDATED
            exposure = 0.25

        return {
            "state": self.state,
            "quality_score": round(self._quality_score, 1),
            "exposure_guidance": exposure,
            "rally_day_count": self._rally_day_count,
        }
