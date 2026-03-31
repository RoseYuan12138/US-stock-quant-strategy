"""
日级交易信号生成
每日更新最新交易信号和建议
支持技术信号和新闻情感融合
"""

import pandas as pd
import numpy as np
from datetime import datetime
import json
from pathlib import Path
from typing import Optional, Dict, List

class SignalGenerator:
    """交易信号生成器"""
    
    def __init__(self, strategies=None, risk_free_rate=0.02):
        """
        Args:
            strategies: 策略列表
            risk_free_rate: 无风险利率
        """
        self.strategies = strategies
        self.risk_free_rate = risk_free_rate
    
    def generate_signals(self, ticker, data, sentiment_data: Optional[Dict] = None):
        """
        为指定股票生成当日信号
        
        Args:
            ticker: 股票代码
            data: 历史 OHLCV 数据
            sentiment_data: 新闻情感分析数据（可选）
        
        Returns:
            dict: 包含信号、价位、建议等信息
        """
        if len(data) < 50:  # 需要足够的历史数据
            return {
                'ticker': ticker,
                'status': 'INSUFFICIENT_DATA',
                'message': f'数据不足（{len(data)} < 50）'
            }
        
        latest_price = data['Close'].iloc[-1]
        latest_date = data.index[-1]
        
        # 计算技术指标
        indicators = self._calculate_indicators(data)
        
        # 汇总各策略信号
        strategy_signals = {}
        if self.strategies:
            for strategy in self.strategies:
                signal_value = strategy.get_latest_signal(data)
                
                # 处理返回值（可能是 Signal enum 或数值）
                if hasattr(signal_value, 'name'):
                    signal_name = signal_value.name
                    signal_int = signal_value.value
                else:
                    # 如果是数值，转换为最近的 Signal
                    signal_int = int(signal_value)
                    signal_name = self._value_to_signal(signal_int)
                
                strategy_signals[strategy.name] = {
                    'signal': signal_name,
                    'value': signal_int
                }
        
        # 综合信号
        if strategy_signals:
            avg_signal = np.mean([s['value'] for s in strategy_signals.values()])
            ensemble_signal = self._value_to_signal(avg_signal)
        else:
            ensemble_signal = 'UNKNOWN'
        
        # 信号融合：技术 + 新闻 (新增)
        fusion_result = self._fuse_signals_with_news(
            indicators, sentiment_data
        )
        
        # 计算关键价位
        atr = self._calculate_atr(data)
        support = indicators['support']
        resistance = indicators['resistance']
        
        # 止损线：支撑位下方 0.5*ATR
        stop_loss = support - 0.5 * atr
        # 目标价：阻力位上方 1*ATR
        target = resistance + 1 * atr
        
        return {
            'ticker': ticker,
            'date': latest_date.strftime('%Y-%m-%d'),
            'latest_price': latest_price,
            'status': 'OK',
            # 综合信号（技术）
            'signal': ensemble_signal,
            'signal_confidence': self._calculate_confidence(strategy_signals),
            # 融合信号（技术 + 新闻）(新增)
            'fusion': fusion_result,
            # 策略详情
            'strategies': strategy_signals,
            'indicators': {
                'sma_20': indicators['sma_20'],
                'sma_50': indicators['sma_50'],
                'rsi': indicators['rsi'],
                'macd': indicators['macd'],
                'macd_signal': indicators['macd_signal'],
                'macd_histogram': indicators['macd_histogram'],
            },
            # 新闻数据 (新增)
            'sentiment': sentiment_data,
            # 关键价位
            'support': support,
            'resistance': resistance,
            'stop_loss': stop_loss,
            'target': target,
            'risk_reward_ratio': (target - latest_price) / (latest_price - stop_loss) if latest_price > stop_loss else 0,
            # 建议
            'advice': self._generate_advice_v2(
                ensemble_signal, fusion_result, latest_price,
                support, resistance, target, sentiment_data
            )
        }
    
    def _calculate_indicators(self, data):
        """计算技术指标"""
        df = data.copy()
        
        # SMA
        sma_20 = df['Close'].rolling(20).mean().iloc[-1]
        sma_50 = df['Close'].rolling(50).mean().iloc[-1]
        
        # RSI
        rsi = self._calculate_rsi(df)
        
        # MACD
        ema_12 = df['Close'].ewm(span=12).mean()
        ema_26 = df['Close'].ewm(span=26).mean()
        macd = ema_12 - ema_26
        macd_signal = macd.ewm(span=9).mean()
        macd_histogram = macd - macd_signal
        
        # 支撑和阻力（简化：用最近 20 天的最低和最高）
        support = df['Low'].tail(20).min()
        resistance = df['High'].tail(20).max()
        
        return {
            'sma_20': sma_20,
            'sma_50': sma_50,
            'rsi': rsi,
            'macd': macd.iloc[-1],
            'macd_signal': macd_signal.iloc[-1],
            'macd_histogram': macd_histogram.iloc[-1],
            'support': support,
            'resistance': resistance,
        }
    
    def _calculate_rsi(self, data, period=14):
        """计算 RSI"""
        delta = data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1]
    
    def _calculate_atr(self, data, period=14):
        """计算 ATR (Average True Range)"""
        df = data.copy()
        
        df['tr1'] = df['High'] - df['Low']
        df['tr2'] = abs(df['High'] - df['Close'].shift(1))
        df['tr3'] = abs(df['Low'] - df['Close'].shift(1))
        df['TR'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
        
        atr = df['TR'].rolling(period).mean()
        return atr.iloc[-1]
    
    def _value_to_signal(self, value):
        """将信号数值转换为文本"""
        if value >= 4.5:
            return 'STRONG_BUY'
        elif value >= 3.5:
            return 'BUY'
        elif value >= 2.5:
            return 'HOLD'
        elif value >= 1.5:
            return 'SELL'
        else:
            return 'STRONG_SELL'
    
    def _calculate_confidence(self, strategy_signals):
        """计算信号置信度（0-100）"""
        if not strategy_signals:
            return 0
        
        values = [s['value'] for s in strategy_signals.values()]
        # 信号越一致，置信度越高
        std = np.std(values)
        # 标准差越小，置信度越高；最小 std=0 时 confidence=100，std=2 时 confidence≈10
        confidence = max(0, 100 - std * 50)
        return confidence
    
    def _fuse_signals_with_news(self, indicators: Dict, sentiment_data: Optional[Dict] = None) -> Dict:
        """
        融合技术信号和新闻情感信号
        
        Returns:
            Dict: {
                'confidence': float (0-100),
                'signal': str,
                'reasoning': str,
                'divergence': str,
            }
        """
        try:
            from signals.signal_fusion import SignalFusion
            
            fusion = SignalFusion(technical_weight=0.6, news_weight=0.4)
            
            # 计算技术评分
            tech_score = fusion.calculate_technical_score(indicators)
            
            # 计算新闻评分
            news_score = fusion.calculate_news_score(sentiment_data)
            
            # 融合
            result = fusion.fuse_signals(
                tech_score, news_score,
                sentiment_data, indicators
            )
            
            return result
        
        except ImportError:
            # 如果信号融合模块不可用，返回基础信息
            return {
                'confidence': 50,
                'signal': 'HOLD',
                'reasoning': 'Signal fusion module not available',
                'divergence': 'unknown',
            }
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"信号融合出错: {e}")
            return {
                'confidence': 50,
                'signal': 'HOLD',
                'reasoning': f'Error in signal fusion: {e}',
                'divergence': 'error',
            }
    
    def _generate_advice(self, signal, current_price, support, resistance, target):
        """生成交易建议"""
        advice = []
        
        if signal in ['STRONG_BUY', 'BUY']:
            advice.append(f"✅ 建议买入，当前价 ${current_price:.2f}")
            advice.append(f"📍 支撑位: ${support:.2f}，止损线: ${support:.2f}")
            advice.append(f"🎯 目标价: ${target:.2f}")
        elif signal == 'HOLD':
            advice.append(f"⏸️ 建议观望，当前价 ${current_price:.2f}")
            advice.append(f"📍 支撑位: ${support:.2f}，阻力位: ${resistance:.2f}")
        elif signal in ['SELL', 'STRONG_SELL']:
            advice.append(f"⛔ 建议卖出，当前价 ${current_price:.2f}")
            advice.append(f"📍 阻力位: ${resistance:.2f}")
            if current_price > support:
                advice.append(f"🛑 止损线: ${support:.2f}")
        
        return advice
    
    def _generate_advice_v2(self, signal, fusion_result, current_price, support, resistance, target, sentiment_data=None):
        """
        生成增强的交易建议（包含新闻信息）
        """
        advice = []
        
        # 基础价格建议
        fusion_signal = fusion_result.get('signal', signal) if fusion_result else signal
        fusion_confidence = fusion_result.get('confidence', 50) if fusion_result else 50
        
        if fusion_signal in ['STRONG_BUY', 'BUY']:
            advice.append(f"✅ 建议买入，当前价 ${current_price:.2f} (信心度 {fusion_confidence:.0f}%)")
            advice.append(f"📍 支撑位: ${support:.2f}，止损线: ${support:.2f}")
            advice.append(f"🎯 目标价: ${target:.2f}")
        elif fusion_signal == 'HOLD':
            advice.append(f"⏸️ 建议观望，当前价 ${current_price:.2f}")
            advice.append(f"📍 支撑位: ${support:.2f}，阻力位: ${resistance:.2f}")
        elif fusion_signal in ['SELL', 'STRONG_SELL']:
            advice.append(f"⛔ 建议卖出，当前价 ${current_price:.2f} (信心度 {abs(100-fusion_confidence):.0f}%)")
            advice.append(f"📍 阻力位: ${resistance:.2f}")
            if current_price > support:
                advice.append(f"🛑 止损线: ${support:.2f}")
        
        # 新闻信息提示
        if sentiment_data and sentiment_data.get('news_count', 0) > 0:
            divergence = fusion_result.get('divergence', 'unknown') if fusion_result else 'unknown'
            
            if divergence == 'tech_bullish_news_bearish':
                advice.append("⚠️ 技术面好但新闻面差，需要谨慎")
            elif divergence == 'tech_bearish_news_bullish':
                advice.append("💡 新闻利好但技术面冷淡，可观察")
            elif divergence == 'aligned_bullish':
                advice.append("✨ 技术和新闻信号一致看好")
            elif divergence == 'aligned_bearish':
                advice.append("⚠️ 技术和新闻信号一致看空")
        
        return advice
    
    def generate_daily_report(self, tickers_signals):
        """
        生成每日报告（增强版，包含新闻信息）
        
        Args:
            tickers_signals: {ticker: signal_dict}
        
        Returns:
            str: 格式化的报告文本
        """
        report_lines = [
            "=" * 70,
            f"📊 美股交易信号日报 (技术 + 新闻融合)",
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            "=" * 70,
            ""
        ]
        
        # 分类信号
        strong_buy = []
        buy = []
        hold = []
        sell = []
        strong_sell = []
        warnings = []  # 技术好但新闻差 或 新闻好但技术差
        
        for ticker, signal_info in tickers_signals.items():
            if signal_info.get('status') != 'OK':
                continue
            
            fusion = signal_info.get('fusion', {})
            fusion_signal = fusion.get('signal', 'HOLD')
            divergence = fusion.get('divergence', '')
            
            # 分类
            if divergence in ['tech_bullish_news_bearish', 'tech_bearish_news_bullish']:
                warnings.append((ticker, signal_info))
            elif fusion_signal == 'STRONG_BUY':
                strong_buy.append((ticker, signal_info))
            elif fusion_signal == 'BUY':
                buy.append((ticker, signal_info))
            elif fusion_signal == 'HOLD':
                hold.append((ticker, signal_info))
            elif fusion_signal == 'SELL':
                sell.append((ticker, signal_info))
            elif fusion_signal == 'STRONG_SELL':
                strong_sell.append((ticker, signal_info))
        
        # 【强买信号】
        if strong_buy:
            report_lines.append("【🚀 强买信号】")
            for ticker, info in strong_buy:
                self._append_signal_detail(report_lines, ticker, info)
            report_lines.append("")
        
        # 【买入信号】
        if buy:
            report_lines.append("【💚 买入信号】")
            for ticker, info in buy:
                self._append_signal_detail(report_lines, ticker, info)
            report_lines.append("")
        
        # 【风险警告】
        if warnings:
            report_lines.append("【⚠️ 风险警告 - 技术好但新闻差 / 新闻好但技术差】")
            for ticker, info in warnings:
                self._append_signal_detail(report_lines, ticker, info)
            report_lines.append("")
        
        # 【持有信号】
        if hold:
            report_lines.append("【⏸️ 持有观望】")
            for ticker, info in hold:
                self._append_signal_detail(report_lines, ticker, info, brief=True)
            report_lines.append("")
        
        # 【卖出信号】
        if sell:
            report_lines.append("【📉 卖出信号】")
            for ticker, info in sell:
                self._append_signal_detail(report_lines, ticker, info)
            report_lines.append("")
        
        # 【强卖信号】
        if strong_sell:
            report_lines.append("【🔴 强卖信号】")
            for ticker, info in strong_sell:
                self._append_signal_detail(report_lines, ticker, info)
            report_lines.append("")
        
        report_lines.append("=" * 70)
        report_lines.append(f"报告说明: 综合信心度 = 技术信号 60% + 新闻情感 40%")
        report_lines.append(f"数据来源: YFinance (价格) | NewsAPI/Yahoo Finance (新闻)")
        report_lines.append("=" * 70)
        
        return "\n".join(report_lines)
    
    def _append_signal_detail(self, lines, ticker, signal_info, brief=False):
        """追加单只股票的信号详情"""
        fusion = signal_info.get('fusion', {})
        indicators = signal_info.get('indicators', {})
        sentiment = signal_info.get('sentiment', {})
        
        # 标题行
        fusion_confidence = fusion.get('confidence', 0)
        lines.append(f"  {ticker} (信心度 {fusion_confidence:.0f}%)")
        
        # 价格信息
        lines.append(f"    价格: ${signal_info['latest_price']:.2f}")
        
        # 技术指标
        if indicators:
            lines.append(
                f"    技术: RSI={indicators['rsi']:.0f} | "
                f"SMA20={indicators['sma_20']:.0f} | "
                f"MACD={'金叉' if indicators['macd'] > indicators['macd_signal'] else '死叉'}"
            )
        
        # 新闻情感
        if sentiment and sentiment.get('news_count', 0) > 0:
            trend = sentiment.get('trend', 'stable')
            trend_emoji = '📈' if trend == 'improving' else ('📉' if trend == 'declining' else '➡️')
            lines.append(
                f"    新闻: {sentiment['positive_count']}正 {sentiment['negative_count']}负 {sentiment['neutral_count']}中 "
                f"({trend_emoji} {trend})"
            )
        
        # 目标价和止损
        if not brief:
            lines.append(
                f"    目标: ${signal_info['target']:.2f} | "
                f"止损: ${signal_info['stop_loss']:.2f}"
            )
        
        # 建议
        for advice in signal_info.get('advice', [])[:2]:  # 只显示前两条建议
            lines.append(f"    {advice}")
        
        lines.append("")
    
    def _signal_priority(self, signal):
        """信号优先级"""
        priority = {
            'STRONG_BUY': 5,
            'BUY': 4,
            'HOLD': 3,
            'SELL': 2,
            'STRONG_SELL': 1,
            'UNKNOWN': 0,
        }
        return priority.get(signal, 0)
    
    def save_report(self, report_text, output_file=None):
        """保存报告到文件"""
        if output_file is None:
            output_file = f"daily_report_{datetime.now().strftime('%Y%m%d')}.txt"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(report_text)
        
        return output_file


if __name__ == "__main__":
    # 测试
    from data.data_fetcher import DataFetcher
    from strategy.strategies import StrategyEnsemble
    
    fetcher = DataFetcher()
    ensemble = StrategyEnsemble()
    generator = SignalGenerator(strategies=ensemble.strategies)
    
    # 生成多只股票的信号
    tickers = ['AAPL', 'MSFT', 'GOOGL']
    signals = {}
    
    for ticker in tickers:
        data = fetcher.fetch_historical_data(ticker)
        if data is not None:
            signal = generator.generate_signals(ticker, data)
            signals[ticker] = signal
    
    # 生成日报
    report = generator.generate_daily_report(signals)
    print(report)
