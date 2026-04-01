"""Market Top Detector — composite top risk scoring.

Combines distribution days, leading stock health, defensive rotation,
breadth divergence, and index technicals into a 0-100 risk score.
"""

import numpy as np
import pandas as pd

from .distribution_days import DistributionDayCounter
from .market_breadth import MarketBreadthAnalyzer


class MarketTopDetector:
    """Detect market tops using O'Neil/Minervini methodology."""

    # Component weights
    W_DISTRIBUTION = 0.25
    W_LEADING_HEALTH = 0.20
    W_DEFENSIVE_ROTATION = 0.15
    W_BREADTH = 0.15
    W_TECHNICALS = 0.15
    W_SENTIMENT = 0.10

    def __init__(self):
        self.dist_counter = DistributionDayCounter()
        self.breadth_analyzer = MarketBreadthAnalyzer()
        self._last_result = None

    def assess(self, date: pd.Timestamp, universe: list,
               price_data: dict, macro: pd.Series = None) -> dict:
        """Compute market top risk score.

        Returns:
            {
                "top_risk": float (0-100, higher = more dangerous),
                "risk_zone": str (green/yellow/orange/red/critical),
                "components": dict of individual scores,
                "exposure_ceiling": float (0-1),
            }
        """
        components = {}

        # 1. Distribution days (SPY + QQQ)
        indices = [s for s in ["SPY", "QQQ"] if s in price_data]
        dist = self.dist_counter.count(date, price_data, indices)
        # Average risk across available indices
        dist_scores = [self.dist_counter.get_risk_score(dist[s]) for s in indices]
        components["distribution"] = np.mean(dist_scores) if dist_scores else 0

        # 2. Leading stock health — how are high-beta leaders doing?
        leaders = ["ARKK", "SOXX", "SMH", "IGV", "XBI"]
        components["leading_health"] = self._leading_stock_health(
            date, leaders, price_data)

        # 3. Defensive rotation — are defensives outperforming cyclicals?
        components["defensive_rotation"] = self._defensive_rotation(
            date, price_data)

        # 4. Breadth
        breadth = self.breadth_analyzer.compute(date, universe, price_data)
        # Invert: low breadth = high risk
        components["breadth_risk"] = max(0, 100 - breadth["breadth_score"])

        # 5. Index technicals
        components["technicals"] = self._index_technicals(date, price_data)

        # 6. Sentiment (yield curve inversion as proxy)
        components["sentiment"] = self._sentiment_score(date, macro)

        # Composite
        top_risk = (
            components["distribution"] * self.W_DISTRIBUTION +
            components["leading_health"] * self.W_LEADING_HEALTH +
            components["defensive_rotation"] * self.W_DEFENSIVE_ROTATION +
            components["breadth_risk"] * self.W_BREADTH +
            components["technicals"] * self.W_TECHNICALS +
            components["sentiment"] * self.W_SENTIMENT
        )

        top_risk = np.clip(top_risk, 0, 100)

        # Risk zone
        if top_risk <= 20:
            zone = "green"
        elif top_risk <= 40:
            zone = "yellow"
        elif top_risk <= 60:
            zone = "orange"
        elif top_risk <= 80:
            zone = "red"
        else:
            zone = "critical"

        # Exposure ceiling based on risk.
        # Smooth gradient — avoids the 0.65→0.45 cliff that traps post-crash
        # recoveries in DEFENSIVE even when FTD is confirmed.
        if top_risk <= 20:
            ceiling = 1.0
        elif top_risk <= 40:
            ceiling = 0.85
        elif top_risk <= 55:
            ceiling = 0.75
        elif top_risk <= 70:
            ceiling = 0.60
        elif top_risk <= 85:
            ceiling = 0.40
        else:
            ceiling = 0.25

        self._last_result = {
            "top_risk": round(top_risk, 1),
            "risk_zone": zone,
            "components": {k: round(v, 1) for k, v in components.items()},
            "exposure_ceiling": ceiling,
            "breadth": breadth,
        }
        return self._last_result

    def _leading_stock_health(self, date: pd.Timestamp,
                              leaders: list, price_data: dict) -> float:
        """Check if leading/speculative ETFs are breaking down.

        Returns 0-100 risk score (100 = leaders in bad shape).
        """
        risk_scores = []
        for sym in leaders:
            if sym not in price_data:
                continue
            df = price_data[sym]
            df_up_to = df[df.index <= date]
            if len(df_up_to) < 50:
                continue

            close = df_up_to["Close"]
            current = float(close.iloc[-1])
            high_52w = float(close.iloc[-252:].max()) if len(close) >= 252 else float(close.max())
            sma_50 = float(close.iloc[-50:].mean())
            sma_200 = float(close.iloc[-200:].mean()) if len(close) >= 200 else sma_50

            # How far from 52-week high?
            drawdown = (current / high_52w - 1)

            score = 0
            if current < sma_200:
                score += 40  # Below 200DMA
            if current < sma_50:
                score += 20  # Below 50DMA
            if drawdown < -0.20:
                score += 30  # 20%+ from high
            elif drawdown < -0.10:
                score += 15  # 10%+ from high

            risk_scores.append(min(score, 100))

        return np.mean(risk_scores) if risk_scores else 0

    def _defensive_rotation(self, date: pd.Timestamp,
                            price_data: dict) -> float:
        """Detect rotation into defensive sectors.

        Returns 0-100 (100 = strong defensive rotation = bearish signal).
        """
        defensive = ["XLU", "XLP", "XLV"]  # Utilities, Staples, Healthcare
        cyclical = ["XLK", "XLY", "XLC"]   # Tech, Consumer Disc, Comm Services

        def avg_return(symbols, lookback=20):
            returns = []
            for sym in symbols:
                if sym not in price_data:
                    continue
                df = price_data[sym]
                df_up_to = df[df.index <= date]
                if len(df_up_to) < lookback + 1:
                    continue
                close = df_up_to["Close"]
                ret = float(close.iloc[-1]) / float(close.iloc[-lookback]) - 1
                returns.append(ret)
            return np.mean(returns) if returns else 0

        def_ret = avg_return(defensive)
        cyc_ret = avg_return(cyclical)

        # If defensives outperforming cyclicals, risk is rising
        spread = def_ret - cyc_ret

        if spread > 0.05:
            return 90  # Strong defensive rotation
        elif spread > 0.02:
            return 60
        elif spread > 0:
            return 30
        else:
            return 10  # Cyclicals leading = risk-on

    def _index_technicals(self, date: pd.Timestamp,
                          price_data: dict) -> float:
        """Check index technical condition.

        Returns 0-100 risk (100 = bad technicals).
        """
        if "SPY" not in price_data:
            return 50

        df = price_data["SPY"]
        df_up_to = df[df.index <= date]
        if len(df_up_to) < 200:
            return 50

        close = df_up_to["Close"]
        current = float(close.iloc[-1])
        sma_50 = float(close.iloc[-50:].mean())
        sma_200 = float(close.iloc[-200:].mean())

        # Check for lower highs (bearish structure)
        risk = 0

        ret_20d = current / float(close.iloc[-20]) - 1 if len(close) >= 20 else 0

        if current < sma_200:
            risk += 40
        elif current < sma_50:
            risk += 20

        # Death cross — lagging indicator; discount when market is already bouncing
        if sma_50 < sma_200:
            if ret_20d > 0.03:
                risk += 10  # Recovering fast: discount the death cross signal
            else:
                risk += 25  # Normal death cross penalty (reduced from 30)

        # Recent momentum
        if ret_20d < -0.05:
            risk += 20
        elif ret_20d < -0.02:
            risk += 10

        return min(risk, 100)

    def _sentiment_score(self, date: pd.Timestamp,
                         macro: pd.Series = None) -> float:
        """Sentiment/macro risk using available macro data.

        Returns 0-100 risk.
        """
        if macro is None or macro.empty:
            return 30  # neutral default

        risk = 0

        # Yield curve inversion
        spread = macro.get("treasury_spread_10y2y", None)
        if spread is not None:
            if spread < -0.5:
                risk += 50  # Deep inversion
            elif spread < 0:
                risk += 30  # Inverted
            elif spread < 0.5:
                risk += 10  # Flat

        # Fed funds rate change
        ff_yoy = macro.get("macro_FEDFUNDS_yoy", None)
        if ff_yoy is not None:
            if ff_yoy > 2.0:
                risk += 30  # Aggressive tightening
            elif ff_yoy > 0.5:
                risk += 15  # Moderate tightening

        # Consumer confidence
        umcsent_yoy = macro.get("macro_UMCSENT_yoy", None)
        if umcsent_yoy is not None:
            if umcsent_yoy < -15:
                risk += 20  # Confidence cratering

        return min(risk, 100)
