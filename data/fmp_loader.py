"""FMP Data Loader - Load and prepare all FMP parquet data for backtesting."""

import os
from typing import Dict, List

import numpy as np
import pandas as pd

from config import FMP_CACHE


class FMPDataLoader:
    """Load and prepare all FMP data for backtesting."""

    def __init__(self, cache_dir: str = FMP_CACHE):
        self.cache_dir = cache_dir
        self._fundamentals = None
        self._earnings = None
        self._analyst_grades = None
        self._insider_trades = None
        self._congressional = None
        self._macro = None
        self._pit_index = None
        self._sp500_info = None
        self._sector_map = {}

    def load_all(self):
        """Load all datasets into memory."""
        print("📊 Loading FMP data...")

        # S&P 500 current info (for sector mapping)
        self._sp500_info = pd.read_parquet(
            os.path.join(self.cache_dir, "sp500_current.parquet")
        )
        self._sector_map = dict(
            zip(self._sp500_info["symbol"], self._sp500_info["sector"])
        )
        print(f"  Sectors: {len(set(self._sector_map.values()))} sectors, "
              f"{len(self._sector_map)} tickers")

        # Point-in-time S&P 500 membership
        self._pit_index = pd.read_parquet(
            os.path.join(self.cache_dir, "sp500_pit_index.parquet")
        )
        self._pit_index["date"] = pd.to_datetime(self._pit_index["date"])
        print(f"  PIT index: {len(self._pit_index)} rows")

        # Fundamentals (merged quarterly financials)
        self._fundamentals = pd.read_parquet(
            os.path.join(self.cache_dir, "fundamentals_merged.parquet")
        )
        self._fundamentals["filingDate"] = pd.to_datetime(
            self._fundamentals["filingDate"]
        )
        print(f"  Fundamentals: {len(self._fundamentals)} rows, "
              f"{self._fundamentals['symbol'].nunique()} tickers")

        # Macro
        self._macro = pd.read_parquet(
            os.path.join(self.cache_dir, "macro_merged.parquet")
        )
        self._macro["date"] = pd.to_datetime(self._macro["date"])
        print(f"  Macro: {len(self._macro)} rows")

        # Load factor files (per-ticker parquets)
        self._earnings = self._load_factor_dir("earnings")
        print(f"  Earnings: {len(self._earnings)} rows")

        self._analyst_grades = self._load_factor_dir("analyst_grades")
        print(f"  Analyst grades: {len(self._analyst_grades)} rows")

        self._insider_trades = self._load_factor_dir("insider_trades")
        print(f"  Insider trades: {len(self._insider_trades)} rows")

        self._congressional = self._load_factor_dir("congressional_trades")
        print(f"  Congressional: {len(self._congressional)} rows")

        print("✅ All data loaded.\n")

    def _load_factor_dir(self, subdir: str) -> pd.DataFrame:
        """Load all parquet files from a factor subdirectory."""
        path = os.path.join(self.cache_dir, subdir)
        if not os.path.exists(path):
            return pd.DataFrame()
        dfs = []
        for f in os.listdir(path):
            if f.endswith(".parquet"):
                try:
                    df = pd.read_parquet(os.path.join(path, f))
                    dfs.append(df)
                except Exception:
                    continue
        if not dfs:
            return pd.DataFrame()
        result = pd.concat(dfs, ignore_index=True)
        # Standardize date column
        for col in ["date", "filingDate", "disclosureDate"]:
            if col in result.columns:
                result[col] = pd.to_datetime(result[col], errors="coerce")
        return result

    def get_sp500_members(self, date: pd.Timestamp) -> List[str]:
        """Get S&P 500 members at a specific date (point-in-time)."""
        monthly = self._pit_index[self._pit_index["date"] <= date]
        if monthly.empty:
            return []
        latest = monthly["date"].max()
        members = monthly[
            (monthly["date"] == latest) & (monthly["in_index"] == True)
        ]["symbol"].tolist()
        return members

    def get_sector(self, symbol: str) -> str:
        """Get sector for a symbol."""
        return self._sector_map.get(symbol, "Unknown")

    def get_fundamentals_at(self, date: pd.Timestamp) -> pd.DataFrame:
        """Get most recent fundamentals available at date (point-in-time)."""
        available = self._fundamentals[
            self._fundamentals["filingDate"] <= date
        ].copy()
        # Keep only most recent filing per symbol
        available = available.sort_values("filingDate").groupby("symbol").last()
        return available

    def get_earnings_at(self, symbol: str, date: pd.Timestamp,
                        lookback_days: int = 365) -> pd.DataFrame:
        """Get earnings history for a symbol available at date."""
        if self._earnings.empty:
            return pd.DataFrame()
        mask = (
            (self._earnings["symbol"] == symbol) &
            (self._earnings["date"] <= date) &
            (self._earnings["date"] >= date - pd.Timedelta(days=lookback_days)) &
            (self._earnings["epsActual"].notna())
        )
        return self._earnings[mask].sort_values("date")

    def get_analyst_grades_at(self, date: pd.Timestamp) -> pd.DataFrame:
        """Get most recent analyst grades at date."""
        if self._analyst_grades.empty or "date" not in self._analyst_grades.columns:
            return pd.DataFrame()
        available = self._analyst_grades[
            self._analyst_grades["date"] <= date
        ].copy()
        available = available.sort_values("date").groupby("symbol").last()
        return available

    def get_insider_trades(self, symbol: str, date: pd.Timestamp,
                           lookback_days: int = 180) -> pd.DataFrame:
        """Get insider trades for symbol in lookback window."""
        if self._insider_trades.empty:
            return pd.DataFrame()
        date_col = "filingDate" if "filingDate" in self._insider_trades.columns else "date"
        mask = (
            (self._insider_trades["symbol"] == symbol) &
            (self._insider_trades[date_col] <= date) &
            (self._insider_trades[date_col] >= date - pd.Timedelta(days=lookback_days))
        )
        return self._insider_trades[mask]

    def get_congressional_trades(self, symbol: str, date: pd.Timestamp,
                                  lookback_days: int = 180) -> pd.DataFrame:
        """Get congressional trades for symbol in lookback window."""
        if self._congressional.empty:
            return pd.DataFrame()
        date_col = "disclosureDate" if "disclosureDate" in self._congressional.columns else "date"
        mask = (
            (self._congressional["symbol"] == symbol) &
            (self._congressional[date_col] <= date) &
            (self._congressional[date_col] >= date - pd.Timedelta(days=lookback_days))
        )
        return self._congressional[mask]

    def get_macro_at(self, date: pd.Timestamp) -> pd.Series:
        """Get macro data at date."""
        available = self._macro[self._macro["date"] <= date]
        if available.empty:
            return pd.Series()
        return available.iloc[-1]
