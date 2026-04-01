"""Exposure Coach — unified position sizing ceiling.

Synthesizes defense (Market Top) + offense (FTD) signals into
a single exposure recommendation: how much of the portfolio should
be in stocks vs cash.
"""

import numpy as np


class ExposureCoach:
    """Determine maximum equity exposure from attack/defense signals."""

    def recommend(self, top_result: dict, ftd_result: dict,
                  regime_label: str = None) -> dict:
        """Compute exposure recommendation.

        Args:
            top_result: Output from MarketTopDetector.assess()
            ftd_result: Output from FTDDetector.update()
            regime_label: Optional override label

        Returns:
            {
                "max_exposure": float (0-1),
                "action": str (NEW_ENTRY_ALLOWED / REDUCE_ONLY / CASH_PRIORITY),
                "regime": str,
                "reasoning": str,
            }
        """
        # Get individual ceilings
        top_ceiling = top_result.get("exposure_ceiling", 0.80)
        ftd_exposure = ftd_result.get("exposure_guidance", 0.80)
        ftd_state = ftd_result.get("state", "NO_SIGNAL")

        # Use the MORE CONSERVATIVE of the two as base
        base = min(top_ceiling, ftd_exposure)

        # FTD state adjustments
        if ftd_state == "CORRECTION":
            base = min(base, 0.40)  # Reduce but don't panic
        elif ftd_state == "FTD_CONFIRMED":
            # FTD_CONFIRMED = market has passed the re-entry test. The top
            # detector guards against extreme risk (top_risk>=80 override below)
            # so don't also gate the FTD boost on top_ceiling here.
            ftd_quality = ftd_result.get("quality_score", 0)
            if ftd_quality >= 70:
                base = max(base, 0.80)  # Confirmed re-entry
            elif ftd_quality >= 40:
                base = max(base, 0.70)
            else:
                base = max(base, 0.60)
        elif ftd_state in ("RALLY_ATTEMPT", "FTD_WINDOW"):
            base = min(base, 0.65)  # More aggressive during rally (was 0.55)

        # Top risk override: only cut hard on extreme readings.
        # Thresholds raised to avoid over-penalizing post-crash recoveries
        # where death cross and low breadth lag the actual market recovery.
        top_risk = top_result.get("top_risk", 0)
        if top_risk >= 90:
            base = min(base, 0.25)
        elif top_risk >= 80:
            base = min(base, 0.40)

        # Determine action
        if base >= 0.55:
            action = "NEW_ENTRY_ALLOWED"
        elif base >= 0.30:
            action = "REDUCE_ONLY"
        else:
            action = "CASH_PRIORITY"

        # Regime label
        if base >= 0.80:
            regime = "BULL"
        elif base >= 0.60:
            regime = "CAUTION"
        elif base >= 0.40:
            regime = "DEFENSIVE"
        else:
            regime = "BEAR"

        # Reasoning
        reasons = []
        zone = top_result.get("risk_zone", "unknown")
        reasons.append(f"Top risk: {zone} ({top_risk:.0f})")
        reasons.append(f"FTD: {ftd_state}")
        breadth = top_result.get("breadth", {})
        if breadth:
            reasons.append(f"Breadth: {breadth.get('breadth_score', '?')}")

        return {
            "max_exposure": round(base, 2),
            "action": action,
            "regime": regime,
            "reasoning": " | ".join(reasons),
        }
