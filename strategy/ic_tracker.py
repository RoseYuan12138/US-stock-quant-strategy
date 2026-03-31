"""IC (Information Coefficient) Tracker - Dynamic factor weighting."""

from typing import Dict, List

import numpy as np
import pandas as pd


class ICTracker:
    """Track factor IC over time to dynamically weight factors."""

    def __init__(self, lookback_months: int = 12):
        self.lookback_months = lookback_months
        self.ic_history: List[Dict[str, float]] = []
        self.dates: List[pd.Timestamp] = []

    def record_ic(self, date: pd.Timestamp, factors_df: pd.DataFrame,
                  forward_returns: Dict[str, float]):
        """Record IC for each factor at this rebalance date."""
        z_cols = [c for c in factors_df.columns if c.endswith("_z")]
        ic_dict = {}

        fwd = factors_df["symbol"].map(forward_returns)

        for col in z_cols:
            valid = factors_df[col].notna() & fwd.notna()
            if valid.sum() >= 10:
                ic = factors_df.loc[valid, col].corr(
                    fwd[valid], method="spearman"
                )
                ic_dict[col] = ic if pd.notna(ic) else 0.0
            else:
                ic_dict[col] = 0.0

        self.ic_history.append(ic_dict)
        self.dates.append(date)

    def get_ic_weights(self) -> Dict[str, float]:
        """Get IC-weighted factor weights from recent history."""
        if not self.ic_history:
            return {}

        recent = self.ic_history[-self.lookback_months * 2:]

        if not recent:
            return {}

        z_cols = set()
        for d in recent:
            z_cols.update(d.keys())

        avg_ic = {}
        for col in z_cols:
            ics = [d.get(col, 0.0) for d in recent]
            mean_ic = np.mean(ics)
            std_ic = np.std(ics) if len(ics) > 1 else 1.0
            ic_ir = mean_ic / std_ic if std_ic > 0.01 else mean_ic
            avg_ic[col] = max(ic_ir, 0.0)

        return avg_ic
