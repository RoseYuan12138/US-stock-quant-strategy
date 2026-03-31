"""
回测框架
支持单策略和多策略回测，计算各项性能指标
"""

import numpy as np
import pandas as pd
from datetime import datetime
from pathlib import Path
import json

class BacktestEngine:
    """回测引擎"""
    
    def __init__(self, initial_cash=10000, commission=10):
        """
        初始化回测引擎
        
        Args:
            initial_cash: 初始资金 (default: $10,000)
            commission: 每笔交易的佣金 (default: $10)
        """
        self.initial_cash = initial_cash
        self.commission = commission
        self.reset()
    
    def reset(self):
        """重置引擎状态"""
        self.cash = self.initial_cash
        self.holdings = 0  # 持股数量
        self.entry_price = 0  # 成本价
        self.trades = []  # 交易记录
        self.portfolio_value = []  # 每日投资组合价值
        self.dates = []  # 日期
    
    def run_backtest(self, data, strategy, signal_column='signal'):
        """
        执行回测
        
        Args:
            data: pd.DataFrame，包含 OHLCV 和交易信号
            strategy: 策略对象或生成信号的函数
            signal_column: 信号列名
        
        Returns:
            pd.DataFrame: 回测结果
        """
        self.reset()
        
        df = data.copy()
        
        # 如果没有信号列，使用策略计算
        if signal_column not in df.columns:
            if callable(strategy):
                df[signal_column] = strategy.calculate(df)
            else:
                df[signal_column] = strategy.calculate(df)
        
        # 执行逐日交易
        for idx, (date, row) in enumerate(df.iterrows()):
            close = row['Close']
            signal = row[signal_column]
            
            # 简化信号：>3 为买入，<3 为卖出，=3 为持有
            if signal > 3 and self.holdings == 0:
                # 买入信号
                self._buy(close, date, signal)
            elif signal < 3 and self.holdings > 0:
                # 卖出信号
                self._sell(close, date, signal)
            
            # 记录每日投资组合价值
            portfolio_value = self.cash + self.holdings * close
            self.portfolio_value.append(portfolio_value)
            self.dates.append(date)
        
        # 平仓
        if self.holdings > 0 and len(df) > 0:
            last_price = df['Close'].iloc[-1]
            self._sell(last_price, df.index[-1], 0)
        
        # 构建结果
        df['Portfolio_Value'] = self.portfolio_value[:len(df)]
        return df, self._generate_report()
    
    def _buy(self, price, date, signal):
        """买入"""
        if self.cash >= price + self.commission:
            shares = self.cash / (price + self.commission / self.cash)
            shares = int(shares * 100) / 100  # 保留2位小数
            
            cost = shares * price + self.commission
            self.cash -= cost
            self.holdings = shares
            self.entry_price = price
            
            self.trades.append({
                'date': date,
                'action': 'BUY',
                'price': price,
                'shares': shares,
                'value': cost,
                'signal': signal
            })
    
    def _sell(self, price, date, signal):
        """卖出"""
        if self.holdings > 0:
            revenue = self.holdings * price - self.commission
            profit = revenue - (self.holdings * self.entry_price + self.commission)
            
            self.cash += revenue
            
            self.trades.append({
                'date': date,
                'action': 'SELL',
                'price': price,
                'shares': self.holdings,
                'value': revenue,
                'profit': profit,
                'profit_pct': profit / (self.holdings * self.entry_price) * 100,
                'signal': signal
            })
            
            self.holdings = 0
            self.entry_price = 0
    
    def _generate_report(self):
        """生成回测报告"""
        if not self.portfolio_value:
            return {}
        
        # 基础指标
        initial_value = self.initial_cash
        final_value = self.portfolio_value[-1]
        total_return = (final_value - initial_value) / initial_value
        
        # 最大回撤
        max_drawdown = self._calculate_max_drawdown()
        
        # 胜率
        win_rate = self._calculate_win_rate()
        
        # 夏普比率
        sharpe_ratio = self._calculate_sharpe_ratio()
        
        # 交易统计
        total_trades = len([t for t in self.trades if t['action'] == 'SELL'])
        avg_win = self._calculate_avg_win()
        avg_loss = self._calculate_avg_loss()
        
        return {
            'initial_value': initial_value,
            'final_value': final_value,
            'total_return': total_return,
            'total_return_pct': total_return * 100,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe_ratio,
            'total_trades': total_trades,
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'total_commissions': self.commission * len(self.trades),
        }
    
    def _calculate_max_drawdown(self):
        """计算最大回撤"""
        if not self.portfolio_value:
            return 0
        
        values = np.array(self.portfolio_value)
        running_max = np.maximum.accumulate(values)
        drawdown = (values - running_max) / running_max
        return np.min(drawdown)
    
    def _calculate_win_rate(self):
        """计算胜率"""
        sells = [t for t in self.trades if t['action'] == 'SELL']
        if not sells:
            return 0
        
        wins = sum(1 for t in sells if t.get('profit', 0) > 0)
        return wins / len(sells) * 100
    
    def _calculate_avg_win(self):
        """平均赢利"""
        sells = [t for t in self.trades if t['action'] == 'SELL' and t.get('profit', 0) > 0]
        if not sells:
            return 0
        return sum(t['profit'] for t in sells) / len(sells)
    
    def _calculate_avg_loss(self):
        """平均亏损"""
        sells = [t for t in self.trades if t['action'] == 'SELL' and t.get('profit', 0) < 0]
        if not sells:
            return 0
        return sum(t['profit'] for t in sells) / len(sells)
    
    def _calculate_sharpe_ratio(self, risk_free_rate=0.02):
        """计算夏普比率"""
        if len(self.portfolio_value) < 2:
            return 0
        
        values = np.array(self.portfolio_value)
        returns = np.diff(values) / values[:-1]
        
        excess_returns = returns - (risk_free_rate / 252)  # 日化无风险利率
        
        if np.std(excess_returns) == 0:
            return 0
        
        sharpe = np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(252)
        return sharpe
    
    def print_report(self, report):
        """打印报告"""
        print("\n" + "="*60)
        print("回测报告")
        print("="*60)
        print(f"初始资金: ${report['initial_value']:,.2f}")
        print(f"最终资金: ${report['final_value']:,.2f}")
        print(f"总收益率: {report['total_return_pct']:.2f}%")
        print(f"最大回撤: {report['max_drawdown']*100:.2f}%")
        print(f"夏普比率: {report['sharpe_ratio']:.2f}")
        print(f"总交易数: {report['total_trades']}")
        print(f"胜率: {report['win_rate']:.1f}%")
        print(f"平均赢利: ${report['avg_win']:,.2f}")
        print(f"平均亏损: ${report['avg_loss']:,.2f}")
        print(f"总佣金: ${report['total_commissions']:,.2f}")
        print("="*60 + "\n")


class MultiStrategyBacktest:
    """多策略回测"""
    
    def __init__(self, initial_cash=10000, commission=10):
        self.initial_cash = initial_cash
        self.commission = commission
        self.results = {}
    
    def run(self, data, strategies):
        """
        运行多策略回测
        
        Args:
            data: 包含 OHLCV 的 DataFrame
            strategies: 策略列表
        
        Returns:
            dict: 各策略的回测结果和报告
        """
        for strategy in strategies:
            engine = BacktestEngine(self.initial_cash, self.commission)
            result, report = engine.run_backtest(data, strategy)
            
            self.results[strategy.name] = {
                'result': result,
                'report': report,
                'engine': engine
            }
        
        return self.results
    
    def compare(self):
        """比较各策略"""
        print("\n" + "="*60)
        print("策略对比")
        print("="*60)
        
        comparison = pd.DataFrame([
            {
                'Strategy': name,
                'Total Return %': result['report']['total_return_pct'],
                'Sharpe Ratio': result['report']['sharpe_ratio'],
                'Max Drawdown %': result['report']['max_drawdown'] * 100,
                'Win Rate %': result['report']['win_rate'],
                'Total Trades': result['report']['total_trades']
            }
            for name, result in self.results.items()
        ])
        
        comparison = comparison.sort_values('Total Return %', ascending=False)
        print(comparison.to_string(index=False))
        print("="*60 + "\n")
        
        return comparison


if __name__ == "__main__":
    # 测试
    from data.data_fetcher import DataFetcher
    from strategy.strategies import SMACrossover, RSIStrategy, MACDStrategy
    
    fetcher = DataFetcher()
    data = fetcher.fetch_historical_data('AAPL', start_date='2024-01-01')
    
    if data is not None:
        # 单策略回测
        sma = SMACrossover()
        engine = BacktestEngine()
        result, report = engine.run_backtest(data, sma)
        engine.print_report(report)
        
        # 多策略回测
        strategies = [SMACrossover(), RSIStrategy(), MACDStrategy()]
        multi = MultiStrategyBacktest()
        multi.run(data, strategies)
        multi.compare()
