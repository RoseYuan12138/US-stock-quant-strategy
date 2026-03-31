"""
信号融合模块
将技术信号和新闻情感信号融合为综合信心度
"""

import logging
from typing import Dict, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)


class SignalFusion:
    """技术信号和新闻情感融合"""
    
    def __init__(self, technical_weight: float = 0.6, news_weight: float = 0.4):
        """
        Args:
            technical_weight: 技术信号权重
            news_weight: 新闻情感权重
        """
        assert abs(technical_weight + news_weight - 1.0) < 0.01, "权重必须相加为 1.0"
        
        self.technical_weight = technical_weight
        self.news_weight = news_weight
    
    def calculate_technical_score(self, indicators: Dict) -> float:
        """
        计算技术信号评分 (0-100)
        基于 RSI + SMA + MACD 的综合评分
        
        Args:
            indicators: {
                'rsi': float,
                'sma_20': float,
                'sma_50': float,
                'macd': float,
                'macd_signal': float,
                'macd_histogram': float,
            }
        
        Returns:
            float: 技术信号评分 (0-100)
        """
        try:
            rsi = indicators.get('rsi', 50)
            sma_20 = indicators.get('sma_20', 0)
            sma_50 = indicators.get('sma_50', 0)
            macd = indicators.get('macd', 0)
            macd_signal = indicators.get('macd_signal', 0)
            
            score = 0.0
            weights_sum = 0.0
            
            # RSI 评分 (权重 40%)
            # RSI < 30: 超卖，加分
            # RSI > 70: 超买，减分
            rsi_component = self._rsi_to_score(rsi)
            score += rsi_component * 0.40
            weights_sum += 0.40
            
            # SMA 评分 (权重 30%)
            # 如果当前价格 > SMA20 > SMA50，强烈看好
            # 如果当前价格 < SMA20 < SMA50，看空
            # SMA20 > SMA50: 短期趋势向上
            if sma_20 > 0 and sma_50 > 0:
                if sma_20 > sma_50:
                    sma_component = 70.0  # 短期趋势向上
                elif sma_20 < sma_50:
                    sma_component = 30.0  # 短期趋势向下
                else:
                    sma_component = 50.0  # 中立
            else:
                sma_component = 50.0
            
            score += sma_component * 0.30
            weights_sum += 0.30
            
            # MACD 评分 (权重 30%)
            # MACD > MACD Signal：看好，MACD_Histogram > 0
            # MACD < MACD Signal：看空，MACD_Histogram < 0
            if macd > macd_signal:
                macd_component = 70.0  # MACD 金叉
            elif macd < macd_signal:
                macd_component = 30.0  # MACD 死叉
            else:
                macd_component = 50.0
            
            score += macd_component * 0.30
            weights_sum += 0.30
            
            # 正规化到 0-100
            final_score = score / weights_sum if weights_sum > 0 else 50.0
            final_score = max(0.0, min(100.0, final_score))
            
            return final_score
        
        except Exception as e:
            logger.error(f"计算技术信号评分出错: {e}")
            return 50.0
    
    def _rsi_to_score(self, rsi: float) -> float:
        """
        将 RSI 转换为评分
        0-30: 超卖（看好），评分 60-100
        30-70: 中立，评分 40-60
        70-100: 超买（看空），评分 0-40
        """
        if rsi < 30:
            # 超卖
            return min(100, 60 + (30 - rsi))  # 30 -> 60, 0 -> 90
        elif rsi > 70:
            # 超买
            return max(0, 40 - (rsi - 70))  # 70 -> 40, 100 -> 10
        else:
            # 中立
            return 50.0
    
    def calculate_news_score(self, sentiment_data: Optional[Dict]) -> float:
        """
        计算新闻情感评分 (0-100)
        直接使用情感分析模块返回的 sentiment_score_0_100
        
        Args:
            sentiment_data: {
                'sentiment_score_0_100': int (0-100),
                'news_count': int,
                ...
            }
        
        Returns:
            float: 新闻情感评分 (0-100)
        """
        if sentiment_data is None:
            # 没有新闻数据，返回中立
            return 50.0
        
        score = sentiment_data.get('sentiment_score_0_100', 50)
        
        # 可选：根据新闻数量调整置信度（新闻越多越有信心）
        news_count = sentiment_data.get('news_count', 0)
        
        return float(score)
    
    def fuse_signals(
        self,
        technical_score: float,
        news_score: float,
        sentiment_data: Optional[Dict] = None,
        indicators: Optional[Dict] = None
    ) -> Dict:
        """
        融合技术信号和新闻信号，生成综合信心度
        
        Args:
            technical_score: 技术信号评分 (0-100)
            news_score: 新闻情感评分 (0-100)
            sentiment_data: 原始情感分析数据（用于报告）
            indicators: 原始技术指标（用于报告）
        
        Returns:
            Dict: {
                'confidence': float (0-100),  # 综合信心度
                'signal': str ('STRONG_BUY', 'BUY', 'HOLD', 'SELL', 'STRONG_SELL'),
                'reasoning': str,  # 详细推理
                'technical_score': float,
                'news_score': float,
                'divergence': str,  # 信号分歧情况
            }
        """
        # 综合信心度
        confidence = (
            technical_score * self.technical_weight +
            news_score * self.news_weight
        )
        confidence = max(0.0, min(100.0, confidence))
        
        # 确定信号
        signal = self._score_to_signal(confidence)
        
        # 分析信号分歧
        divergence = self._analyze_divergence(technical_score, news_score)
        
        # 生成推理说明
        reasoning = self._generate_reasoning(
            signal, confidence, technical_score, news_score,
            divergence, sentiment_data, indicators
        )
        
        return {
            'confidence': confidence,
            'signal': signal,
            'reasoning': reasoning,
            'technical_score': technical_score,
            'news_score': news_score,
            'divergence': divergence,
        }
    
    def _score_to_signal(self, confidence: float) -> str:
        """将信心度转换为信号"""
        if confidence >= 75:
            return 'STRONG_BUY'
        elif confidence >= 60:
            return 'BUY'
        elif confidence >= 40:
            return 'HOLD'
        elif confidence >= 25:
            return 'SELL'
        else:
            return 'STRONG_SELL'
    
    def _analyze_divergence(self, technical_score: float, news_score: float) -> str:
        """
        分析技术信号和新闻信号的分歧
        
        Returns:
            str: 分歧类型
                'aligned_bullish': 技术和新闻都看好
                'aligned_bearish': 技术和新闻都看空
                'aligned_neutral': 技术和新闻都中立
                'tech_bullish_news_bearish': 技术看好但新闻看空（风险）
                'tech_bearish_news_bullish': 技术看空但新闻看好（机会）
        """
        tech_bullish = technical_score > 60
        tech_bearish = technical_score < 40
        
        news_bullish = news_score > 60
        news_bearish = news_score < 40
        
        if tech_bullish and news_bullish:
            return 'aligned_bullish'
        elif tech_bearish and news_bearish:
            return 'aligned_bearish'
        elif not tech_bullish and not tech_bearish and not news_bullish and not news_bearish:
            return 'aligned_neutral'
        elif tech_bullish and news_bearish:
            return 'tech_bullish_news_bearish'
        elif tech_bearish and news_bullish:
            return 'tech_bearish_news_bullish'
        else:
            return 'mixed'
    
    def _generate_reasoning(
        self,
        signal: str,
        confidence: float,
        technical_score: float,
        news_score: float,
        divergence: str,
        sentiment_data: Optional[Dict],
        indicators: Optional[Dict]
    ) -> str:
        """生成详细推理说明"""
        lines = []
        
        # 基础评分说明
        lines.append(
            f"综合信心度 {confidence:.0f}: "
            f"技术信号 {technical_score:.0f} + 新闻情感 {news_score:.0f}"
        )
        
        # 信号分歧分析
        if divergence == 'aligned_bullish':
            lines.append("✅ 技术和新闻信号一致看好")
        elif divergence == 'aligned_bearish':
            lines.append("⛔ 技术和新闻信号一致看空")
        elif divergence == 'tech_bullish_news_bearish':
            lines.append("⚠️ 技术面好但新闻面差（风险警告）")
        elif divergence == 'tech_bearish_news_bullish':
            lines.append("💡 新闻利好但技术面冷淡（观察名单）")
        
        # 技术面细节
        if indicators:
            rsi = indicators.get('rsi', 0)
            if rsi < 30:
                lines.append(f"📊 RSI {rsi:.1f}（超卖，反弹机会）")
            elif rsi > 70:
                lines.append(f"📊 RSI {rsi:.1f}（超买，回调风险）")
            else:
                lines.append(f"📊 RSI {rsi:.1f}（中性区间）")
            
            macd = indicators.get('macd', 0)
            macd_signal = indicators.get('macd_signal', 0)
            if macd > macd_signal:
                lines.append("📈 MACD 金叉（上升动能）")
            elif macd < macd_signal:
                lines.append("📉 MACD 死叉（下跌动能）")
        
        # 新闻面细节
        if sentiment_data:
            avg_sentiment = sentiment_data.get('average_sentiment', 0)
            pos_count = sentiment_data.get('positive_count', 0)
            neg_count = sentiment_data.get('negative_count', 0)
            trend = sentiment_data.get('trend', 'stable')
            
            if pos_count > neg_count:
                lines.append(f"📰 近期新闻偏正面 ({pos_count} 正 {neg_count} 负，{trend})")
            elif neg_count > pos_count:
                lines.append(f"📰 近期新闻偏负面 ({pos_count} 正 {neg_count} 负，{trend})")
            else:
                lines.append(f"📰 新闻信号混合 ({pos_count} 正 {neg_count} 负)")
        
        return " | ".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    fusion = SignalFusion(technical_weight=0.6, news_weight=0.4)
    
    # 测试样本
    indicators = {
        'rsi': 25,
        'sma_20': 150.5,
        'sma_50': 148.0,
        'macd': 2.5,
        'macd_signal': 1.8,
    }
    
    sentiment_data = {
        'sentiment_score_0_100': 75,
        'average_sentiment': 0.5,
        'positive_count': 3,
        'negative_count': 1,
        'neutral_count': 2,
        'trend': 'improving',
        'news_count': 6,
    }
    
    # 计算评分
    tech_score = fusion.calculate_technical_score(indicators)
    news_score = fusion.calculate_news_score(sentiment_data)
    
    print(f"技术信号评分: {tech_score:.0f}")
    print(f"新闻情感评分: {news_score:.0f}")
    
    # 融合
    result = fusion.fuse_signals(tech_score, news_score, sentiment_data, indicators)
    
    print(f"\n综合信心度: {result['confidence']:.0f}")
    print(f"信号: {result['signal']}")
    print(f"分歧: {result['divergence']}")
    print(f"推理: {result['reasoning']}")
