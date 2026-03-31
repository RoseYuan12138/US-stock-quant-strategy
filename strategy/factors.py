"""Factor Engine - Cross-sectional factor z-score construction."""

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from config import V7Config
from data.fmp_loader import FMPDataLoader


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
            accruals = -(net_income - ocf) / total_assets

        return {"accruals": accruals}

    def _momentum_factors(self, prices: pd.DataFrame,
                          date: pd.Timestamp) -> dict:
        """Compute momentum factors from price history."""
        p = prices[prices.index <= date]["Close"]
        if isinstance(p, pd.DataFrame):
            p = p.iloc[:, 0]

        result = {"mom_6m": np.nan, "mom_1m_rev": np.nan, "mom_12m_skip1": np.nan}

        if len(p) < 22:
            return result

        current = p.iloc[-1]

        # 6-month momentum (skip last 1 month for reversal)
        if len(p) >= 147:
            price_6m_ago = p.iloc[-147]
            price_1m_ago = p.iloc[-22]
            if price_6m_ago > 0:
                result["mom_6m"] = (price_1m_ago / price_6m_ago) - 1.0

        # 1-month reversal (short-term mean reversion, flipped)
        if len(p) >= 22:
            price_1m_ago = p.iloc[-22]
            if price_1m_ago > 0:
                result["mom_1m_rev"] = -(current / price_1m_ago - 1.0)

        # 12-month skip-1-month momentum
        if len(p) >= 273:
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

        surprises = []
        for _, row in earnings.iterrows():
            actual = row.get("epsActual", np.nan)
            estimated = row.get("epsEstimated", np.nan)
            if pd.notna(actual) and pd.notna(estimated) and estimated != 0:
                surprises.append(actual - estimated)

        if len(surprises) < 2:
            return np.nan

        std_surprise = np.std(surprises)
        if std_surprise < 0.001:
            std_surprise = 0.001

        latest_surprise = surprises[-1]
        sue = latest_surprise / std_surprise

        # Apply time decay
        last_date = earnings["date"].iloc[-1]
        days_since = (date - last_date).days
        decay = np.exp(-days_since / self.config.factor_decay_days)

        return sue * decay

    def _analyst_revision(self, symbol: str, date: pd.Timestamp,
                          analyst_grades: pd.DataFrame) -> float:
        """Analyst revision momentum: change in consensus over recent months."""
        if analyst_grades.empty or symbol not in analyst_grades.index:
            return np.nan

        if self.data._analyst_grades.empty:
            return np.nan

        sym_grades = self.data._analyst_grades[
            (self.data._analyst_grades["symbol"] == symbol) &
            (self.data._analyst_grades["date"] <= date) &
            (self.data._analyst_grades["date"] >= date - pd.Timedelta(days=180))
        ].sort_values("date")

        if len(sym_grades) < 2:
            return np.nan

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

        return latest - earliest

    def _insider_factor(self, symbol: str, date: pd.Timestamp) -> float:
        """Insider trading signal based on dollar value of purchases."""
        trades = self.data.get_insider_trades(symbol, date, lookback_days=180)
        if trades.empty:
            return 0.0

        net_value = 0.0
        for _, t in trades.iterrows():
            shares = t.get("securitiesTransacted", 0) or 0
            price = t.get("price", 0) or 0
            disposition = t.get("acquisitionOrDisposition", "")
            tx_type = t.get("transactionType", "")

            if tx_type in ["F-InKind", "G-Gift", "W-Will"]:
                continue

            value = shares * price
            if disposition == "A":
                net_value += value
            elif disposition == "D":
                net_value -= value

        return net_value / 1_000_000

    def _congressional_factor(self, symbol: str,
                               date: pd.Timestamp) -> float:
        """Congressional trading signal."""
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
            ic_weights = {c: 1.0 for c in z_cols}

        total_w = sum(abs(v) for v in ic_weights.values()) or 1.0
        norm_weights = {k: v / total_w for k, v in ic_weights.items()}

        composite = pd.Series(0.0, index=factors_df.index)
        n_factors = pd.Series(0, index=factors_df.index)

        for col in z_cols:
            w = norm_weights.get(col, 0.0)
            valid = factors_df[col].notna()
            composite[valid] += factors_df.loc[valid, col] * w
            n_factors[valid] += 1

        min_factors = max(1, len(z_cols) // 2)
        composite[n_factors < min_factors] = np.nan

        factors_df = factors_df.copy()
        factors_df["composite_z"] = composite
        return factors_df
