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

        # FTD state adjustments — more gradual
        if ftd_state == "CORRECTION":
            base = min(base, 0.50)  # Reduce but don't panic
        elif ftd_state == "FTD_CONFIRMED":
            ftd_quality = ftd_result.get("quality_score", 0)
            if ftd_quality >= 70 and top_ceiling >= 0.50:
                base = max(base, 0.75)  # Override: confirmed re-entry
            elif ftd_quality >= 40:
                base = max(base, 0.55)
        elif ftd_state in ("RALLY_ATTEMPT", "FTD_WINDOW"):
            base = min(base, 0.55)  # Cautious but not shutdown

        # Top risk override: only cut hard on extreme readings
        top_risk = top_result.get("top_risk", 0)
        if top_risk >= 85:
            base = min(base, 0.25)
        elif top_risk >= 70:
            base = min(base, 0.45)

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
