"""
价值投资策略
核心逻辑：基本面筛选 + 纪律性买入 + 止盈止损

与纯技术指标策略不同，这个策略:
1. 用基本面评分决定"买什么" (选股)
2. 用简单的均值回归/动量确认决定"什么时候买" (择时)
3. 用纪律性规则决定"什么时候卖" (止盈止损 + 定期再平衡)

回测验证方法:
- 对每只股票，先做基本面评分
- 评分 >= 70 的股票进入买入池
- 在买入池内，等待价格回调到合理区间后买入
- 持有并定期检查：止盈 20%、止损 10%、或基本面恶化则卖出
"""

import numpy as np
import pandas as pd
from enum import Enum


class ValueSignal(Enum):
    """价值策略信号"""
    STRONG_BUY = 5    # 基本面优+价格回调
    BUY = 4           # 基本面好+价格合理
    HOLD = 3          # 持有
    SELL = 2          # 止盈/止损/基本面恶化
    STRONG_SELL = 1   # 强制平仓
    UNKNOWN = 0


class ValueStrategy:
    """
    价值投资策略

    选股条件 (基本面筛选):
    - 基本面评分 >= buy_threshold (default 65)
    - 分析师目标价有上涨空间

    买入时机 (技术辅助):
    - 价格低于20日均线（回调买入）
    - 或 RSI < 40（超卖区）

    卖出条件:
    - 盈利 >= take_profit (default 20%)
    - 亏损 >= stop_loss (default 10%)
    - 持有超过 max_hold_days 天后重新评估
    """

    def __init__(self, buy_threshold=65, take_profit=0.20, stop_loss=0.10,
                 max_hold_days=60, sma_window=20, rsi_period=14):
        self.name = "Value Strategy"
        self.buy_threshold = buy_threshold
        self.take_profit = take_profit
        self.stop_loss = stop_loss
        self.max_hold_days = max_hold_days
        self.sma_window = sma_window
        self.rsi_period = rsi_period

    def calculate(self, data, fundamental_score=None):
        """
        计算价值策略信号

        Args:
            data: pd.DataFrame with OHLCV
            fundamental_score: float (0-100), 基本面评分
                如果为 None，只用技术面做择时（退化为均值回归策略）

        Returns:
            pd.Series: 信号序列
        """
        df = data.copy()

        # 技术指标计算
        df['SMA'] = df['Close'].rolling(window=self.sma_window).mean()
        df['RSI'] = self._calculate_rsi(df)

        # 价格相对 SMA 的位置
        df['price_vs_sma'] = (df['Close'] - df['SMA']) / df['SMA']

        signals = pd.Series(ValueSignal.UNKNOWN.value, index=df.index)

        # 基本面评分决定是否"有资格买入"
        if fundamental_score is not None and fundamental_score >= self.buy_threshold:
            # 基本面过关 -> 等待好的买入时机
            # 价格回调到均线以下 + RSI 偏低 = 好机会
            buy_condition = (df['price_vs_sma'] < 0) & (df['RSI'] < 45)
            strong_buy = (df['price_vs_sma'] < -0.03) & (df['RSI'] < 35)

            signals[buy_condition] = ValueSignal.BUY.value
            signals[strong_buy] = ValueSignal.STRONG_BUY.value

            # 非买入区间 = 持有 (已持仓的话)
            hold_condition = ~buy_condition & ~strong_buy
            signals[hold_condition] = ValueSignal.HOLD.value

            # 卖出信号：大幅超涨
            overbought = (df['price_vs_sma'] > 0.08) & (df['RSI'] > 75)
            signals[overbought] = ValueSignal.SELL.value

        elif fundamental_score is not None and fundamental_score < self.buy_threshold:
            # 基本面不过关 -> 不买，已有持仓等止盈止损
            signals[:] = ValueSignal.HOLD.value
            # 如果大幅超涨也卖
            overbought = (df['price_vs_sma'] > 0.05) & (df['RSI'] > 70)
            signals[overbought] = ValueSignal.SELL.value

        else:
            # 没有基本面数据，退化为均值回归策略
            buy_condition = (df['price_vs_sma'] < -0.02) & (df['RSI'] < 40)
            strong_buy = (df['price_vs_sma'] < -0.05) & (df['RSI'] < 30)
            sell_condition = (df['price_vs_sma'] > 0.05) & (df['RSI'] > 70)

            signals[:] = ValueSignal.HOLD.value
            signals[buy_condition] = ValueSignal.BUY.value
            signals[strong_buy] = ValueSignal.STRONG_BUY.value
            signals[sell_condition] = ValueSignal.SELL.value

        return signals

    def _calculate_rsi(self, data):
        """计算 RSI"""
        delta = data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.rsi_period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi


class DisciplinedBacktester:
    """
    纪律性回测引擎
    相比简单回测，增加了:
    1. 止盈止损
    2. 持仓天数限制
    3. 分批建仓 (可选)
    4. 与基准的相对表现对比
    """

    def __init__(self, initial_cash=10000, commission=10,
                 take_profit=0.20, stop_loss=0.10, max_hold_days=60):
        self.initial_cash = initial_cash
        self.commission = commission
        self.take_profit = take_profit
        self.stop_loss = stop_loss
        self.max_hold_days = max_hold_days

    def run(self, data, strategy, fundamental_score=None, benchmark_data=None):
        """
        执行纪律性回测

        Args:
            data: OHLCV DataFrame
            strategy: ValueStrategy instance
            fundamental_score: 基本面评分 (0-100)
            benchmark_data: 基准指数的 OHLCV (e.g., SPY)

        Returns:
            (result_df, report_dict)
        """
        df = data.copy()
        signals = strategy.calculate(df, fundamental_score)
        df['signal'] = signals

        # 交易模拟
        cash = self.initial_cash
        holdings = 0
        entry_price = 0
        entry_date = None
        hold_days = 0
        trades = []
        portfolio_values = []

        for date, row in df.iterrows():
            close = row['Close']
            signal = row['signal']

            # 如果有持仓，检查止盈止损 + 持仓天数
            if holdings > 0:
                hold_days += 1
                pnl_pct = (close - entry_price) / entry_price

                # 止盈
                if pnl_pct >= self.take_profit:
                    revenue = holdings * close - self.commission
                    profit = revenue - (holdings * entry_price + self.commission)
                    cash += revenue
                    trades.append({
                        'date': date, 'action': 'SELL_TP', 'price': close,
                        'shares': holdings, 'profit': profit,
                        'profit_pct': pnl_pct * 100, 'hold_days': hold_days,
                        'reason': f'止盈 {pnl_pct*100:.1f}%'
                    })
                    holdings = 0
                    entry_price = 0
                    hold_days = 0

                # 止损
                elif pnl_pct <= -self.stop_loss:
                    revenue = holdings * close - self.commission
                    profit = revenue - (holdings * entry_price + self.commission)
                    cash += revenue
                    trades.append({
                        'date': date, 'action': 'SELL_SL', 'price': close,
                        'shares': holdings, 'profit': profit,
                        'profit_pct': pnl_pct * 100, 'hold_days': hold_days,
                        'reason': f'止损 {pnl_pct*100:.1f}%'
                    })
                    holdings = 0
                    entry_price = 0
                    hold_days = 0

                # 持仓过久强制重评
                elif hold_days >= self.max_hold_days and signal <= ValueSignal.HOLD.value:
                    revenue = holdings * close - self.commission
                    profit = revenue - (holdings * entry_price + self.commission)
                    cash += revenue
                    trades.append({
                        'date': date, 'action': 'SELL_EXPIRE', 'price': close,
                        'shares': holdings, 'profit': profit,
                        'profit_pct': pnl_pct * 100, 'hold_days': hold_days,
                        'reason': f'持仓 {hold_days} 天到期'
                    })
                    holdings = 0
                    entry_price = 0
                    hold_days = 0

                # 策略卖出信号
                elif signal <= ValueSignal.SELL.value:
                    revenue = holdings * close - self.commission
                    profit = revenue - (holdings * entry_price + self.commission)
                    cash += revenue
                    trades.append({
                        'date': date, 'action': 'SELL_SIGNAL', 'price': close,
                        'shares': holdings, 'profit': profit,
                        'profit_pct': pnl_pct * 100, 'hold_days': hold_days,
                        'reason': '策略卖出信号'
                    })
                    holdings = 0
                    entry_price = 0
                    hold_days = 0

            # 买入逻辑
            elif holdings == 0 and signal >= ValueSignal.BUY.value:
                if cash >= close + self.commission:
                    shares = int((cash - self.commission) / close)
                    if shares > 0:
                        cost = shares * close + self.commission
                        cash -= cost
                        holdings = shares
                        entry_price = close
                        entry_date = date
                        hold_days = 0
                        trades.append({
                            'date': date, 'action': 'BUY', 'price': close,
                            'shares': shares, 'cost': cost,
                            'reason': 'STRONG_BUY' if signal == ValueSignal.STRONG_BUY.value else 'BUY'
                        })

            # 记录每日组合价值
            portfolio_values.append(cash + holdings * close)

        # 平仓
        if holdings > 0:
            last_price = df['Close'].iloc[-1]
            revenue = holdings * last_price - self.commission
            profit = revenue - (holdings * entry_price + self.commission)
            cash += revenue
            trades.append({
                'date': df.index[-1], 'action': 'SELL_CLOSE', 'price': last_price,
                'shares': holdings, 'profit': profit,
                'profit_pct': (last_price - entry_price) / entry_price * 100,
                'hold_days': hold_days, 'reason': '回测结束平仓'
            })
            portfolio_values[-1] = cash
            holdings = 0

        df['Portfolio_Value'] = portfolio_values[:len(df)]

        # 生成报告
        report = self._generate_report(
            portfolio_values, trades, df, benchmark_data
        )

        return df, report

    def _generate_report(self, portfolio_values, trades, data, benchmark_data=None):
        """生成回测报告（含与基准的相对表现）"""
        if not portfolio_values:
            return {}

        initial = self.initial_cash
        final = portfolio_values[-1]
        total_return = (final - initial) / initial

        # 年化
        days = (data.index[-1] - data.index[0]).days
        annual_return = (1 + total_return) ** (365 / days) - 1 if days > 0 else 0

        # 最大回撤
        values = np.array(portfolio_values)
        running_max = np.maximum.accumulate(values)
        drawdown = (values - running_max) / running_max
        max_drawdown = np.min(drawdown)

        # 夏普比率
        daily_returns = np.diff(values) / values[:-1]
        excess = daily_returns - 0.02 / 252
        sharpe = (np.mean(excess) / np.std(excess) * np.sqrt(252)) if np.std(excess) > 0 else 0

        # 交易统计
        sell_trades = [t for t in trades if t['action'].startswith('SELL')]
        total_trades = len(sell_trades)
        wins = [t for t in sell_trades if t.get('profit', 0) > 0]
        losses = [t for t in sell_trades if t.get('profit', 0) < 0]
        win_rate = len(wins) / total_trades * 100 if total_trades > 0 else 0

        avg_win = np.mean([t['profit'] for t in wins]) if wins else 0
        avg_loss = np.mean([t['profit'] for t in losses]) if losses else 0
        avg_hold_days = np.mean([t.get('hold_days', 0) for t in sell_trades]) if sell_trades else 0

        # 止盈/止损统计
        tp_trades = [t for t in sell_trades if t['action'] == 'SELL_TP']
        sl_trades = [t for t in sell_trades if t['action'] == 'SELL_SL']
        expire_trades = [t for t in sell_trades if t['action'] == 'SELL_EXPIRE']

        report = {
            'initial_value': initial,
            'final_value': final,
            'total_return': total_return,
            'total_return_pct': total_return * 100,
            'annual_return_pct': annual_return * 100,
            'max_drawdown': max_drawdown,
            'max_drawdown_pct': max_drawdown * 100,
            'sharpe_ratio': sharpe,
            'total_trades': total_trades,
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'avg_hold_days': avg_hold_days,
            'tp_count': len(tp_trades),
            'sl_count': len(sl_trades),
            'expire_count': len(expire_trades),
            'trades': trades,
        }

        # 与基准对比
        if benchmark_data is not None and len(benchmark_data) > 0:
            bench_start = benchmark_data['Close'].iloc[0]
            bench_end = benchmark_data['Close'].iloc[-1]
            bench_return = (bench_end - bench_start) / bench_start
            bench_annual = (1 + bench_return) ** (365 / days) - 1 if days > 0 else 0

            # 基准夏普
            bench_daily = benchmark_data['Close'].pct_change().dropna()
            bench_excess = bench_daily - 0.02 / 252
            bench_sharpe = (bench_excess.mean() / bench_excess.std() * np.sqrt(252)) if bench_excess.std() > 0 else 0

            # 基准最大回撤
            bench_values = benchmark_data['Close'] / benchmark_data['Close'].iloc[0] * self.initial_cash
            bench_running_max = bench_values.cummax()
            bench_dd = (bench_values - bench_running_max) / bench_running_max
            bench_max_dd = bench_dd.min()

            report['benchmark_return_pct'] = bench_return * 100
            report['benchmark_annual_pct'] = bench_annual * 100
            report['benchmark_sharpe'] = bench_sharpe
            report['benchmark_max_dd_pct'] = bench_max_dd * 100
            report['alpha'] = annual_return - bench_annual  # 超额年化收益
            report['alpha_pct'] = (annual_return - bench_annual) * 100
            report['beat_benchmark'] = total_return > bench_return

        return report


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent))
    from data.data_fetcher import DataFetcher

    fetcher = DataFetcher(cache_dir='./data/cache')

    # 测试价值策略
    strategy = ValueStrategy(buy_threshold=65)
    backtester = DisciplinedBacktester(
        initial_cash=10000, commission=10,
        take_profit=0.20, stop_loss=0.10, max_hold_days=60
    )

    # 对 AAPL 做回测，假设基本面评分 75
    data = fetcher.fetch_historical_data('AAPL', start_date='2023-01-01', end_date='2025-12-31')
    spy = fetcher.fetch_historical_data('SPY', start_date='2023-01-01', end_date='2025-12-31')

    if data is not None:
        _, report = backtester.run(data, strategy, fundamental_score=75, benchmark_data=spy)

        print(f"\n{'='*60}")
        print(f"价值策略回测 - AAPL (基本面评分: 75)")
        print(f"{'='*60}")
        print(f"总收益: {report['total_return_pct']:.1f}%")
        print(f"年化收益: {report['annual_return_pct']:.1f}%")
        print(f"最大回撤: {report['max_drawdown_pct']:.1f}%")
        print(f"夏普比率: {report['sharpe_ratio']:.2f}")
        print(f"总交易: {report['total_trades']} (止盈{report['tp_count']} 止损{report['sl_count']} 到期{report['expire_count']})")
        print(f"胜率: {report['win_rate']:.1f}%")
        print(f"平均持仓: {report['avg_hold_days']:.0f} 天")

        if 'benchmark_return_pct' in report:
            print(f"\nSPY 基准: {report['benchmark_return_pct']:.1f}%")
            print(f"Alpha: {report['alpha_pct']:+.1f}%")
            print(f"{'✅ 跑赢基准' if report['beat_benchmark'] else '❌ 未跑赢基准'}")
