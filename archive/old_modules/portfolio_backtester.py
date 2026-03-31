"""
组合级回测引擎
模拟真实的多标的组合操作：月度选股 → 等权建仓 → trailing stop → 再平衡

与单标的回测的关键区别：
- 同时持有多只股票
- 月度/季度再平衡
- 仓位管理（等权重、单只上限）
- 市场环境调整总仓位
- Trailing stop 替代固定止盈
- SPY 底仓

前视偏差处理：
- 基本面评分用"截至当月"的数据（模拟只用已知信息）
- 动量评分用历史价格计算（无前视偏差）
"""

import numpy as np
import pandas as pd
import logging
from datetime import datetime
from typing import Dict, List, Optional

from strategy.momentum import MomentumScorer
from strategy.regime_filter import RegimeFilter
from strategy.portfolio_strategy import PortfolioConfig, PortfolioStrategy, Position
from data.historical_fundamentals import HistoricalFundamentalFetcher
from strategy.earnings_surprise import EarningsSurpriseScorer

logger = logging.getLogger(__name__)


class PortfolioBacktester:
    """
    组合级回测引擎

    流程：
    1. 逐日遍历
    2. 每月初（或季度初）做再平衡：
       a. 用截至当前的价格数据计算动量评分
       b. 用基本面评分（注意前视偏差说明）
       c. 综合评分选 Top N
       d. 检查市场环境，调整总仓位
       e. 卖出不在新名单中的股票，买入新进的股票
    3. 每日检查 trailing stop
    4. 记录每日组合价值
    """

    def __init__(self, config: PortfolioConfig = None):
        self.config = config or PortfolioConfig()
        self.strategy = PortfolioStrategy(self.config)
        self.momentum_scorer = MomentumScorer()
        self.regime_filter = RegimeFilter()
        self.hist_fundamental_fetcher = HistoricalFundamentalFetcher()
        self.earnings_scorer = EarningsSurpriseScorer()

    def _apply_slippage(self, price, action):
        """应用滑点：买入价格偏高，卖出价格偏低"""
        slippage = self.config.slippage_bps / 10000
        if action == 'BUY':
            return price * (1 + slippage)
        else:  # SELL
            return price * (1 - slippage)

    def run(self, price_data_dict, fundamental_scores, benchmark_data,
            start_date='2023-01-01', end_date='2025-12-31',
            use_historical_fundamentals=False, macro_data=None,
            short_interest=None, insider_scorer=None,
            news_provider=None):
        """
        执行组合回测

        Args:
            price_data_dict: {ticker: DataFrame} 所有候选股票的价格数据
            fundamental_scores: {ticker: {'total_score': float, 'analyst_score': float, ...}}
                静态评分（use_historical_fundamentals=False 时使用）
            benchmark_data: SPY 价格数据 DataFrame
            start_date: 回测开始日期
            end_date: 回测结束日期
            use_historical_fundamentals: 是否使用历史季度财报评分（修复前视偏差）
            macro_data: dict of DataFrames，跨资产宏观数据（可选）
                {'tnx': df, 'irx': df, 'vix': df, 'hyg': df, 'lqd': df}
            short_interest: dict {ticker: float} short percent of float（可选）
            insider_scorer: InsiderSignalScorer instance（可选）

        Returns:
            (daily_values_df, report_dict, trade_log)
        """
        self.use_historical_fundamentals = use_historical_fundamentals
        self.short_interest = short_interest
        self.insider_scorer = insider_scorer
        self.news_provider = news_provider
        # 初始化
        cash = self.config.initial_cash
        positions: Dict[str, Position] = {}  # {ticker: Position}
        spy_position: Optional[Position] = None  # SPY 底仓

        trade_log = []
        daily_values = []
        rebalance_log = []
        last_rebalance_date = None

        # 获取交易日历（用 SPY 的日期）
        if benchmark_data is None or len(benchmark_data) == 0:
            logger.error("基准数据为空")
            return None, None, None

        trading_dates = benchmark_data.loc[start_date:end_date].index

        if len(trading_dates) == 0:
            logger.error(f"日期范围 {start_date}~{end_date} 内无交易日")
            return None, None, None

        # 市场环境序列（传入跨资产宏观数据）
        regime_series = self.regime_filter.get_regime_series(benchmark_data, macro_data=macro_data)

        # 逐日模拟
        for date in trading_dates:
            # 1. 检查是否需要再平衡
            if self.strategy.should_rebalance(date, last_rebalance_date):
                cash, positions, spy_position = self._rebalance(
                    date, cash, positions, spy_position,
                    price_data_dict, fundamental_scores, benchmark_data,
                    regime_series, trade_log, rebalance_log
                )
                last_rebalance_date = date

            # 2. 每日检查 trailing stop
            tickers_to_sell = []
            for ticker, pos in positions.items():
                if ticker in price_data_dict and date in price_data_dict[ticker].index:
                    current_price = price_data_dict[ticker].loc[date, 'Close']

                    # 更新最高价
                    if current_price > pos.highest_price:
                        pos.highest_price = current_price

                    # 检查 trailing stop
                    if self.strategy.check_trailing_stop(pos, current_price):
                        tickers_to_sell.append((ticker, current_price, 'TRAILING_STOP'))

            # 执行 trailing stop 卖出
            for ticker, price, reason in tickers_to_sell:
                pos = positions[ticker]
                sell_price = self._apply_slippage(price, 'SELL')
                revenue = pos.shares * sell_price - self.config.commission
                profit = revenue - pos.cost_basis
                cash += revenue

                trade_log.append({
                    'date': date, 'ticker': ticker, 'action': 'SELL',
                    'reason': reason, 'shares': pos.shares, 'price': price,
                    'profit': profit,
                    'profit_pct': (price - pos.entry_price) / pos.entry_price * 100,
                    'hold_days': (date - pos.entry_date).days,
                })

                del positions[ticker]

            # 3. 记录每日组合价值
            portfolio_value = cash
            for ticker, pos in positions.items():
                if ticker in price_data_dict and date in price_data_dict[ticker].index:
                    portfolio_value += pos.shares * price_data_dict[ticker].loc[date, 'Close']
                else:
                    portfolio_value += pos.shares * pos.entry_price  # 用入场价兜底

            if spy_position and date in benchmark_data.index:
                portfolio_value += spy_position.shares * benchmark_data.loc[date, 'Close']

            daily_values.append({
                'date': date,
                'portfolio_value': portfolio_value,
                'cash': cash,
                'n_positions': len(positions),
                'regime': regime_series.loc[date, 'regime'] if regime_series is not None and date in regime_series.index else 'BULL',
            })

        # 回测结束，强制平仓
        last_date = trading_dates[-1]
        for ticker, pos in list(positions.items()):
            if ticker in price_data_dict and last_date in price_data_dict[ticker].index:
                price = price_data_dict[ticker].loc[last_date, 'Close']
            else:
                price = pos.entry_price
            revenue = pos.shares * price - self.config.commission
            profit = revenue - pos.cost_basis
            cash += revenue
            trade_log.append({
                'date': last_date, 'ticker': ticker, 'action': 'SELL',
                'reason': 'BACKTEST_END', 'shares': pos.shares, 'price': price,
                'profit': profit,
                'profit_pct': (price - pos.entry_price) / pos.entry_price * 100,
                'hold_days': (last_date - pos.entry_date).days,
            })
        positions.clear()

        if spy_position and last_date in benchmark_data.index:
            spy_price = benchmark_data.loc[last_date, 'Close']
            revenue = spy_position.shares * spy_price - self.config.commission
            cash += revenue
            trade_log.append({
                'date': last_date, 'ticker': 'SPY', 'action': 'SELL',
                'reason': 'BACKTEST_END', 'shares': spy_position.shares, 'price': spy_price,
            })
            spy_position = None

        # 更新最后一天的价值
        if daily_values:
            daily_values[-1]['portfolio_value'] = cash

        # 生成报告
        daily_df = pd.DataFrame(daily_values).set_index('date')
        report = self._generate_report(daily_df, benchmark_data, trade_log, rebalance_log)

        return daily_df, report, trade_log

    def _rebalance(self, date, cash, positions, spy_position,
                   price_data_dict, fundamental_scores, benchmark_data,
                   regime_series, trade_log, rebalance_log):
        """
        执行月度再平衡

        Returns:
            (cash, positions, spy_position)
        """
        # 计算当前组合总价值
        total_value = cash
        for ticker, pos in positions.items():
            if ticker in price_data_dict and date in price_data_dict[ticker].index:
                total_value += pos.shares * price_data_dict[ticker].loc[date, 'Close']
            else:
                total_value += pos.shares * pos.entry_price

        if spy_position and date in benchmark_data.index:
            total_value += spy_position.shares * benchmark_data.loc[date, 'Close']

        # 1. 计算动量评分（用截至当前日期的数据，无前视偏差）
        momentum_scores = {}
        for ticker, data in price_data_dict.items():
            historical = data.loc[:date]
            if len(historical) > 0:
                mom = self.momentum_scorer.calculate_momentum(historical)
                if mom is not None:
                    momentum_scores[ticker] = mom

        # 2. 获取基本面评分（历史模式 or 静态模式）
        if self.use_historical_fundamentals:
            current_fundamentals = {}
            for ticker in price_data_dict.keys():
                hist_score = self.hist_fundamental_fetcher.get_score_at_date(ticker, date)
                if hist_score is not None:
                    current_fundamentals[ticker] = {
                        'total_score': hist_score['score'],
                        'analyst_score': hist_score['score'],  # 历史模式无单独分析师分
                    }
                elif ticker in fundamental_scores:
                    # fallback: 没有历史数据的用静态评分
                    current_fundamentals[ticker] = fundamental_scores[ticker]
            fund_scores_for_selection = current_fundamentals
        else:
            fund_scores_for_selection = fundamental_scores

        # 2.5 Earnings surprise 调整基本面评分
        for ticker in list(fund_scores_for_selection.keys()):
            es = self.earnings_scorer.score_at_date(ticker, date)
            if es.get('data_available'):
                # 用 earnings surprise 调整基本面分：原分 80% + earnings 20%
                orig = fund_scores_for_selection[ticker]['total_score']
                adjusted = orig * 0.8 + es['earnings_score'] * 0.2
                fund_scores_for_selection[ticker] = dict(fund_scores_for_selection[ticker])
                fund_scores_for_selection[ticker]['total_score'] = adjusted

        # 2.7 Insider Trading 评分
        insider_scores = None
        if self.insider_scorer:
            insider_scores = self.insider_scorer.score_universe(
                list(fund_scores_for_selection.keys()), date
            )

        # 2.9 新闻情绪评分
        news_scores = None
        if self.news_provider:
            news_scores = self.news_provider.score_universe(
                list(fund_scores_for_selection.keys()), date
            )

        # 3. 选股（含 short interest 过滤 + insider 加分 + 新闻情绪）
        selected = self.strategy.select_stocks(
            fund_scores_for_selection, momentum_scores,
            short_interest=self.short_interest,
            insider_scores=insider_scores,
            news_scores=news_scores,
        )

        # 3. 市场环境调整
        position_multiplier = 1.0
        current_regime = 'BULL'
        if self.config.use_regime_filter and regime_series is not None and date in regime_series.index:
            position_multiplier = regime_series.loc[date, 'position_multiplier']
            current_regime = regime_series.loc[date, 'regime']

        rebalance_log.append({
            'date': date,
            'regime': current_regime,
            'multiplier': position_multiplier,
            'selected': [s['ticker'] for s in selected],
            'scores': {s['ticker']: s['combined_score'] for s in selected},
            'total_value': total_value,
        })

        # 4. 卖出不在新名单中的持仓
        selected_tickers = {s['ticker'] for s in selected}
        for ticker in list(positions.keys()):
            if ticker not in selected_tickers:
                pos = positions[ticker]
                if ticker in price_data_dict and date in price_data_dict[ticker].index:
                    price = self._apply_slippage(price_data_dict[ticker].loc[date, 'Close'], 'SELL')
                else:
                    price = pos.entry_price

                revenue = pos.shares * price - self.config.commission
                profit = revenue - pos.cost_basis
                cash += revenue

                trade_log.append({
                    'date': date, 'ticker': ticker, 'action': 'SELL',
                    'reason': 'REBALANCE_OUT', 'shares': pos.shares, 'price': price,
                    'profit': profit,
                    'profit_pct': (price - pos.entry_price) / pos.entry_price * 100,
                    'hold_days': (date - pos.entry_date).days,
                })
                del positions[ticker]

        # 卖出旧 SPY 仓位（准备重建）
        if spy_position and date in benchmark_data.index:
            spy_price = self._apply_slippage(benchmark_data.loc[date, 'Close'], 'SELL')
            cash += spy_position.shares * spy_price - self.config.commission
            spy_position = None

        # 5. 重新计算目标仓位并建仓
        # SPY 底仓
        spy_target = total_value * self.config.spy_base_weight * position_multiplier
        if date in benchmark_data.index:
            spy_price = self._apply_slippage(benchmark_data.loc[date, 'Close'], 'BUY')
            spy_shares = int(spy_target / spy_price)
            if spy_shares > 0 and cash >= spy_shares * spy_price + self.config.commission:
                cost = spy_shares * spy_price + self.config.commission
                cash -= cost
                spy_position = Position(
                    ticker='SPY', shares=spy_shares, entry_price=spy_price,
                    entry_date=date, highest_price=spy_price, cost_basis=cost,
                )

        # 个股仓位
        for stock in selected:
            ticker = stock['ticker']
            target_weight = stock['weight'] * position_multiplier
            target_value = total_value * target_weight

            if ticker not in price_data_dict or date not in price_data_dict[ticker].index:
                continue

            raw_price = price_data_dict[ticker].loc[date, 'Close']

            if ticker in positions:
                # 已持有：检查是否需要调仓
                pos = positions[ticker]
                current_value = pos.shares * raw_price
                diff = target_value - current_value

                if abs(diff) > total_value * 0.02:  # 偏差超过2%才调仓
                    # 卖出旧仓位
                    sell_price = self._apply_slippage(raw_price, 'SELL')
                    revenue = pos.shares * sell_price - self.config.commission
                    profit = revenue - pos.cost_basis
                    cash += revenue
                    trade_log.append({
                        'date': date, 'ticker': ticker, 'action': 'SELL',
                        'reason': 'REBALANCE_ADJUST', 'shares': pos.shares, 'price': sell_price,
                        'profit': profit,
                        'profit_pct': (sell_price - pos.entry_price) / pos.entry_price * 100,
                        'hold_days': (date - pos.entry_date).days,
                    })

                    # 重新买入目标仓位
                    buy_price = self._apply_slippage(raw_price, 'BUY')
                    shares = int(target_value / buy_price)
                    if shares > 0 and cash >= shares * buy_price + self.config.commission:
                        cost = shares * buy_price + self.config.commission
                        cash -= cost
                        positions[ticker] = Position(
                            ticker=ticker, shares=shares, entry_price=buy_price,
                            entry_date=date, highest_price=buy_price,
                            combined_score=stock['combined_score'], cost_basis=cost,
                        )
                        trade_log.append({
                            'date': date, 'ticker': ticker, 'action': 'BUY',
                            'reason': 'REBALANCE_ADJUST', 'shares': shares, 'price': buy_price,
                            'combined_score': stock['combined_score'],
                        })
                # 偏差小于2%：不动，节省佣金
            else:
                # 新建仓
                buy_price = self._apply_slippage(raw_price, 'BUY')
                shares = int(target_value / buy_price)
                if shares > 0 and cash >= shares * buy_price + self.config.commission:
                    cost = shares * buy_price + self.config.commission
                    cash -= cost
                    positions[ticker] = Position(
                        ticker=ticker, shares=shares, entry_price=buy_price,
                        entry_date=date, highest_price=buy_price,
                        combined_score=stock['combined_score'], cost_basis=cost,
                    )
                    trade_log.append({
                        'date': date, 'ticker': ticker, 'action': 'BUY',
                        'reason': 'REBALANCE_NEW', 'shares': shares, 'price': buy_price,
                        'combined_score': stock['combined_score'],
                    })

        return cash, positions, spy_position

    def _generate_report(self, daily_df, benchmark_data, trade_log, rebalance_log):
        """生成组合回测报告"""
        if daily_df.empty:
            return {}

        values = daily_df['portfolio_value'].values
        initial = self.config.initial_cash
        final = values[-1]
        total_return = (final - initial) / initial
        days = (daily_df.index[-1] - daily_df.index[0]).days
        annual_return = (1 + total_return) ** (365 / days) - 1 if days > 0 else 0

        # 最大回撤
        running_max = np.maximum.accumulate(values)
        drawdown = (values - running_max) / running_max
        max_drawdown = np.min(drawdown)

        # 夏普比率
        daily_returns = np.diff(values) / values[:-1]
        excess = daily_returns - 0.02 / 252
        sharpe = (np.mean(excess) / np.std(excess) * np.sqrt(252)) if np.std(excess) > 0 else 0

        # 交易统计
        sell_trades = [t for t in trade_log if t['action'] == 'SELL' and t.get('reason') != 'BACKTEST_END']
        profitable_trades = [t for t in sell_trades if t.get('profit', 0) > 0]
        losing_trades = [t for t in sell_trades if t.get('profit', 0) < 0]
        total_trades = len(sell_trades)
        win_rate = len(profitable_trades) / total_trades * 100 if total_trades > 0 else 0

        # trailing stop 统计
        ts_trades = [t for t in trade_log if t.get('reason') == 'TRAILING_STOP']
        rebalance_trades = [t for t in trade_log if 'REBALANCE' in t.get('reason', '')]

        # 基准对比
        bench_start = benchmark_data.loc[daily_df.index[0]:].iloc[0]['Close']
        bench_end = benchmark_data.loc[:daily_df.index[-1]].iloc[-1]['Close']
        bench_return = (bench_end - bench_start) / bench_start
        bench_annual = (1 + bench_return) ** (365 / days) - 1 if days > 0 else 0

        # 基准夏普和回撤
        bench_prices = benchmark_data.loc[daily_df.index[0]:daily_df.index[-1], 'Close']
        bench_daily_ret = bench_prices.pct_change().dropna()
        bench_excess = bench_daily_ret - 0.02 / 252
        bench_sharpe = (bench_excess.mean() / bench_excess.std() * np.sqrt(252)) if bench_excess.std() > 0 else 0

        bench_normalized = bench_prices / bench_prices.iloc[0] * initial
        bench_running_max = bench_normalized.cummax()
        bench_dd = (bench_normalized - bench_running_max) / bench_running_max
        bench_max_dd = bench_dd.min()

        # 市场环境统计
        regime_counts = daily_df['regime'].value_counts().to_dict()

        # 平均持仓数
        avg_positions = daily_df['n_positions'].mean()

        # 换手率
        buy_trades = [t for t in trade_log if t['action'] == 'BUY']
        total_buy_value = sum(t.get('shares', 0) * t.get('price', 0) for t in buy_trades)
        avg_portfolio_value = values.mean()
        turnover = total_buy_value / avg_portfolio_value if avg_portfolio_value > 0 else 0

        # Alpha t-stat 和 Information Ratio
        # daily alpha = portfolio daily return - benchmark daily return
        daily_alpha = daily_returns - bench_daily_ret.values[:len(daily_returns)] if len(bench_daily_ret) >= len(daily_returns) else daily_returns - 0
        alpha_mean = np.mean(daily_alpha)
        alpha_std = np.std(daily_alpha, ddof=1) if len(daily_alpha) > 1 else 1
        # t-stat = mean(alpha) / (std(alpha) / sqrt(N))
        alpha_tstat = (alpha_mean / (alpha_std / np.sqrt(len(daily_alpha)))) if alpha_std > 0 else 0
        # Information Ratio = annualized alpha / tracking error
        tracking_error = alpha_std * np.sqrt(252)
        information_ratio = (alpha_mean * 252) / tracking_error if tracking_error > 0 else 0

        report = {
            # 收益
            'initial_value': initial,
            'final_value': round(final, 2),
            'total_return_pct': round(total_return * 100, 2),
            'annual_return_pct': round(annual_return * 100, 2),

            # 风险
            'max_drawdown_pct': round(max_drawdown * 100, 2),
            'sharpe_ratio': round(sharpe, 2),

            # 基准
            'benchmark_return_pct': round(bench_return * 100, 2),
            'benchmark_annual_pct': round(bench_annual * 100, 2),
            'benchmark_sharpe': round(bench_sharpe, 2),
            'benchmark_max_dd_pct': round(bench_max_dd * 100, 2),
            'alpha_pct': round((annual_return - bench_annual) * 100, 2),
            'beat_benchmark': total_return > bench_return,

            # Alpha 统计检验
            'alpha_tstat': round(alpha_tstat, 2),
            'information_ratio': round(information_ratio, 2),
            'tracking_error_pct': round(tracking_error * 100, 2),
            'alpha_significant': abs(alpha_tstat) > 1.96,  # 95% 置信

            # 交易
            'total_trades': len(trade_log),
            'sell_trades': total_trades,
            'win_rate': round(win_rate, 1),
            'trailing_stop_count': len(ts_trades),
            'rebalance_trade_count': len(rebalance_trades),
            'avg_hold_days': round(np.mean([t.get('hold_days', 0) for t in sell_trades]), 1) if sell_trades else 0,

            # 组合
            'avg_positions': round(avg_positions, 1),
            'total_rebalances': len(rebalance_log),
            'turnover': round(turnover, 2),

            # 市场环境
            'regime_days': regime_counts,

            # 明细
            'rebalance_log': rebalance_log,
        }

        return report
