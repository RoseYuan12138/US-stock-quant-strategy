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

    # Factors with consistent positive IC across regimes.
    # Momentum dominates; analyst_revision and SUE add small edge.
    KEEP_FACTORS = [
        "mom_12m_skip1_z",     # Strongest IC: +0.007-0.015 across regimes
        "mom_6m_z",            # Good momentum signal
        "mom_1m_rev_z",        # Best IC in bull (+0.021); short-term reversal adds edge
        "analyst_revision_z",  # Consistent: -0.006 bull but +0.025/+0.026 crash/bear
        "sue_z",               # Small but positive
        "accruals_z",          # Quality screen
    ]

    # Static factor weights — same for all regimes.
    # Lesson from rounds 6-8: regime-specific weights hurt more than they help.
    # analyst_revision_z is forward-looking and works in ALL regimes:
    # - 2022 bear: energy analysts upgrading → selects energy correctly
    # - 2023 recovery: tech analysts upgrading → selects NVDA/META correctly
    # Concentrated single-dominant-factor approach beats balanced portfolio of factors.
    FACTOR_WEIGHTS = {
        "analyst_revision_z": 0.35,
        "mom_6m_z": 0.20,
        "mom_12m_skip1_z": 0.20,
        "mom_1m_rev_z": 0.10,
        "sue_z": 0.10,
        "accruals_z": 0.05,
    }

    # Regime aliases (all same — preserve interface compatibility)
    BULL_WEIGHTS = FACTOR_WEIGHTS
    BEAR_WEIGHTS = FACTOR_WEIGHTS
    CAUTION_WEIGHTS = FACTOR_WEIGHTS

    def __init__(self, config):
        self.config = config
        self.factor_engine = None
        self.ic_tracker = None

        # V8 components
        self.top_detector = MarketTopDetector()
        self.ftd_detector = FTDDetector()
        self.exposure_coach = ExposureCoach()
        self.position_sizer = ATRPositionSizer(
            max_single_pct=0.07,
            max_sector_pct=0.25,  # Tighter sector cap (was 30%) to avoid single-sector concentration
            target_n=20,
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

    def _compute_trend_exposure(self, date: pd.Timestamp) -> tuple:
        """Trend-following exposure based on SPY moving averages + recovery signal.

        Primary signal: SPY vs 200/50/20 DMA stack.
        Recovery boost: when 50DMA is rising and SPY has bounced from bear low,
        add up to +0.15 exposure to avoid being stuck in BEAR during early recovery.
        This specifically targets the Oct 2022 → Apr 2023 bottoming/recovery sequence
        where pure 200DMA crossover is too lagging.

        Returns (max_exposure, regime_label).
        """
        spy = self._price_data.get("SPY")
        if spy is None:
            return 0.70, "CAUTION"

        spy_up = spy[spy.index <= date]
        if len(spy_up) < 200:
            return 0.70, "CAUTION"

        close = spy_up["Close"]
        current = float(close.iloc[-1])
        sma_200 = float(close.iloc[-200:].mean())
        sma_50 = float(close.iloc[-50:].mean())
        sma_20 = float(close.iloc[-20:].mean()) if len(close) >= 20 else sma_50

        # Trend alignment: all MAs stacked bullishly
        if current > sma_20 and sma_20 > sma_50 and sma_50 > sma_200:
            return 0.95, "BULL"         # Perfect bull alignment
        elif current > sma_50 and sma_50 > sma_200:
            return 0.85, "BULL"         # Good uptrend
        elif current > sma_200:
            return 0.70, "CAUTION"      # Above 200DMA but choppy

        # Below 200DMA — check recovery signal before assigning bear exposure
        # Recovery signal: 50DMA is rising (short-term trend turning up) AND
        # SPY has bounced ≥10% from recent 52-week low (confirmed liftoff)
        low_52w = float(close.iloc[-252:].min()) if len(close) >= 252 else float(close.min())
        bounce_pct = (current / low_52w - 1)

        # 50DMA direction: compare recent 50DMA to 20 trading days ago
        sma_50_prior = float(close.iloc[-70:-20].mean()) if len(close) >= 70 else sma_50
        sma_50_rising = sma_50 > sma_50_prior

        if current > sma_200 * 0.93:
            # Just below 200DMA (-7%): DEFENSIVE base
            if sma_50_rising and bounce_pct >= 0.10:
                return 0.65, "DEFENSIVE"   # Recovery in progress: boost from 0.50
            return 0.50, "DEFENSIVE"
        elif current > sma_200 * 0.85:
            # Clearly below 200DMA (-15% to -7%): BEAR base
            if sma_50_rising and bounce_pct >= 0.12:
                return 0.45, "DEFENSIVE"   # Bear recovery: upgrade to DEFENSIVE
            return 0.30, "BEAR"
        else:
            # Deep bear (>-15% below 200DMA)
            if sma_50_rising and bounce_pct >= 0.15:
                return 0.35, "BEAR"        # Deep bear recovery: modest boost
            return 0.15, "BEAR"

    def on_rebalance(self, date: pd.Timestamp, universe: list,
                     prev_date: pd.Timestamp = None,
                     prev_factors: pd.DataFrame = None
                     ) -> Tuple[Dict[str, float], pd.DataFrame]:
        """V8 rebalance: defense check → offense check → stock selection → sizing."""

        # --- EXPOSURE DECISION (trend-following primary signal) ---
        max_exposure, regime = self._compute_trend_exposure(date)

        # Secondary: MarketTopDetector adjusts exposure at extremes
        # (keep for breadth/leading-stock context, but don't let it override trend)
        macro = self._data_loader.get_macro_at(date)
        top_result = self.top_detector.assess(
            date, universe, self._price_data, macro)
        top_risk = top_result.get("top_risk", 0)

        # Only apply top_risk reduction at very high readings to avoid
        # double-penalizing post-crash recovery periods
        if top_risk >= 85:
            max_exposure = min(max_exposure, 0.35)
            regime = "BEAR"
        elif top_risk >= 72:
            max_exposure = min(max_exposure, max_exposure * 0.80)

        self._current_regime = regime
        self._current_exposure = max_exposure

        self._diagnostics["regime_history"].append(
            (str(date), self._current_regime, self._current_exposure))

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

        # Regime-specific factor weights based on IC evidence
        if regime == "BULL":
            weights = self.BULL_WEIGHTS
        elif regime in ("BEAR", "DEFENSIVE"):
            weights = self.BEAR_WEIGHTS
        else:  # CAUTION
            weights = self.CAUTION_WEIGHTS

        if factors_df is not None and not factors_df.empty:
            factors_df = self.factor_engine.compute_composite_score(
                factors_df, weights)

        # B) VCP screening
        spy_df = self._price_data.get("SPY")
        vcp_candidates = self.vcp_screener.screen(
            date, universe, self._price_data, spy_df)
        vcp_symbols = {c["symbol"]: c["vcp_score"] for c in vcp_candidates[:50]}

        # C) PEAD screening
        pead_candidates = self.pead_screener.screen(
            date, universe, self._price_data,
            self._data_loader._earnings)
        pead_symbols = {c["symbol"]: c["pead_score"] for c in pead_candidates[:40]}

        # --- COMBINE SIGNALS ---
        # Build candidate list with multi-signal scoring
        sector_map = {sym: self._data_loader.get_sector(sym) for sym in universe}
        candidates = self._combine_signals(
            factors_df, vcp_symbols, pead_symbols, universe, regime, sector_map)

        # --- PHASE 4: POSITION SIZING ---

        target = self.position_sizer.size_portfolio(
            candidates=candidates,
            price_data=self._price_data,
            date=date,
            portfolio_value=self.config.initial_capital,
            max_exposure=self._current_exposure,
            sector_map=sector_map,
        )

        return target, factors_df if factors_df is not None else pd.DataFrame()

    # Sector classification for regime-aware selection
    DEFENSIVE_SECTORS = {"Healthcare", "Consumer Staples", "Utilities"}
    CYCLICAL_SECTORS = {"Energy", "Materials", "Consumer Discretionary"}

    def _combine_signals(self, factors_df: pd.DataFrame,
                         vcp_symbols: dict, pead_symbols: dict,
                         universe: list,
                         regime: str = "BULL",
                         sector_map: dict = None) -> list:
        """Combine factor scores, VCP, and PEAD into ranked candidates.

        Weights:
            Factor composite z-score: 40%
            VCP score: 35%
            PEAD score: 25%

        In BEAR/DEFENSIVE: defensive sectors get +15% boost; cyclicals get -20% penalty.
        This prevents momentum factors from locking into 2022 energy winners
        right as the market transitions to a tech-led recovery.
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

            # No sector bias — let factor weights drive selection.
            # Sector penalties backfire: energy was the 2022 top sector (+60%)
            # despite BEAR regime. fcf_yield_z/roe_z naturally select energy
            # in 2022 (high oil FCF). Regime rotation in 2023 handled by
            # CAUTION_WEIGHTS which boost analyst_revision_z and mom_1m_rev_z.

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
