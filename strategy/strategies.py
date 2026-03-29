"""
量化策略实现
包含：双均线、RSI、MACD 等经典策略
"""

import numpy as np
import pandas as pd
from enum import Enum

class Signal(Enum):
    """交易信号"""
    STRONG_BUY = 5
    BUY = 4
    HOLD = 3
    SELL = 2
    STRONG_SELL = 1
    UNKNOWN = 0


class BaseStrategy:
    """策略基类"""
    
    def __init__(self, name):
        self.name = name
    
    def calculate(self, data):
        """
        计算策略信号
        
        Args:
            data: pd.DataFrame，包含 Open, High, Low, Close, Volume
        
        Returns:
            pd.Series: 信号序列
        """
        raise NotImplementedError
    
    def get_latest_signal(self, data):
        """获取最新信号"""
        signals = self.calculate(data)
        return signals.iloc[-1]


class SMACrossover(BaseStrategy):
    """
    双均线策略
    SMA-20 > SMA-50: 买入信号
    SMA-20 < SMA-50: 卖出信号
    """
    
    def __init__(self, short_window=20, long_window=50):
        super().__init__("SMA Crossover")
        self.short_window = short_window
        self.long_window = long_window
    
    def calculate(self, data):
        """计算双均线信号"""
        df = data.copy()
        
        # 计算移动平均线
        df['SMA_short'] = df['Close'].rolling(window=self.short_window).mean()
        df['SMA_long'] = df['Close'].rolling(window=self.long_window).mean()
        
        # 生成信号
        signals = pd.Series(Signal.UNKNOWN.value, index=df.index)
        
        # SMA_short > SMA_long: 买入趋势
        # SMA_short < SMA_long: 卖出趋势
        # 计算差值和差值速度
        diff = df['SMA_short'] - df['SMA_long']
        diff_pct = diff / df['SMA_long']
        
        # 强信号：差值 > 2%
        signals[diff_pct > 0.02] = Signal.STRONG_BUY.value
        signals[(diff_pct > 0) & (diff_pct <= 0.02)] = Signal.BUY.value
        signals[(diff_pct < 0) & (diff_pct >= -0.02)] = Signal.SELL.value
        signals[diff_pct < -0.02] = Signal.STRONG_SELL.value
        signals[(-0.02 <= diff_pct) & (diff_pct <= 0)] = Signal.HOLD.value
        
        return signals


class RSIStrategy(BaseStrategy):
    """
    RSI 超卖超买策略
    RSI < 30: 超卖，买入信号
    RSI > 70: 超买，卖出信号
    """
    
    def __init__(self, period=14, oversold=30, overbought=70):
        super().__init__("RSI")
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
    
    def _calculate_rsi(self, data):
        """计算 RSI"""
        delta = data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def calculate(self, data):
        """计算 RSI 信号"""
        df = data.copy()
        df['RSI'] = self._calculate_rsi(df)
        
        signals = pd.Series(Signal.UNKNOWN.value, index=df.index)
        
        # 根据 RSI 值生成信号
        signals[df['RSI'] < self.oversold] = Signal.STRONG_BUY.value
        signals[(df['RSI'] >= self.oversold) & (df['RSI'] < 40)] = Signal.BUY.value
        signals[(df['RSI'] >= 40) & (df['RSI'] <= 60)] = Signal.HOLD.value
        signals[(df['RSI'] > 60) & (df['RSI'] <= self.overbought)] = Signal.SELL.value
        signals[df['RSI'] > self.overbought] = Signal.STRONG_SELL.value
        
        return signals


class MACDStrategy(BaseStrategy):
    """
    MACD 策略
    MACD 线 > 信号线：买入
    MACD 线 < 信号线：卖出
    """
    
    def __init__(self, fast=12, slow=26, signal=9):
        super().__init__("MACD")
        self.fast = fast
        self.slow = slow
        self.signal = signal
    
    def calculate(self, data):
        """计算 MACD 信号"""
        df = data.copy()
        
        # 计算 MACD
        ema_fast = df['Close'].ewm(span=self.fast).mean()
        ema_slow = df['Close'].ewm(span=self.slow).mean()
        
        df['MACD'] = ema_fast - ema_slow
        df['Signal_Line'] = df['MACD'].ewm(span=self.signal).mean()
        df['Histogram'] = df['MACD'] - df['Signal_Line']
        
        signals = pd.Series(Signal.UNKNOWN.value, index=df.index)
        
        # 根据 MACD 直方图生成信号
        # 直方图 > 0 且 > 上一个值：强买
        # 直方图 > 0：买入
        # 直方图 < 0：卖出
        # 直方图 < 0 且 < 上一个值：强卖
        
        hist = df['Histogram']
        hist_prev = hist.shift(1)
        
        signals[hist > 0] = Signal.HOLD.value  # 默认持有
        signals[(hist > 0) & (hist > hist_prev)] = Signal.BUY.value
        signals[(hist > 0) & (hist > hist_prev) & (hist > 0.001)] = Signal.STRONG_BUY.value
        
        signals[(hist < 0) & (hist < hist_prev)] = Signal.SELL.value
        signals[(hist < 0) & (hist < hist_prev) & (hist < -0.001)] = Signal.STRONG_SELL.value
        
        return signals


class StrategyEnsemble:
    """策略集合：组合多个策略的信号"""
    
    def __init__(self, strategies=None):
        """
        Args:
            strategies: 策略列表，如果为 None，使用默认策略组合
        """
        if strategies is None:
            self.strategies = [
                SMACrossover(),
                RSIStrategy(),
                MACDStrategy()
            ]
        else:
            self.strategies = strategies
    
    def calculate(self, data):
        """
        计算综合信号
        
        Returns:
            pd.DataFrame: 每个策略的信号，以及综合信号
        """
        results = pd.DataFrame(index=data.index)
        
        for strategy in self.strategies:
            signals = strategy.calculate(data)
            results[strategy.name] = signals
        
        # 综合信号：各策略信号的平均值
        results['Ensemble'] = results.mean(axis=1).round(0)
        
        return results
    
    def get_latest_ensemble_signal(self, data):
        """获取最新的综合信号"""
        results = self.calculate(data)
        latest_signal = results['Ensemble'].iloc[-1]
        
        # 将数值映射到 Signal
        for signal in Signal:
            if signal.value == latest_signal:
                return signal
        
        return Signal.UNKNOWN


if __name__ == "__main__":
    # 测试
    from data.data_fetcher import DataFetcher
    
    fetcher = DataFetcher()
    data = fetcher.fetch_historical_data('AAPL', start_date='2024-01-01')
    
    if data is not None:
        # 测试单个策略
        sma = SMACrossover()
        sma_signals = sma.calculate(data)
        print("SMA 策略信号 (最后5行):")
        print(sma_signals.tail())
        
        # 测试策略集合
        ensemble = StrategyEnsemble()
        ensemble_signals = ensemble.calculate(data)
        print("\n综合信号 (最后5行):")
        print(ensemble_signals.tail())
