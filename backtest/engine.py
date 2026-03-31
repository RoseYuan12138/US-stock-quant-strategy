"""Backtester - Strategy-agnostic backtesting engine."""

import os
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from config import FMP_CACHE, V7Config
from data.fmp_loader import FMPDataLoader
from strategy.base import StrategyBase


class Backtester:
    """Generic backtesting engine. Accepts any StrategyBase implementation."""

    def __init__(self, strategy: StrategyBase, config: V7Config):
        self.strategy = strategy
        self.config = config
        self.data = FMPDataLoader()

    def run(self, start_date: str = "2015-01-01",
            end_date: str = "2025-12-31") -> Tuple[pd.DataFrame, dict]:
        """Run full backtest."""
        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date)

        # Load data
        self.data.load_all()

        # Load price data
        print("📈 Loading price data...")
        all_tickers = self._get_all_tickers(start, end)
        price_data = self._load_prices(all_tickers, start, end)
        spy_prices = self._get_spy_prices(start, end)
        print(f"  Prices: {len(price_data)} tickers loaded\n")

        # Initialize strategy
        self.strategy.initialize(self.data, price_data, spy_prices)

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
        positions: Dict[str, dict] = {}
        daily_values = []
        trade_log = []
        rebalance_log = []
        last_rebalance = None
        last_factors_df = None

        total_days = len(trading_dates)
        print(f"🔄 Running backtest... ({total_days} trading days)")
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
                universe = self.data.get_sp500_members(date)
                universe = [s for s in universe if s in price_data
                           and len(price_data[s]) > 0]

                if len(universe) >= 50:
                    # Call strategy
                    target, factors_df = self.strategy.on_rebalance(
                        date, universe, last_rebalance, last_factors_df
                    )

                    # Execute trades - sell positions not in target
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
                            continue

                        if diff > 0 and cash > 0:
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

                    # Sector breakdown for logging
                    sector_alloc = {}
                    for sym in target:
                        s = self.data.get_sector(sym)
                        sector_alloc[s] = sector_alloc.get(s, 0) + target[sym]

                    rebalance_log.append({
                        "date": date,
                        "regime": self.strategy.get_regime(),
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
                "regime": self.strategy.get_regime(),
            })

            # Progress bar - update every 50 days
            if i % 50 == 0 or i == total_days - 1:
                pct = (i + 1) / total_days
                bar_len = 30
                filled = int(bar_len * pct)
                bar = "█" * filled + "░" * (bar_len - filled)
                ret = (port_value / self.config.initial_capital - 1) * 100
                print(f"\r  [{bar}] {pct:5.1%} | "
                      f"{date.strftime('%Y-%m-%d')} | "
                      f"${port_value:,.0f} ({ret:+.1f}%) | "
                      f"{len(positions)} pos | "
                      f"{self.strategy.get_regime()}    ",
                      end="", flush=True)

            # Yearly milestone log
            if i % 252 == 0 and i > 0:
                ret = (port_value / self.config.initial_capital - 1) * 100
                print(f"\n  📅 {date.strftime('%Y-%m-%d')}: "
                      f"${port_value:,.0f} ({ret:+.1f}%) | "
                      f"{len(positions)} positions | "
                      f"{self.strategy.get_regime()}")

        print()  # newline after progress bar

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

        fund_tickers = set(self.data._fundamentals["symbol"].unique())
        tickers = list(pit_tickers & fund_tickers)

        recent_filings = self.data._fundamentals[
            self.data._fundamentals["filingDate"] >= start - pd.Timedelta(days=365)
        ]["symbol"].unique()
        tickers = [t for t in tickers if t in set(recent_filings)]

        if "SPY" not in tickers:
            tickers.append("SPY")

        print(f"  Universe: {len(tickers)} tickers (from {len(pit_tickers)} "
              f"PIT members, filtered by FMP data)")
        return tickers

    def _load_prices(self, tickers: List[str],
                     start: pd.Timestamp,
                     end: pd.Timestamp) -> Dict[str, pd.DataFrame]:
        """Load price data for all tickers from FMP parquet cache."""
        price_start = start - pd.Timedelta(days=400)

        prices_dir = os.path.join(FMP_CACHE, "prices")
        price_data = {}

        for sym in tickers:
            path = os.path.join(prices_dir, f"{sym}.parquet")
            if not os.path.exists(path):
                continue
            try:
                df = pd.read_parquet(path)
                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date").sort_index()
                df.columns = [c.capitalize() for c in df.columns]
                df = df.loc[price_start:end]
                if not df.empty:
                    price_data[sym] = df
            except Exception as e:
                print(f"  ⚠️ Failed to load {sym}: {e}")
                continue

        return price_data

    def _get_spy_prices(self, start: pd.Timestamp,
                        end: pd.Timestamp) -> pd.Series:
        """Get SPY price series from FMP parquet cache."""
        price_start = start - pd.Timedelta(days=400)
        path = os.path.join(FMP_CACHE, "prices", "SPY.parquet")
        if not os.path.exists(path):
            return pd.Series()
        try:
            df = pd.read_parquet(path)
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").sort_index()
            df = df.loc[price_start:end]
            return df["close"].rename(None) if not df.empty else pd.Series()
        except Exception as e:
            print(f"  ⚠️ Failed to load SPY: {e}")
            return pd.Series()

    def _compute_report(self, daily_df: pd.DataFrame,
                        spy_prices: pd.Series,
                        trade_log: List[dict],
                        rebalance_log: List[dict]) -> dict:
        """Compute comprehensive backtest report."""
        values = daily_df["portfolio_value"].values
        dates = daily_df["date"].values

        total_return = (values[-1] / values[0] - 1) * 100
        n_years = (dates[-1] - dates[0]) / np.timedelta64(365, "D")
        annual_return = ((values[-1] / values[0]) ** (1 / max(n_years, 0.01))
                        - 1) * 100

        daily_returns = pd.Series(values).pct_change().dropna()

        cummax = np.maximum.accumulate(values)
        drawdown = (values - cummax) / cummax
        max_dd = drawdown.min() * 100

        rf_daily = 0.04 / 252
        excess = daily_returns - rf_daily
        sharpe = (excess.mean() / excess.std() * np.sqrt(252)
                 if excess.std() > 0 else 0)

        vol = daily_returns.std() * np.sqrt(252) * 100

        # Benchmark
        spy_close = spy_prices
        if not spy_close.empty:
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

        # Sector exposure
        sector_exposures = {}
        for r in rebalance_log:
            for s, w in r.get("sector_alloc", {}).items():
                if s not in sector_exposures:
                    sector_exposures[s] = []
                sector_exposures[s].append(w)

        avg_sector = {s: np.mean(ws) * 100
                     for s, ws in sector_exposures.items()}

        # Strategy diagnostics (factor IC, etc.)
        diagnostics = self.strategy.get_diagnostics()

        significant = abs(t_stat) >= 1.96

        return {
            "strategy": self.strategy.name,
            "period": f"{dates[0]} to {dates[-1]}",
            "n_trading_days": len(values),
            "n_years": round(n_years, 1),
            "total_return_pct": round(total_return, 2),
            "annual_return_pct": round(annual_return, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "sharpe_ratio": round(sharpe, 3),
            "volatility_pct": round(vol, 2),
            "spy_total_return_pct": round(spy_total, 2),
            "spy_annual_return_pct": round(spy_annual, 2),
            "spy_sharpe": round(spy_sharpe, 3),
            "alpha_annual_pct": round(alpha_annual, 2),
            "alpha_t_stat": round(t_stat, 3),
            "alpha_significant": significant,
            "tracking_error_pct": round(tracking_error, 2),
            "information_ratio": round(info_ratio, 3),
            "total_trades": n_trades,
            "win_rate_pct": round(win_rate, 1),
            "avg_pnl_pct": round(avg_pnl, 2),
            "trailing_stops": trailing_stops,
            "n_rebalances": len(rebalance_log),
            "avg_sector_allocation": avg_sector,
            **diagnostics,
        }


# Backward compatibility alias
V7Backtester = Backtester
