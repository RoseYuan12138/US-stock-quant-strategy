"""V8 Strategy — Druckenmiller-inspired attack/defense architecture.

Architecture:
    Defense: MarketTopDetector (distribution days + breadth + technicals)
    Offense: FTDDetector (follow-through day re-entry signal)
    Selection: VCP + PEAD + refined V7 factors
    Sizing: ATR-based position sizing with exposure ceiling
    Coordination: ExposureCoach synthesizes all signals
"""

from typing import Dict, Tuple

import numpy as np
import pandas as pd

from strategy.base import StrategyBase
from strategy.factors import FactorEngine
from strategy.ic_tracker import ICTracker

from .market_top import MarketTopDetector
from .ftd_detector import FTDDetector
from .exposure_coach import ExposureCoach
from .position_sizer import ATRPositionSizer
from .vcp_screener import VCPScreener
from .pead_screener import PEADScreener


class V8Strategy(StrategyBase):
    """V8: Attack/Defense + Multi-Signal Stock Selection."""

    name = "V8 Druckenmiller Attack/Defense"

    # Factors to keep from V7 (stable IC across regimes)
    KEEP_FACTORS = [
        "analyst_revision_z", "sue_z", "accruals_z",
        "mom_6m_z", "mom_12m_skip1_z",
    ]

    def __init__(self, config):
        self.config = config
        self.factor_engine = None
        self.ic_tracker = None

        # V8 components
        self.top_detector = MarketTopDetector()
        self.ftd_detector = FTDDetector()
        self.exposure_coach = ExposureCoach()
        self.position_sizer = ATRPositionSizer(
            risk_pct=0.01,
            atr_multiplier=2.0,
            max_single_pct=0.10,
            max_sector_pct=0.30,
        )
        self.vcp_screener = VCPScreener()
        self.pead_screener = PEADScreener()

        # State
        self._data_loader = None
        self._price_data = None
        self._spy_prices = None
        self._current_regime = "BULL"
        self._current_exposure = 1.0
        self._diagnostics = {
            "factor_ic": {},
            "regime_history": [],
            "exposure_history": [],
        }

    def initialize(self, data_loader, price_data: Dict[str, pd.DataFrame],
                   spy_prices: pd.Series):
        self._data_loader = data_loader
        self._price_data = price_data
        self._spy_prices = spy_prices

        self.factor_engine = FactorEngine(data_loader, self.config)
        self.ic_tracker = ICTracker(self.config.ic_lookback_months)

        # Build sector weight benchmarks
        sp500_current = list(data_loader._sector_map.keys())
        sectors = {}
        for sym in sp500_current:
            s = data_loader.get_sector(sym)
            sectors[s] = sectors.get(s, 0) + 1
        total = sum(sectors.values())
        self._benchmark_sector_weights = {
            s: c / total for s, c in sectors.items()
        }

    def on_rebalance(self, date: pd.Timestamp, universe: list,
                     prev_date: pd.Timestamp = None,
                     prev_factors: pd.DataFrame = None
                     ) -> Tuple[Dict[str, float], pd.DataFrame]:
        """V8 rebalance: defense check → offense check → stock selection → sizing."""

        # --- PHASE 1: DEFENSE ASSESSMENT ---
        macro = self._data_loader.get_macro_at(date)
        top_result = self.top_detector.assess(
            date, universe, self._price_data, macro)

        # --- PHASE 2: OFFENSE ASSESSMENT ---
        ftd_result = self.ftd_detector.update(date, self._price_data)

        # --- EXPOSURE DECISION ---
        exposure = self.exposure_coach.recommend(top_result, ftd_result)
        self._current_regime = exposure["regime"]
        self._current_exposure = exposure["max_exposure"]

        self._diagnostics["regime_history"].append(
            (str(date), self._current_regime, self._current_exposure))
        self._diagnostics["exposure_history"].append(
            (str(date), exposure))

        # If CASH_PRIORITY, use minimal exposure (not zero — avoid missing recoveries)
        if exposure["action"] == "CASH_PRIORITY":
            self._current_exposure = max(self._current_exposure, 0.15)

        # --- PHASE 3: STOCK SELECTION ---
        # A) Compute V7 factors (refined subset)
        factors_df = self.factor_engine.compute_all_factors(
            date, universe, self._price_data)

        # Record IC from previous period
        if prev_factors is not None and prev_date is not None:
            fwd_returns = self._compute_forward_returns(
                prev_factors, prev_date, date)
            if fwd_returns:
                self.ic_tracker.record_ic(date, prev_factors, fwd_returns)

        # IC-weighted composite (only keep stable factors)
        ic_weights = self.ic_tracker.get_ic_weights()
        # Zero out factors we don't trust
        filtered_weights = {}
        for k, v in ic_weights.items():
            if k in self.KEEP_FACTORS:
                filtered_weights[k] = v
            else:
                filtered_weights[k] = 0.0

        if factors_df is not None and not factors_df.empty:
            factors_df = self.factor_engine.compute_composite_score(
                factors_df, filtered_weights)

        # B) VCP screening
        spy_df = self._price_data.get("SPY")
        vcp_candidates = self.vcp_screener.screen(
            date, universe, self._price_data, spy_df)
        vcp_symbols = {c["symbol"]: c["vcp_score"] for c in vcp_candidates[:30]}

        # C) PEAD screening
        pead_candidates = self.pead_screener.screen(
            date, universe, self._price_data,
            self._data_loader._earnings)
        pead_symbols = {c["symbol"]: c["pead_score"] for c in pead_candidates[:20]}

        # --- COMBINE SIGNALS ---
        # Build candidate list with multi-signal scoring
        candidates = self._combine_signals(
            factors_df, vcp_symbols, pead_symbols, universe)

        # --- PHASE 4: POSITION SIZING ---
        sector_map = {sym: self._data_loader.get_sector(sym) for sym in universe}

        target = self.position_sizer.size_portfolio(
            candidates=candidates,
            price_data=self._price_data,
            date=date,
            portfolio_value=self.config.initial_capital,
            max_exposure=self._current_exposure,
            sector_map=sector_map,
        )

        return target, factors_df if factors_df is not None else pd.DataFrame()

    def _combine_signals(self, factors_df: pd.DataFrame,
                         vcp_symbols: dict, pead_symbols: dict,
                         universe: list) -> list:
        """Combine factor scores, VCP, and PEAD into ranked candidates.

        Weights:
            Factor composite z-score: 40%
            VCP score: 35%
            PEAD score: 25%
        """
        scores = {}

        # Factor scores (normalized to 0-100)
        if factors_df is not None and "composite_z" in factors_df.columns:
            z_min = factors_df["composite_z"].min()
            z_max = factors_df["composite_z"].max()
            z_range = z_max - z_min if z_max > z_min else 1

            for _, row in factors_df.iterrows():
                sym = row.get("symbol", "")
                if not sym or sym not in universe:
                    continue
                z = row.get("composite_z", 0)
                factor_score = ((z - z_min) / z_range) * 100
                scores[sym] = {"factor": factor_score, "vcp": 0, "pead": 0}

        # VCP scores
        for sym, vcp_score in vcp_symbols.items():
            if sym not in scores:
                scores[sym] = {"factor": 50, "vcp": 0, "pead": 0}
            scores[sym]["vcp"] = vcp_score

        # PEAD scores
        for sym, pead_score in pead_symbols.items():
            if sym not in scores:
                scores[sym] = {"factor": 50, "vcp": 0, "pead": 0}
            scores[sym]["pead"] = pead_score

        # Composite
        candidates = []
        for sym, s in scores.items():
            composite = (
                s["factor"] * 0.40 +
                s["vcp"] * 0.35 +
                s["pead"] * 0.25
            )

            # Bonus: multi-signal agreement
            signals_active = sum([
                s["factor"] > 60,
                s["vcp"] > 50,
                s["pead"] > 50,
            ])
            if signals_active >= 2:
                composite *= 1.15  # 15% bonus for multi-signal
            if signals_active >= 3:
                composite *= 1.10  # Additional 10% for triple agreement

            candidates.append({
                "symbol": sym,
                "score": composite,
                "factor_score": s["factor"],
                "vcp_score": s["vcp"],
                "pead_score": s["pead"],
            })

        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates

    def _compute_forward_returns(self, factors_df: pd.DataFrame,
                                  prev_date: pd.Timestamp,
                                  current_date: pd.Timestamp) -> dict:
        """Compute forward returns from prev_date to current_date."""
        fwd = {}
        if "symbol" not in factors_df.columns:
            return fwd

        for sym in factors_df["symbol"].values:
            if sym not in self._price_data:
                continue
            p = self._price_data[sym]
            prev = p[p.index <= prev_date]
            curr = p[p.index <= current_date]
            if len(prev) > 0 and len(curr) > 0:
                p0 = float(prev["Close"].iloc[-1])
                p1 = float(curr["Close"].iloc[-1])
                if p0 > 0:
                    fwd[sym] = p1 / p0 - 1
        return fwd

    def get_regime(self) -> str:
        return self._current_regime

    def get_diagnostics(self) -> dict:
        ic_stats = {}
        if self.ic_tracker and self.ic_tracker.ic_history:
            # Compute mean IC per factor from history
            all_factors = set()
            for d in self.ic_tracker.ic_history:
                all_factors.update(d.keys())
            for f in all_factors:
                vals = [d.get(f, 0) for d in self.ic_tracker.ic_history]
                ic_stats[f] = {
                    "mean_ic": float(np.mean(vals)),
                    "n_obs": len(vals),
                }
        return {"factor_ic": ic_stats}
