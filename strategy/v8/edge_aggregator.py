"""Edge Signal Aggregator — combine multi-source edge signals.

Aggregates signal strength across VCP, PEAD, factor model, and regime
to produce a unified "edge score" per stock. Tracks which signal sources
are contributing alpha and dynamically adjusts weights.
"""

import numpy as np
import pandas as pd


class EdgeAggregator:
    """Aggregate and track edge signals across multiple sources."""

    def __init__(self):
        # Track hit rates per signal source
        self._entry_log = []   # [(date, symbol, signals_at_entry)]
        self._exit_log = []    # [(date, symbol, pnl, signals_at_entry)]

        # Dynamic weights (start equal)
        self._source_weights = {
            "factor": 0.40,
            "vcp": 0.35,
            "pead": 0.25,
        }

    def record_entry(self, date: pd.Timestamp, symbol: str,
                     signals: dict):
        """Record which signals were active at entry.

        Args:
            signals: {"factor": score, "vcp": score, "pead": score}
        """
        self._entry_log.append({
            "date": date,
            "symbol": symbol,
            "signals": signals.copy(),
        })

    def record_exit(self, date: pd.Timestamp, symbol: str,
                    pnl_pct: float):
        """Record exit with P&L and link back to entry signals."""
        # Find matching entry
        for entry in reversed(self._entry_log):
            if entry["symbol"] == symbol:
                self._exit_log.append({
                    "date": date,
                    "symbol": symbol,
                    "pnl_pct": pnl_pct,
                    "signals_at_entry": entry["signals"],
                })
                break

    def get_signal_attribution(self, min_trades: int = 20) -> dict:
        """Analyze which signal sources are contributing to alpha.

        Returns:
            {
                "factor": {"avg_pnl": float, "win_rate": float, "n_trades": int},
                "vcp": {...},
                "pead": {...},
            }
        """
        if len(self._exit_log) < min_trades:
            return {}

        attribution = {}
        for source in ["factor", "vcp", "pead"]:
            # Trades where this signal was active (score > 50)
            active_trades = [
                e for e in self._exit_log
                if e["signals_at_entry"].get(source, 0) > 50
            ]

            if len(active_trades) >= 5:
                pnls = [t["pnl_pct"] for t in active_trades]
                attribution[source] = {
                    "avg_pnl": round(np.mean(pnls), 2),
                    "win_rate": round(sum(1 for p in pnls if p > 0) / len(pnls), 3),
                    "n_trades": len(active_trades),
                }

        return attribution

    def update_weights(self, min_trades: int = 30) -> dict:
        """Dynamically adjust signal weights based on historical performance.

        Returns updated weights dict.
        """
        attr = self.get_signal_attribution(min_trades)
        if not attr:
            return self._source_weights.copy()

        # Score each source by win_rate * avg_pnl (risk-adjusted edge)
        scores = {}
        for source, stats in attr.items():
            if stats["avg_pnl"] > 0:
                scores[source] = stats["win_rate"] * stats["avg_pnl"]
            else:
                scores[source] = max(stats["win_rate"] * stats["avg_pnl"], 0.01)

        if not scores:
            return self._source_weights.copy()

        # Normalize to sum to 1
        total = sum(scores.values())
        if total > 0:
            new_weights = {s: v / total for s, v in scores.items()}
            # Blend: 70% new evidence, 30% prior (avoid overfitting)
            for source in self._source_weights:
                if source in new_weights:
                    self._source_weights[source] = (
                        0.7 * new_weights[source] +
                        0.3 * self._source_weights[source]
                    )

            # Re-normalize
            total = sum(self._source_weights.values())
            self._source_weights = {
                s: v / total for s, v in self._source_weights.items()
            }

        return self._source_weights.copy()

    def get_current_weights(self) -> dict:
        """Return current signal weights."""
        return self._source_weights.copy()
