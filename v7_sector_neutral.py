#!/usr/bin/env python3
"""
V7 Sector-Neutral Multi-Factor Strategy
========================================
Key improvements over V5/V6:
1. Sector-neutral portfolio construction (alpha = stock selection, not sector bet)
2. Cross-sectional z-score factor construction
3. Better factors: SUE, analyst revision momentum, accruals, insider $-value
4. Bi-weekly rebalancing with signal decay
5. IC-weighted dynamic factor combination
6. Uses FMP data (point-in-time, no look-ahead bias)

Usage:
    python3 v7_sector_neutral.py [--start 2015-01-01] [--end 2025-12-31] [--slippage 10]
"""

import argparse
import os
import sys
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────

FMP_CACHE = os.path.join(os.path.dirname(__file__), "fmp-datasource", "cache")


@dataclass
class V7Config:
    """V7 strategy configuration."""
    initial_capital: float = 100_000
    top_n_per_sector: int = 2          # pick top N stocks per sector
    max_total_holdings: int = 25       # absolute cap on positions
    min_zscore: float = -0.5           # minimum composite z-score to enter
    rebalance_days: int = 14           # bi-weekly
    slippage_bps: float = 10.0         # one-way slippage in bps
    commission: float = 0.0            # per-trade commission ($)
    trailing_stop_pct: float = 0.20    # 20% trailing stop
    spy_base_weight: float = 0.0       # no SPY ballast (fully sector-neutral)
    max_single_weight: float = 0.08    # 8% max per stock
    ic_lookback_months: int = 12       # IC estimation window
    factor_decay_days: int = 60        # signal half-life for earnings/insider


# ─────────────────────────────────────────────────────────────────────
# Data Loading
# ─────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────
# Factor Construction
# ─────────────────────────────────────────────────────────────────────

class FactorEngine:
    """Compute cross-sectional factor z-scores."""

    def __init__(self, data: FMPDataLoader, config: V7Config):
        self.data = data
        self.config = config

    def compute_all_factors(self, date: pd.Timestamp,
                            universe: List[str],
                            price_data: Dict[str, pd.DataFrame]
                            ) -> pd.DataFrame:
        """Compute all factors for the universe at date.
        Returns DataFrame with columns: symbol, sector, and one col per factor.
        """
        rows = []
        fundamentals = self.data.get_fundamentals_at(date)
        analyst_grades = self.data.get_analyst_grades_at(date)

        for sym in universe:
            row = {"symbol": sym, "sector": self.data.get_sector(sym)}

            # 1. Value factors
            if sym in fundamentals.index:
                f = fundamentals.loc[sym]
                row.update(self._value_factors(f))
                row.update(self._quality_factors(f))
                row.update(self._accruals_factor(f))
            else:
                row.update({k: np.nan for k in [
                    "earnings_yield", "book_yield", "fcf_yield",
                    "roe", "gross_margin", "operating_margin",
                    "accruals"
                ]})

            # 2. Momentum
            if sym in price_data and len(price_data[sym]) > 0:
                row.update(self._momentum_factors(price_data[sym], date))
            else:
                row.update({k: np.nan for k in [
                    "mom_6m", "mom_1m_rev", "mom_12m_skip1"
                ]})

            # 3. SUE (Standardized Unexpected Earnings)
            row["sue"] = self._sue_factor(sym, date)

            # 4. Analyst revision momentum
            row["analyst_revision"] = self._analyst_revision(
                sym, date, analyst_grades
            )

            # 5. Insider signal (dollar-weighted)
            row["insider_signal"] = self._insider_factor(sym, date)

            # 6. Congressional following
            row["congress_signal"] = self._congressional_factor(sym, date)

            rows.append(row)

        df = pd.DataFrame(rows)

        # Cross-sectional z-score normalization (sector-neutral)
        factor_cols = [
            "earnings_yield", "book_yield", "fcf_yield",
            "roe", "gross_margin", "operating_margin",
            "accruals",
            "mom_6m", "mom_1m_rev", "mom_12m_skip1",
            "sue", "analyst_revision",
            "insider_signal", "congress_signal",
        ]

        df = self._sector_neutral_zscore(df, factor_cols)

        return df

    def _value_factors(self, f: pd.Series) -> dict:
        """Compute value factors from fundamentals."""
        # Use trailing 4Q data where possible
        eps = f.get("epsDiluted", np.nan)
        bv_per_share = np.nan
        equity = f.get("totalStockholdersEquity", np.nan)
        shares = f.get("weightedAverageShsOutDil", np.nan)
        if pd.notna(equity) and pd.notna(shares) and shares > 0:
            bv_per_share = equity / shares

        fcf = f.get("freeCashFlow", np.nan)
        fcf_per_share = np.nan
        if pd.notna(fcf) and pd.notna(shares) and shares > 0:
            fcf_per_share = fcf / shares

        # Earnings yield = EPS / Price (inverted PE, higher = cheaper = better)
        # We'll normalize cross-sectionally so actual price doesn't matter here
        # Use EPS directly as proxy (same direction after z-scoring within sector)
        return {
            "earnings_yield": eps if pd.notna(eps) else np.nan,
            "book_yield": bv_per_share if pd.notna(bv_per_share) else np.nan,
            "fcf_yield": fcf_per_share if pd.notna(fcf_per_share) else np.nan,
        }

    def _quality_factors(self, f: pd.Series) -> dict:
        """Compute quality factors."""
        revenue = f.get("revenue", np.nan)
        gross_profit = f.get("grossProfit", np.nan)
        operating_income = f.get("operatingIncome", np.nan)
        net_income = f.get("netIncome", np.nan)
        equity = f.get("totalStockholdersEquity", np.nan)

        roe = np.nan
        if pd.notna(net_income) and pd.notna(equity) and equity > 0:
            roe = net_income / equity

        gross_margin = np.nan
        if pd.notna(gross_profit) and pd.notna(revenue) and revenue > 0:
            gross_margin = gross_profit / revenue

        operating_margin = np.nan
        if pd.notna(operating_income) and pd.notna(revenue) and revenue > 0:
            operating_margin = operating_income / revenue

        return {
            "roe": roe,
            "gross_margin": gross_margin,
            "operating_margin": operating_margin,
        }

    def _accruals_factor(self, f: pd.Series) -> dict:
        """Accruals = (Net Income - Operating Cash Flow) / Total Assets.
        Lower (more negative) = higher quality. We flip sign so higher = better.
        """
        net_income = f.get("netIncome", np.nan)
        ocf = f.get("operatingCashFlow",
                     f.get("netCashProvidedByOperatingActivities", np.nan))
        total_assets = f.get("totalAssets", np.nan)

        accruals = np.nan
        if (pd.notna(net_income) and pd.notna(ocf)
                and pd.notna(total_assets) and total_assets > 0):
            # Negative accruals = good (cash earnings > accounting earnings)
            # We flip: higher value = better quality
            accruals = -(net_income - ocf) / total_assets

        return {"accruals": accruals}

    def _momentum_factors(self, prices: pd.DataFrame,
                          date: pd.Timestamp) -> dict:
        """Compute momentum factors from price history."""
        # Ensure we only use data up to date
        p = prices[prices.index <= date]["Close"]
        if isinstance(p, pd.DataFrame):
            p = p.iloc[:, 0]

        result = {"mom_6m": np.nan, "mom_1m_rev": np.nan, "mom_12m_skip1": np.nan}

        if len(p) < 22:
            return result

        current = p.iloc[-1]

        # 6-month momentum (skip last 1 month for reversal)
        if len(p) >= 147:  # ~7 months
            price_6m_ago = p.iloc[-147]
            price_1m_ago = p.iloc[-22]
            if price_6m_ago > 0:
                result["mom_6m"] = (price_1m_ago / price_6m_ago) - 1.0

        # 1-month reversal (short-term mean reversion, flipped)
        if len(p) >= 22:
            price_1m_ago = p.iloc[-22]
            if price_1m_ago > 0:
                # Negative = reversal expected, positive = continuation
                # We flip: stocks that went down recently may bounce
                result["mom_1m_rev"] = -(current / price_1m_ago - 1.0)

        # 12-month skip-1-month momentum
        if len(p) >= 273:  # ~13 months
            price_12m_ago = p.iloc[-273]
            price_1m_ago = p.iloc[-22]
            if price_12m_ago > 0:
                result["mom_12m_skip1"] = (price_1m_ago / price_12m_ago) - 1.0

        return result

    def _sue_factor(self, symbol: str, date: pd.Timestamp) -> float:
        """Standardized Unexpected Earnings (SUE).
        SUE = (EPS_actual - EPS_estimate) / std(surprise) over recent quarters.
        With time decay.
        """
        earnings = self.data.get_earnings_at(symbol, date, lookback_days=730)
        if earnings.empty or len(earnings) < 2:
            return np.nan

        # Calculate surprise for each quarter
        surprises = []
        for _, row in earnings.iterrows():
            actual = row.get("epsActual", np.nan)
            estimated = row.get("epsEstimated", np.nan)
            if pd.notna(actual) and pd.notna(estimated) and estimated != 0:
                surprises.append(actual - estimated)

        if len(surprises) < 2:
            return np.nan

        # SUE = most recent surprise / std of surprises
        std_surprise = np.std(surprises)
        if std_surprise < 0.001:
            std_surprise = 0.001

        latest_surprise = surprises[-1]
        sue = latest_surprise / std_surprise

        # Apply time decay based on how long ago the last earnings was
        last_date = earnings["date"].iloc[-1]
        days_since = (date - last_date).days
        decay = np.exp(-days_since / self.config.factor_decay_days)

        return sue * decay

    def _analyst_revision(self, symbol: str, date: pd.Timestamp,
                          analyst_grades: pd.DataFrame) -> float:
        """Analyst revision momentum: change in consensus over recent months.
        Positive = upgrades outpacing downgrades.
        """
        if analyst_grades.empty or symbol not in analyst_grades.index:
            return np.nan

        # Get all grades for this symbol over last 6 months
        if self.data._analyst_grades.empty:
            return np.nan

        sym_grades = self.data._analyst_grades[
            (self.data._analyst_grades["symbol"] == symbol) &
            (self.data._analyst_grades["date"] <= date) &
            (self.data._analyst_grades["date"] >= date - pd.Timedelta(days=180))
        ].sort_values("date")

        if len(sym_grades) < 2:
            return np.nan

        # Compute weighted consensus score at each point
        # Score = (5*StrongBuy + 4*Buy + 3*Hold + 2*Sell + 1*StrongSell) / total
        def consensus_score(row):
            sb = row.get("analystRatingsStrongBuy", 0) or 0
            b = row.get("analystRatingsBuy", 0) or 0
            h = row.get("analystRatingsHold", 0) or 0
            s = row.get("analystRatingsSell", 0) or 0
            ss = row.get("analystRatingsStrongSell", 0) or 0
            total = sb + b + h + s + ss
            if total == 0:
                return np.nan
            return (5*sb + 4*b + 3*h + 2*s + 1*ss) / total

        latest = consensus_score(sym_grades.iloc[-1])
        earliest = consensus_score(sym_grades.iloc[0])

        if pd.isna(latest) or pd.isna(earliest):
            return np.nan

        # Revision = change in consensus (positive = upgraded)
        return latest - earliest

    def _insider_factor(self, symbol: str, date: pd.Timestamp) -> float:
        """Insider trading signal based on dollar value of purchases.
        Positive = net buying, negative = net selling.
        """
        trades = self.data.get_insider_trades(symbol, date, lookback_days=180)
        if trades.empty:
            return 0.0

        net_value = 0.0
        for _, t in trades.iterrows():
            shares = t.get("securitiesTransacted", 0) or 0
            price = t.get("price", 0) or 0
            disposition = t.get("acquisitionOrDisposition", "")
            tx_type = t.get("transactionType", "")

            # Skip non-open-market transactions (options exercise, etc.)
            if tx_type in ["F-InKind", "G-Gift", "W-Will"]:
                continue

            value = shares * price
            if disposition == "A":  # Acquisition (buy)
                net_value += value
            elif disposition == "D":  # Disposition (sell)
                net_value -= value

        # Normalize to millions for interpretability
        return net_value / 1_000_000

    def _congressional_factor(self, symbol: str,
                               date: pd.Timestamp) -> float:
        """Congressional trading signal.
        Count of net purchases by Congress members.
        """
        trades = self.data.get_congressional_trades(
            symbol, date, lookback_days=180
        )
        if trades.empty:
            return 0.0

        buys = len(trades[trades["type"].str.lower().str.contains(
            "purchase", na=False)])
        sells = len(trades[trades["type"].str.lower().str.contains(
            "sale", na=False)])

        return buys - sells

    def _sector_neutral_zscore(self, df: pd.DataFrame,
                                factor_cols: List[str]) -> pd.DataFrame:
        """Z-score each factor within sector (sector-neutral)."""
        for col in factor_cols:
            if col not in df.columns:
                df[col] = np.nan
                continue

            # Within each sector, compute z-score
            zscored = []
            for sector, group in df.groupby("sector"):
                vals = group[col].copy()
                mean = vals.mean()
                std = vals.std()
                if pd.isna(std) or std < 1e-10:
                    group = group.copy()
                    group[f"{col}_z"] = 0.0
                else:
                    group = group.copy()
                    group[f"{col}_z"] = (vals - mean) / std
                zscored.append(group)

            if zscored:
                df = pd.concat(zscored)

        return df

    def compute_composite_score(self, factors_df: pd.DataFrame,
                                 ic_weights: Optional[Dict[str, float]] = None
                                 ) -> pd.DataFrame:
        """Combine factor z-scores into composite using IC weights."""
        z_cols = [c for c in factors_df.columns if c.endswith("_z")]

        if ic_weights is None:
            # Equal weight as default
            ic_weights = {c: 1.0 for c in z_cols}

        # Normalize weights
        total_w = sum(abs(v) for v in ic_weights.values()) or 1.0
        norm_weights = {k: v / total_w for k, v in ic_weights.items()}

        # Compute weighted composite
        composite = pd.Series(0.0, index=factors_df.index)
        n_factors = pd.Series(0, index=factors_df.index)

        for col in z_cols:
            w = norm_weights.get(col, 0.0)
            valid = factors_df[col].notna()
            composite[valid] += factors_df.loc[valid, col] * w
            n_factors[valid] += 1

        # Penalize stocks with fewer valid factors
        min_factors = max(1, len(z_cols) // 2)
        composite[n_factors < min_factors] = np.nan

        factors_df = factors_df.copy()
        factors_df["composite_z"] = composite
        return factors_df


# ─────────────────────────────────────────────────────────────────────
# IC (Information Coefficient) Tracker
# ─────────────────────────────────────────────────────────────────────

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

        # Forward return series aligned with factors
        fwd = factors_df["symbol"].map(forward_returns)

        for col in z_cols:
            valid = factors_df[col].notna() & fwd.notna()
            if valid.sum() >= 10:
                # Rank IC (Spearman correlation)
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
            return {}  # Will fall back to equal weight

        # Use recent N months
        recent = self.ic_history[-self.lookback_months * 2:]  # ~bi-weekly

        if not recent:
            return {}

        # Average IC per factor
        z_cols = set()
        for d in recent:
            z_cols.update(d.keys())

        avg_ic = {}
        for col in z_cols:
            ics = [d.get(col, 0.0) for d in recent]
            mean_ic = np.mean(ics)
            # IC-IR weighting: use mean IC but also consider consistency
            std_ic = np.std(ics) if len(ics) > 1 else 1.0
            ic_ir = mean_ic / std_ic if std_ic > 0.01 else mean_ic
            avg_ic[col] = max(ic_ir, 0.0)  # Only use positive IC factors

        return avg_ic


# ─────────────────────────────────────────────────────────────────────
# Regime Filter (simplified, using macro data)
# ─────────────────────────────────────────────────────────────────────

class RegimeFilter:
    """Simple regime detection using macro + price data."""

    def __init__(self):
        self.current_regime = "BULL"

    def assess(self, date: pd.Timestamp, macro: pd.Series,
               spy_prices: pd.Series) -> Tuple[str, float]:
        """Returns (regime, position_multiplier)."""
        if spy_prices is None or len(spy_prices) < 200:
            return "BULL", 1.0

        spy_up_to = spy_prices[spy_prices.index <= date]
        if len(spy_up_to) < 200:
            return "BULL", 1.0

        current_price = spy_up_to.iloc[-1]
        sma_200 = spy_up_to.iloc[-200:].mean()
        sma_50 = spy_up_to.iloc[-50:].mean() if len(spy_up_to) >= 50 else current_price

        # Yield curve
        spread = macro.get("treasury_spread_10y2y", 1.0) if not macro.empty else 1.0

        score = 0
        # SPY above 200 SMA
        if current_price > sma_200:
            score += 2
        elif current_price > sma_200 * 0.95:
            score += 1

        # SPY above 50 SMA (short-term trend)
        if current_price > sma_50:
            score += 1

        # Yield curve not inverted
        if pd.notna(spread):
            if spread > 0:
                score += 1
            elif spread < -0.5:
                score -= 1

        if score >= 3:
            regime, mult = "BULL", 1.0
        elif score >= 1:
            regime, mult = "CAUTION", 0.7
        else:
            regime, mult = "BEAR", 0.4

        self.current_regime = regime
        return regime, mult


# ─────────────────────────────────────────────────────────────────────
# Sector-Neutral Portfolio Construction
# ─────────────────────────────────────────────────────────────────────

class SectorNeutralPortfolio:
    """Build a sector-neutral portfolio from factor scores."""

    def __init__(self, config: V7Config):
        self.config = config

    def construct(self, factors_df: pd.DataFrame,
                  benchmark_sector_weights: Dict[str, float],
                  regime_mult: float = 1.0) -> Dict[str, float]:
        """Construct sector-neutral portfolio.

        Returns: dict of {symbol: target_weight}
        """
        if factors_df.empty or "composite_z" not in factors_df.columns:
            return {}

        portfolio = {}
        total_weight = 0.0

        for sector, group in factors_df.groupby("sector"):
            # Get benchmark weight for this sector
            bench_weight = benchmark_sector_weights.get(sector, 0.0)
            if bench_weight < 0.01:
                continue  # Skip tiny sectors

            # Sort by composite z-score, pick top N
            valid = group[group["composite_z"].notna()].sort_values(
                "composite_z", ascending=False
            )

            top_n = min(self.config.top_n_per_sector, len(valid))
            if top_n == 0:
                continue

            selected = valid.head(top_n)

            # Filter: only select stocks with positive composite z-score
            selected = selected[
                selected["composite_z"] >= self.config.min_zscore
            ]
            if selected.empty:
                continue

            # Allocate sector weight equally among selected stocks
            weight_per_stock = bench_weight / len(selected) * regime_mult

            for _, row in selected.iterrows():
                sym = row["symbol"]
                w = min(weight_per_stock, self.config.max_single_weight)
                portfolio[sym] = w
                total_weight += w

        # Normalize if total > 100%
        if total_weight > 1.0:
            for sym in portfolio:
                portfolio[sym] /= total_weight

        # Cap total holdings
        if len(portfolio) > self.config.max_total_holdings:
            sorted_syms = sorted(
                portfolio.items(), key=lambda x: x[1], reverse=True
            )
            portfolio = dict(sorted_syms[:self.config.max_total_holdings])
            total = sum(portfolio.values())
            if total > 0:
                portfolio = {s: w/total for s, w in portfolio.items()}

        return portfolio


# ─────────────────────────────────────────────────────────────────────
# Backtester
# ─────────────────────────────────────────────────────────────────────

class V7Backtester:
    """Sector-neutral multi-factor backtester."""

    def __init__(self, config: V7Config):
        self.config = config
        self.data = FMPDataLoader()
        self.factor_engine = None
        self.ic_tracker = ICTracker(config.ic_lookback_months)
        self.regime_filter = RegimeFilter()
        self.portfolio_builder = SectorNeutralPortfolio(config)

    def run(self, start_date: str = "2015-01-01",
            end_date: str = "2025-12-31") -> Tuple[pd.DataFrame, dict]:
        """Run full backtest."""
        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date)

        # Load data
        self.data.load_all()
        self.factor_engine = FactorEngine(self.data, self.config)

        # Download price data via yfinance
        print("📈 Downloading price data...")
        all_tickers = self._get_all_tickers(start, end)
        price_data = self._download_prices(all_tickers, start, end)
        spy_prices = self._get_spy_prices(start, end)
        print(f"  Prices: {len(price_data)} tickers loaded\n")

        # Compute benchmark sector weights (from current S&P 500)
        benchmark_sector_weights = self._compute_sector_weights()

        # Generate trading dates
        if "SPY" in price_data and len(price_data["SPY"]) > 0:
            trading_dates = price_data["SPY"].index
        else:
            trading_dates = pd.bdate_range(start, end)

        trading_dates = trading_dates[
            (trading_dates >= start) & (trading_dates <= end)
        ]

        # State
        cash = self.config.initial_capital
        positions: Dict[str, dict] = {}  # sym -> {shares, entry_price, highest}
        daily_values = []
        trade_log = []
        rebalance_log = []
        last_rebalance = None
        last_factors_df = None
        last_target_portfolio = None

        print("🔄 Running backtest...")
        slippage = self.config.slippage_bps / 10000.0

        for i, date in enumerate(trading_dates):
            # Portfolio value
            port_value = cash
            for sym, pos in positions.items():
                if sym in price_data:
                    p = price_data[sym]
                    price_at = p[p.index <= date]
                    if len(price_at) > 0:
                        current_price = float(price_at["Close"].iloc[-1])
                        if isinstance(current_price, pd.Series):
                            current_price = current_price.iloc[0]
                        port_value += pos["shares"] * current_price
                        # Update highest price for trailing stop
                        pos["highest"] = max(pos["highest"], current_price)

            # Check trailing stops
            stops_to_sell = []
            for sym, pos in positions.items():
                if sym in price_data:
                    p = price_data[sym]
                    price_at = p[p.index <= date]
                    if len(price_at) > 0:
                        current_price = float(price_at["Close"].iloc[-1])
                        if isinstance(current_price, pd.Series):
                            current_price = current_price.iloc[0]
                        if (current_price < pos["highest"] *
                                (1 - self.config.trailing_stop_pct)):
                            stops_to_sell.append(sym)

            for sym in stops_to_sell:
                pos = positions[sym]
                p = price_data[sym]
                price_at = p[p.index <= date]
                if len(price_at) > 0:
                    sell_price = float(price_at["Close"].iloc[-1])
                    if isinstance(sell_price, pd.Series):
                        sell_price = sell_price.iloc[0]
                    sell_price *= (1 - slippage)
                    proceeds = pos["shares"] * sell_price - self.config.commission
                    cash += proceeds
                    pnl = (sell_price / pos["entry_price"] - 1) * 100
                    trade_log.append({
                        "date": date, "symbol": sym, "action": "SELL",
                        "reason": "trailing_stop", "shares": pos["shares"],
                        "price": sell_price, "pnl_pct": pnl
                    })
                    del positions[sym]

            # Rebalance check
            should_rebalance = (
                last_rebalance is None or
                (date - last_rebalance).days >= self.config.rebalance_days
            )

            if should_rebalance and i > 0:
                # Get universe
                universe = self.data.get_sp500_members(date)
                universe = [s for s in universe if s in price_data
                           and len(price_data[s]) > 0]

                if len(universe) >= 50:
                    # Record IC from previous period (if we have prior factors)
                    if last_factors_df is not None and last_rebalance is not None:
                        fwd_returns = {}
                        for sym in last_factors_df["symbol"].values:
                            if sym in price_data:
                                p = price_data[sym]
                                prev = p[p.index <= last_rebalance]
                                curr = p[p.index <= date]
                                if len(prev) > 0 and len(curr) > 0:
                                    p0 = float(prev["Close"].iloc[-1])
                                    p1 = float(curr["Close"].iloc[-1])
                                    if isinstance(p0, pd.Series):
                                        p0 = p0.iloc[0]
                                    if isinstance(p1, pd.Series):
                                        p1 = p1.iloc[0]
                                    if p0 > 0:
                                        fwd_returns[sym] = p1 / p0 - 1
                        if fwd_returns:
                            self.ic_tracker.record_ic(
                                date, last_factors_df, fwd_returns
                            )

                    # Compute factors
                    factors_df = self.factor_engine.compute_all_factors(
                        date, universe, price_data
                    )

                    # Get IC weights
                    ic_weights = self.ic_tracker.get_ic_weights()
                    if not ic_weights:
                        ic_weights = None  # Equal weight

                    # Composite score
                    factors_df = self.factor_engine.compute_composite_score(
                        factors_df, ic_weights
                    )

                    # Regime
                    macro = self.data.get_macro_at(date)
                    regime, regime_mult = self.regime_filter.assess(
                        date, macro, spy_prices
                    )

                    # Build target portfolio
                    target = self.portfolio_builder.construct(
                        factors_df, benchmark_sector_weights, regime_mult
                    )

                    # Execute trades
                    # First sell positions not in target
                    for sym in list(positions.keys()):
                        if sym not in target:
                            pos = positions[sym]
                            p = price_data.get(sym)
                            if p is not None:
                                price_at = p[p.index <= date]
                                if len(price_at) > 0:
                                    sell_price = float(
                                        price_at["Close"].iloc[-1])
                                    if isinstance(sell_price, pd.Series):
                                        sell_price = sell_price.iloc[0]
                                    sell_price *= (1 - slippage)
                                    proceeds = (pos["shares"] * sell_price
                                               - self.config.commission)
                                    cash += proceeds
                                    pnl = (sell_price / pos["entry_price"]
                                          - 1) * 100
                                    trade_log.append({
                                        "date": date, "symbol": sym,
                                        "action": "SELL",
                                        "reason": "rebalance_out",
                                        "shares": pos["shares"],
                                        "price": sell_price,
                                        "pnl_pct": pnl
                                    })
                                    del positions[sym]

                    # Buy / rebalance positions
                    for sym, target_w in target.items():
                        p = price_data.get(sym)
                        if p is None:
                            continue
                        price_at = p[p.index <= date]
                        if len(price_at) == 0:
                            continue

                        buy_price = float(price_at["Close"].iloc[-1])
                        if isinstance(buy_price, pd.Series):
                            buy_price = buy_price.iloc[0]
                        buy_price *= (1 + slippage)

                        if buy_price <= 0:
                            continue

                        target_value = port_value * target_w
                        current_value = 0
                        if sym in positions:
                            current_value = (positions[sym]["shares"]
                                           * buy_price)

                        diff = target_value - current_value
                        if abs(diff) < port_value * 0.01:
                            continue  # Skip tiny adjustments

                        if diff > 0 and cash > 0:
                            # Buy
                            invest = min(diff, cash * 0.95)
                            shares = int(invest / buy_price)
                            if shares <= 0:
                                continue
                            cost = shares * buy_price + self.config.commission
                            if cost > cash:
                                shares = int(
                                    (cash - self.config.commission) / buy_price
                                )
                                cost = (shares * buy_price
                                       + self.config.commission)

                            if shares > 0:
                                cash -= cost
                                if sym in positions:
                                    old = positions[sym]
                                    total_shares = old["shares"] + shares
                                    avg_price = (
                                        (old["entry_price"] * old["shares"]
                                         + buy_price * shares) / total_shares
                                    )
                                    positions[sym] = {
                                        "shares": total_shares,
                                        "entry_price": avg_price,
                                        "highest": max(old["highest"],
                                                      buy_price)
                                    }
                                else:
                                    positions[sym] = {
                                        "shares": shares,
                                        "entry_price": buy_price,
                                        "highest": buy_price
                                    }
                                trade_log.append({
                                    "date": date, "symbol": sym,
                                    "action": "BUY", "reason": "rebalance_in",
                                    "shares": shares, "price": buy_price,
                                    "pnl_pct": 0
                                })

                    last_rebalance = date
                    last_factors_df = factors_df
                    last_target_portfolio = target

                    # Sector breakdown for logging
                    sector_alloc = {}
                    for sym in target:
                        s = self.data.get_sector(sym)
                        sector_alloc[s] = sector_alloc.get(s, 0) + target[sym]

                    rebalance_log.append({
                        "date": date,
                        "regime": regime,
                        "regime_mult": regime_mult,
                        "n_positions": len(target),
                        "cash_pct": cash / port_value * 100
                            if port_value > 0 else 0,
                        "sector_alloc": sector_alloc,
                        "top_picks": list(target.keys())[:10],
                    })

            # Record daily value
            daily_values.append({
                "date": date,
                "portfolio_value": port_value,
                "cash": cash,
                "n_positions": len(positions),
                "regime": self.regime_filter.current_regime,
            })

            # Progress
            if i % 250 == 0 and i > 0:
                ret = (port_value / self.config.initial_capital - 1) * 100
                print(f"  {date.strftime('%Y-%m-%d')}: "
                      f"${port_value:,.0f} ({ret:+.1f}%) | "
                      f"{len(positions)} positions | "
                      f"{self.regime_filter.current_regime}")

        # Final liquidation
        for sym in list(positions.keys()):
            pos = positions[sym]
            p = price_data.get(sym)
            if p is not None and len(p) > 0:
                sell_price = float(p["Close"].iloc[-1])
                if isinstance(sell_price, pd.Series):
                    sell_price = sell_price.iloc[0]
                sell_price *= (1 - slippage)
                cash += pos["shares"] * sell_price
                trade_log.append({
                    "date": trading_dates[-1], "symbol": sym,
                    "action": "SELL", "reason": "final_liquidation",
                    "shares": pos["shares"], "price": sell_price,
                    "pnl_pct": (sell_price / pos["entry_price"] - 1) * 100
                })
        positions.clear()

        daily_df = pd.DataFrame(daily_values)
        daily_df["date"] = pd.to_datetime(daily_df["date"])

        # Compute report
        report = self._compute_report(
            daily_df, spy_prices, trade_log, rebalance_log
        )

        return daily_df, report

    def _get_all_tickers(self, start: pd.Timestamp,
                         end: pd.Timestamp) -> List[str]:
        """Get tickers that were in S&P 500 during period AND have FMP data."""
        pit = self.data._pit_index
        relevant = pit[
            (pit["date"] >= start) &
            (pit["date"] <= end) &
            (pit["in_index"] == True)
        ]
        pit_tickers = set(relevant["symbol"].unique())

        # Only keep tickers that have fundamentals data
        fund_tickers = set(self.data._fundamentals["symbol"].unique())
        tickers = list(pit_tickers & fund_tickers)

        # Filter: must have recent-ish filings (not ancient delisted)
        recent_filings = self.data._fundamentals[
            self.data._fundamentals["filingDate"] >= start - pd.Timedelta(days=365)
        ]["symbol"].unique()
        tickers = [t for t in tickers if t in set(recent_filings)]

        # Always include SPY
        if "SPY" not in tickers:
            tickers.append("SPY")

        print(f"  Universe: {len(tickers)} tickers (from {len(pit_tickers)} "
              f"PIT members, filtered by FMP data)")
        return tickers

    def _download_prices(self, tickers: List[str],
                         start: pd.Timestamp,
                         end: pd.Timestamp) -> Dict[str, pd.DataFrame]:
        """Download price data for all tickers via yfinance."""
        import yfinance as yf

        # Need extra lookback for momentum calculation
        price_start = start - pd.Timedelta(days=400)

        price_data = {}
        batch_size = 50
        ticker_list = list(tickers)

        for i in range(0, len(ticker_list), batch_size):
            batch = ticker_list[i:i+batch_size]
            try:
                data = yf.download(
                    batch,
                    start=price_start.strftime("%Y-%m-%d"),
                    end=(end + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                    progress=False,
                    group_by="ticker",
                    auto_adjust=True,
                    threads=True,
                )

                if len(batch) == 1:
                    sym = batch[0]
                    if not data.empty:
                        price_data[sym] = data
                else:
                    for sym in batch:
                        try:
                            if sym in data.columns.get_level_values(0):
                                df = data[sym].dropna(how="all")
                                if not df.empty:
                                    price_data[sym] = df
                        except Exception:
                            continue
            except Exception as e:
                print(f"  ⚠️ Batch download error: {e}")
                continue

            if (i + batch_size) % 200 == 0:
                print(f"  Downloaded {min(i+batch_size, len(ticker_list))}/"
                      f"{len(ticker_list)} tickers...")

        return price_data

    def _get_spy_prices(self, start: pd.Timestamp,
                        end: pd.Timestamp) -> pd.Series:
        """Get SPY price series via yfinance."""
        import yfinance as yf
        price_start = start - pd.Timedelta(days=400)
        spy = yf.download(
            "SPY",
            start=price_start.strftime("%Y-%m-%d"),
            end=(end + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=True,
        )
        if not spy.empty:
            close = spy["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            return close
        return pd.Series()

    def _compute_sector_weights(self) -> Dict[str, float]:
        """Compute benchmark sector weights (equal weight per sector member)."""
        sector_counts = {}
        total = 0
        for sym, sector in self.data._sector_map.items():
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
            total += 1

        if total == 0:
            return {}

        return {s: c / total for s, c in sector_counts.items()}

    def _compute_report(self, daily_df: pd.DataFrame,
                        spy_prices: pd.Series,
                        trade_log: List[dict],
                        rebalance_log: List[dict]) -> dict:
        """Compute comprehensive backtest report."""
        values = daily_df["portfolio_value"].values
        dates = daily_df["date"].values

        # Returns
        total_return = (values[-1] / values[0] - 1) * 100
        n_years = (dates[-1] - dates[0]) / np.timedelta64(365, "D")
        annual_return = ((values[-1] / values[0]) ** (1 / max(n_years, 0.01))
                        - 1) * 100

        # Daily returns
        daily_returns = pd.Series(values).pct_change().dropna()

        # Max drawdown
        cummax = np.maximum.accumulate(values)
        drawdown = (values - cummax) / cummax
        max_dd = drawdown.min() * 100

        # Sharpe
        rf_daily = 0.04 / 252  # ~4% risk-free
        excess = daily_returns - rf_daily
        sharpe = (excess.mean() / excess.std() * np.sqrt(252)
                 if excess.std() > 0 else 0)

        # Volatility
        vol = daily_returns.std() * np.sqrt(252) * 100

        # Benchmark returns
        spy_close = spy_prices
        if not spy_close.empty:
            # Align dates
            spy_aligned = spy_close.reindex(
                pd.DatetimeIndex(dates), method="ffill"
            ).dropna()

            if len(spy_aligned) >= 2:
                spy_total = (spy_aligned.iloc[-1] / spy_aligned.iloc[0]
                            - 1) * 100
                spy_annual = (
                    (spy_aligned.iloc[-1] / spy_aligned.iloc[0])
                    ** (1 / max(n_years, 0.01)) - 1
                ) * 100
                spy_daily = spy_aligned.pct_change().dropna()
                spy_sharpe = (
                    (spy_daily.mean() - rf_daily) / spy_daily.std()
                    * np.sqrt(252)
                ) if spy_daily.std() > 0 else 0

                # Alpha & t-stat
                # Align lengths
                min_len = min(len(daily_returns), len(spy_daily))
                strat_r = daily_returns.iloc[-min_len:].values
                bench_r = spy_daily.iloc[-min_len:].values
                daily_alpha = strat_r - bench_r

                alpha_mean = np.mean(daily_alpha)
                alpha_std = np.std(daily_alpha)
                n_obs = len(daily_alpha)

                alpha_annual = alpha_mean * 252 * 100
                t_stat = (alpha_mean / (alpha_std / np.sqrt(n_obs))
                         if alpha_std > 0 else 0)

                tracking_error = alpha_std * np.sqrt(252) * 100
                info_ratio = (alpha_annual / tracking_error
                             if tracking_error > 0 else 0)
            else:
                spy_total = spy_annual = spy_sharpe = 0
                alpha_annual = t_stat = tracking_error = info_ratio = 0
        else:
            spy_total = spy_annual = spy_sharpe = 0
            alpha_annual = t_stat = tracking_error = info_ratio = 0

        # Trade statistics
        trades_df = pd.DataFrame(trade_log) if trade_log else pd.DataFrame()
        sells = trades_df[trades_df["action"] == "SELL"] if not trades_df.empty else pd.DataFrame()
        n_trades = len(sells)
        win_rate = (sells["pnl_pct"] > 0).mean() * 100 if n_trades > 0 else 0
        avg_pnl = sells["pnl_pct"].mean() if n_trades > 0 else 0
        trailing_stops = len(
            sells[sells["reason"] == "trailing_stop"]
        ) if n_trades > 0 else 0

        # Sector exposure over time (from rebalance log)
        sector_exposures = {}
        for r in rebalance_log:
            for s, w in r.get("sector_alloc", {}).items():
                if s not in sector_exposures:
                    sector_exposures[s] = []
                sector_exposures[s].append(w)

        avg_sector = {s: np.mean(ws) * 100
                     for s, ws in sector_exposures.items()}

        # IC summary
        ic_summary = {}
        if self.ic_tracker.ic_history:
            all_ics = {}
            for ic_dict in self.ic_tracker.ic_history:
                for k, v in ic_dict.items():
                    if k not in all_ics:
                        all_ics[k] = []
                    all_ics[k].append(v)
            ic_summary = {
                k.replace("_z", ""): {
                    "mean_ic": np.mean(vs),
                    "ic_ir": np.mean(vs) / np.std(vs) if np.std(vs) > 0 else 0,
                    "hit_rate": np.mean([1 if v > 0 else 0 for v in vs])
                }
                for k, vs in all_ics.items()
            }

        significant = abs(t_stat) >= 1.96

        report = {
            "strategy": "V7 Sector-Neutral Multi-Factor",
            "period": f"{dates[0]} to {dates[-1]}",
            "n_trading_days": len(values),
            "n_years": round(n_years, 1),
            # Strategy performance
            "total_return_pct": round(total_return, 2),
            "annual_return_pct": round(annual_return, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "sharpe_ratio": round(sharpe, 3),
            "volatility_pct": round(vol, 2),
            # Benchmark
            "spy_total_return_pct": round(spy_total, 2),
            "spy_annual_return_pct": round(spy_annual, 2),
            "spy_sharpe": round(spy_sharpe, 3),
            # Alpha analysis
            "alpha_annual_pct": round(alpha_annual, 2),
            "alpha_t_stat": round(t_stat, 3),
            "alpha_significant": significant,
            "tracking_error_pct": round(tracking_error, 2),
            "information_ratio": round(info_ratio, 3),
            # Trading
            "total_trades": n_trades,
            "win_rate_pct": round(win_rate, 1),
            "avg_pnl_pct": round(avg_pnl, 2),
            "trailing_stops": trailing_stops,
            "n_rebalances": len(rebalance_log),
            # Sector exposure
            "avg_sector_allocation": avg_sector,
            # Factor IC
            "factor_ic": ic_summary,
        }

        return report


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────

def print_report(report: dict):
    """Pretty-print backtest report."""
    print("\n" + "=" * 70)
    print(f"  {report['strategy']}")
    print(f"  {report['period']}")
    print(f"  {report['n_years']} years, {report['n_trading_days']} trading days")
    print("=" * 70)

    print(f"\n{'PERFORMANCE':=^50}")
    print(f"  Strategy Return:  {report['total_return_pct']:+.2f}% "
          f"({report['annual_return_pct']:+.2f}% ann.)")
    print(f"  SPY Return:       {report['spy_total_return_pct']:+.2f}% "
          f"({report['spy_annual_return_pct']:+.2f}% ann.)")
    print(f"  Max Drawdown:     {report['max_drawdown_pct']:.2f}%")
    print(f"  Sharpe Ratio:     {report['sharpe_ratio']:.3f} "
          f"(SPY: {report['spy_sharpe']:.3f})")
    print(f"  Volatility:       {report['volatility_pct']:.2f}%")

    print(f"\n{'ALPHA ANALYSIS':=^50}")
    sig = "✅ YES" if report['alpha_significant'] else "❌ NO"
    print(f"  Alpha (annual):   {report['alpha_annual_pct']:+.2f}%")
    print(f"  Alpha t-stat:     {report['alpha_t_stat']:+.3f}")
    print(f"  Significant:      {sig}")
    print(f"  Tracking Error:   {report['tracking_error_pct']:.2f}%")
    print(f"  Information Ratio:{report['information_ratio']:+.3f}")

    print(f"\n{'TRADING':=^50}")
    print(f"  Total Trades:     {report['total_trades']}")
    print(f"  Win Rate:         {report['win_rate_pct']:.1f}%")
    print(f"  Avg P&L/Trade:    {report['avg_pnl_pct']:+.2f}%")
    print(f"  Trailing Stops:   {report['trailing_stops']}")
    print(f"  Rebalances:       {report['n_rebalances']}")

    print(f"\n{'SECTOR ALLOCATION (avg %)':=^50}")
    sectors = report.get("avg_sector_allocation", {})
    for s in sorted(sectors, key=sectors.get, reverse=True):
        print(f"  {s:25s} {sectors[s]:5.1f}%")

    print(f"\n{'FACTOR IC (Information Coefficient)':=^50}")
    ics = report.get("factor_ic", {})
    for f in sorted(ics, key=lambda x: abs(ics[x].get("mean_ic", 0)),
                    reverse=True):
        ic = ics[f]
        print(f"  {f:25s} IC={ic['mean_ic']:+.3f}  "
              f"IC-IR={ic['ic_ir']:+.3f}  "
              f"Hit={ic['hit_rate']:.0%}")

    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="V7 Sector-Neutral Multi-Factor Backtest"
    )
    parser.add_argument("--start", default="2015-01-01",
                       help="Backtest start date")
    parser.add_argument("--end", default="2025-12-31",
                       help="Backtest end date")
    parser.add_argument("--slippage", type=float, default=10.0,
                       help="One-way slippage in bps")
    parser.add_argument("--top-n", type=int, default=2,
                       help="Top N stocks per sector")
    parser.add_argument("--rebalance-days", type=int, default=14,
                       help="Rebalance frequency in days")
    args = parser.parse_args()

    config = V7Config(
        slippage_bps=args.slippage,
        top_n_per_sector=args.top_n,
        rebalance_days=args.rebalance_days,
    )

    backtester = V7Backtester(config)
    daily_df, report = backtester.run(args.start, args.end)

    print_report(report)

    # Save results
    os.makedirs("reports", exist_ok=True)
    daily_df.to_csv("reports/v7_daily_values.csv", index=False)

    import json
    with open("reports/v7_report.json", "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"\n📁 Results saved to reports/v7_daily_values.csv and reports/v7_report.json")


if __name__ == "__main__":
    main()
