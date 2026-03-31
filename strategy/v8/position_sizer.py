"""ATR-Based Position Sizer.

Computes position sizes based on volatility (ATR), so high-vol stocks
get smaller positions and low-vol stocks get larger positions.
Risk per trade is capped at 1% of portfolio.
"""

import numpy as np
import pandas as pd


class ATRPositionSizer:
    """Risk-based position sizing using ATR."""

    def __init__(self, risk_pct: float = 0.01, atr_multiplier: float = 2.0,
                 max_single_pct: float = 0.10, max_sector_pct: float = 0.30):
        self.risk_pct = risk_pct            # 1% risk per trade
        self.atr_multiplier = atr_multiplier  # Stop = 2x ATR
        self.max_single_pct = max_single_pct  # Max 10% per stock
        self.max_sector_pct = max_sector_pct  # Max 30% per sector

    def compute_weight(self, symbol: str, price_data: pd.DataFrame,
                       date: pd.Timestamp, portfolio_value: float) -> float:
        """Compute target weight for a single stock.

        Returns:
            float: target portfolio weight (0 to max_single_pct)
        """
        df = price_data[price_data.index <= date]
        if len(df) < 15:
            return 0.0

        close = df["Close"].values.astype(float)
        high = df["High"].values.astype(float) if "High" in df.columns else close
        low = df["Low"].values.astype(float) if "Low" in df.columns else close

        current_price = close[-1]
        if current_price <= 0:
            return 0.0

        # ATR(14) calculation
        atr = self._compute_atr(high, low, close, period=14)
        if atr <= 0:
            return self.max_single_pct  # Fallback to max if ATR is 0

        # Stop distance = ATR * multiplier
        stop_distance = atr * self.atr_multiplier

        # Dollar risk = portfolio * risk_pct
        dollar_risk = portfolio_value * self.risk_pct

        # Shares = dollar_risk / stop_distance
        shares = int(dollar_risk / stop_distance)
        if shares <= 0:
            return 0.0

        # Position value
        position_value = shares * current_price
        weight = position_value / portfolio_value

        # Cap at max_single_pct
        return min(weight, self.max_single_pct)

    def size_portfolio(self, candidates: list, price_data: dict,
                       date: pd.Timestamp, portfolio_value: float,
                       max_exposure: float = 1.0,
                       sector_map: dict = None) -> dict:
        """Size a portfolio of candidates.

        Args:
            candidates: List of {symbol, score, ...} dicts, sorted by score desc
            price_data: {symbol: DataFrame} price data
            date: Current date
            portfolio_value: Total portfolio value
            max_exposure: Maximum total equity exposure (0-1) from ExposureCoach
            sector_map: {symbol: sector} mapping

        Returns:
            {symbol: target_weight} dict
        """
        if not candidates or portfolio_value <= 0:
            return {}

        target = {}
        total_weight = 0.0
        sector_weights = {}  # {sector: total_weight}

        for cand in candidates:
            sym = cand["symbol"]
            if sym not in price_data:
                continue

            # Compute ATR-based weight
            weight = self.compute_weight(
                sym, price_data[sym], date, portfolio_value)

            if weight <= 0:
                continue

            # Check sector constraint
            if sector_map:
                sector = sector_map.get(sym, "Unknown")
                current_sector = sector_weights.get(sector, 0)
                if current_sector + weight > self.max_sector_pct:
                    weight = max(0, self.max_sector_pct - current_sector)
                    if weight <= 0.005:
                        continue

            # Check total exposure constraint
            if total_weight + weight > max_exposure:
                weight = max(0, max_exposure - total_weight)
                if weight <= 0.005:
                    break

            target[sym] = weight
            total_weight += weight

            if sector_map:
                sector = sector_map.get(sym, "Unknown")
                sector_weights[sector] = sector_weights.get(sector, 0) + weight

            if total_weight >= max_exposure:
                break

        return target

    def _compute_atr(self, high: np.ndarray, low: np.ndarray,
                     close: np.ndarray, period: int = 14) -> float:
        """Compute Average True Range."""
        n = len(close)
        if n < period + 1:
            return float(high[-1] - low[-1]) if n > 0 else 0

        tr = np.zeros(n - 1)
        for i in range(1, n):
            tr[i - 1] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1])
            )

        # Simple average of last `period` TRs
        atr = np.mean(tr[-period:])
        return float(atr)
