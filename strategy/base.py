"""Strategy base class - all strategies implement this interface."""

from abc import ABC, abstractmethod
from typing import Dict

import pandas as pd


class StrategyBase(ABC):
    """Abstract base for all trading strategies.

    The backtester calls on_rebalance() at each rebalance point and uses
    the returned target weights to execute trades. Strategy internals
    (factors, IC tracking, regime, etc.) are encapsulated here.
    """

    name: str = "BaseStrategy"

    @abstractmethod
    def initialize(self, data_loader, price_data: Dict[str, pd.DataFrame],
                   spy_prices: pd.Series):
        """Called once before backtest loop starts.

        Args:
            data_loader: FMPDataLoader instance (fundamentals, earnings, etc.)
            price_data: {symbol: OHLCV DataFrame} for all tickers
            spy_prices: SPY close price series
        """
        pass

    @abstractmethod
    def on_rebalance(self, date: pd.Timestamp, universe: list,
                     prev_date: pd.Timestamp = None,
                     prev_factors: pd.DataFrame = None
                     ) -> Dict[str, float]:
        """Generate target portfolio weights at rebalance.

        Args:
            date: current rebalance date
            universe: list of tradable symbols
            prev_date: previous rebalance date (for IC calculation)
            prev_factors: factors DataFrame from previous rebalance

        Returns:
            {symbol: target_weight} dict, weights should sum to ~1.0
        """
        pass

    @abstractmethod
    def get_regime(self) -> str:
        """Return current regime label (e.g., 'BULL', 'CAUTION', 'BEAR')."""
        pass

    @abstractmethod
    def get_diagnostics(self) -> dict:
        """Return strategy-specific diagnostics for the report.

        Should include at minimum:
            - 'factor_ic': dict of factor IC statistics (if applicable)
            - 'sector_allocation': dict from rebalance logs (if applicable)
        """
        pass
