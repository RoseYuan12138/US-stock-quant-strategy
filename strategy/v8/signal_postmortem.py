"""Signal Postmortem — track accuracy of defense/offense signals.

After each market regime transition, measures whether the signal
was correct (timely and directional) and feeds back into confidence
weights for the ExposureCoach.
"""

import numpy as np
import pandas as pd


class SignalPostmortem:
    """Track and score signal accuracy over time."""

    def __init__(self):
        self._signals = []   # List of signal events
        self._outcomes = []  # List of verified outcomes

    def record_signal(self, date: pd.Timestamp, signal_type: str,
                      signal_value: dict):
        """Record a defense or offense signal.

        Args:
            signal_type: "top_detector" | "ftd_detector" | "exposure_coach"
            signal_value: The signal output dict
        """
        self._signals.append({
            "date": date,
            "type": signal_type,
            "value": signal_value,
        })

    def evaluate(self, date: pd.Timestamp, spy_prices: pd.DataFrame,
                 lookback_days: int = 20) -> dict:
        """Evaluate recent signals against actual market outcomes.

        Returns:
            {
                "top_detector_accuracy": float (0-1),
                "ftd_detector_accuracy": float (0-1),
                "overall_accuracy": float (0-1),
                "n_evaluated": int,
            }
        """
        if not self._signals or spy_prices is None:
            return {"top_detector_accuracy": 0.5, "ftd_detector_accuracy": 0.5,
                    "overall_accuracy": 0.5, "n_evaluated": 0}

        # Only evaluate signals old enough to verify
        cutoff = date - pd.Timedelta(days=lookback_days)
        evaluable = [s for s in self._signals if s["date"] <= cutoff]

        top_scores = []
        ftd_scores = []

        spy_up_to = spy_prices[spy_prices.index <= date]
        if len(spy_up_to) < lookback_days:
            return {"top_detector_accuracy": 0.5, "ftd_detector_accuracy": 0.5,
                    "overall_accuracy": 0.5, "n_evaluated": 0}

        for sig in evaluable[-20:]:  # Last 20 evaluable signals
            sig_date = sig["date"]
            sig_type = sig["type"]
            val = sig["value"]

            # Get forward return from signal date
            spy_at_signal = spy_up_to[spy_up_to.index <= sig_date]
            spy_after = spy_up_to[spy_up_to.index > sig_date]

            if len(spy_at_signal) == 0 or len(spy_after) < 5:
                continue

            price_then = float(spy_at_signal["Close"].iloc[-1])
            # Use 20-day forward return
            fwd_idx = min(lookback_days, len(spy_after))
            price_later = float(spy_after["Close"].iloc[fwd_idx - 1])
            fwd_return = price_later / price_then - 1

            if sig_type == "top_detector":
                risk = val.get("top_risk", 50)
                # High risk signal + market went down = correct
                # High risk signal + market went up = false alarm
                if risk >= 60 and fwd_return < -0.02:
                    score = 1.0
                elif risk >= 60 and fwd_return >= 0.02:
                    score = 0.0
                elif risk < 40 and fwd_return >= 0:
                    score = 1.0
                elif risk < 40 and fwd_return < -0.03:
                    score = 0.0
                else:
                    score = 0.5  # Ambiguous
                top_scores.append(score)

            elif sig_type == "ftd_detector":
                state = val.get("state", "")
                if state == "FTD_CONFIRMED" and fwd_return > 0.02:
                    score = 1.0  # Correctly called bottom
                elif state == "FTD_CONFIRMED" and fwd_return < -0.03:
                    score = 0.0  # False FTD
                elif state == "CORRECTION" and fwd_return < 0:
                    score = 0.8  # Correctly cautious
                elif state == "CORRECTION" and fwd_return > 0.05:
                    score = 0.2  # Missed rally
                else:
                    score = 0.5
                ftd_scores.append(score)

        top_acc = np.mean(top_scores) if top_scores else 0.5
        ftd_acc = np.mean(ftd_scores) if ftd_scores else 0.5
        all_scores = top_scores + ftd_scores
        overall = np.mean(all_scores) if all_scores else 0.5

        result = {
            "top_detector_accuracy": round(top_acc, 3),
            "ftd_detector_accuracy": round(ftd_acc, 3),
            "overall_accuracy": round(overall, 3),
            "n_evaluated": len(all_scores),
        }

        self._outcomes.append((date, result))
        return result

    def get_confidence_adjustments(self) -> dict:
        """Get confidence multipliers for each signal type.

        Returns:
            {
                "top_detector_weight": float (0.5-1.5),
                "ftd_detector_weight": float (0.5-1.5),
            }
        """
        if not self._outcomes:
            return {"top_detector_weight": 1.0, "ftd_detector_weight": 1.0}

        # Use last 5 evaluations
        recent = self._outcomes[-5:]
        top_accs = [r[1]["top_detector_accuracy"] for r in recent]
        ftd_accs = [r[1]["ftd_detector_accuracy"] for r in recent]

        # Map accuracy to weight: 0.5 accuracy = weight 0.75, 1.0 = weight 1.5
        def acc_to_weight(acc):
            return np.clip(0.5 + acc, 0.5, 1.5)

        return {
            "top_detector_weight": round(acc_to_weight(np.mean(top_accs)), 3),
            "ftd_detector_weight": round(acc_to_weight(np.mean(ftd_accs)), 3),
        }
