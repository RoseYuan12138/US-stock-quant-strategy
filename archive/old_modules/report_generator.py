"""
增强的报告生成器
将新闻和技术信号融合，生成美观易读的日报
"""

from datetime import datetime
from typing import Dict, List


class EnhancedReportGenerator:
    """增强的日报生成器"""
    
    def __init__(self):
        self.report_date = datetime.now()
    
    def generate_report(self, signals_dict: Dict) -> str:
        """
        生成增强的日报
        
        Args:
            signals_dict: {ticker: signal_info}
        
        Returns:
            str: 格式化的报告文本
        """
        sections = {
            'strong_buy': [],
            'buy': [],
            'hold': [],
            'sell': [],
            'strong_sell': [],
            'divergence_tech_good': [],  # 技术好但新闻差
            'divergence_news_good': [],  # 新闻好但技术差
        }
        
        # 分类
        for ticker, info in signals_dict.items():
            if info.get('status') != 'OK':
                continue
            
            fusion = info.get('fusion', {})
            signal = fusion.get('signal', 'HOLD')
            divergence = fusion.get('divergence', '')
            
            if divergence == 'tech_bullish_news_bearish':
                sections['divergence_tech_good'].append((ticker, info))
            elif divergence == 'tech_bearish_news_bullish':
                sections['divergence_news_good'].append((ticker, info))
            elif signal == 'STRONG_BUY':
                sections['strong_buy'].append((ticker, info))
            elif signal == 'BUY':
                sections['buy'].append((ticker, info))
            elif signal == 'HOLD':
                sections['hold'].append((ticker, info))
            elif signal == 'SELL':
                sections['sell'].append((ticker, info))
            elif signal == 'STRONG_SELL':
                sections['strong_sell'].append((ticker, info))
        
        # 生成报告
        lines = [
            "=" * 80,
            f"📊 美股量化交易信号日报",
            f"技术指标 + 新闻情感融合",
            f"时间: {self.report_date.strftime('%Y-%m-%d %H:%M:%S')} (US/Pacific)",
            "=" * 80,
            ""
        ]
        
        # 【强买信号】
        if sections['strong_buy']:
            lines.append("┌" + "─" * 78 + "┐")
            lines.append("│ 🚀 【强买信号】- 技术 + 新闻完全一致看好")
            lines.append("└" + "─" * 78 + "┘")
            for ticker, info in sections['strong_buy']:
                self._add_signal_block(lines, ticker, info)
        
        # 【买入信号】
        if sections['buy']:
            lines.append("┌" + "─" * 78 + "┐")
            lines.append("│ 💚 【买入信号】- 综合信心度较高")
            lines.append("└" + "─" * 78 + "┘")
            for ticker, info in sections['buy']:
                self._add_signal_block(lines, ticker, info)
        
        # 【风险警告：技术好但新闻差】
        if sections['divergence_tech_good']:
            lines.append("┌" + "─" * 78 + "┐")
            lines.append("│ ⚠️  【技术面好但新闻面差】- 谨慎介入")
            lines.append("└" + "─" * 78 + "┘")
            for ticker, info in sections['divergence_tech_good']:
                self._add_signal_block(lines, ticker, info, brief=False)
        
        # 【观察名单：新闻好但技术差】
        if sections['divergence_news_good']:
            lines.append("┌" + "─" * 78 + "┐")
            lines.append("│ 💡 【新闻面好但技术冷淡】- 观察名单")
            lines.append("└" + "─" * 78 + "┘")
            for ticker, info in sections['divergence_news_good']:
                self._add_signal_block(lines, ticker, info, brief=False)
        
        # 【持有观望】
        if sections['hold']:
            lines.append("┌" + "─" * 78 + "┐")
            lines.append("│ ⏸️  【持有观望】- 等待更清晰的信号")
            lines.append("└" + "─" * 78 + "┘")
            for ticker, info in sections['hold'][:5]:  # 最多显示 5 只
                self._add_signal_block(lines, ticker, info, brief=True)
        
        # 【卖出信号】
        if sections['sell']:
            lines.append("┌" + "─" * 78 + "┐")
            lines.append("│ 📉 【卖出信号】- 综合信心度较低")
            lines.append("└" + "─" * 78 + "┘")
            for ticker, info in sections['sell']:
                self._add_signal_block(lines, ticker, info)
        
        # 【强卖信号】
        if sections['strong_sell']:
            lines.append("┌" + "─" * 78 + "┐")
            lines.append("│ 🔴 【强卖信号】- 技术 + 新闻完全一致看空")
            lines.append("└" + "─" * 78 + "┘")
            for ticker, info in sections['strong_sell']:
                self._add_signal_block(lines, ticker, info)
        
        # 底部说明
        lines.append("")
        lines.append("=" * 80)
        lines.append("📌 说明:")
        lines.append("  • 综合信心度 = 技术信号评分 60% + 新闻情感评分 40%")
        lines.append("  • 只输出综合信心度 > 70% 的强信号")
        lines.append("  • 数据来源: YFinance (价格) | NewsAPI/Yahoo Finance (新闻)")
        lines.append("  • 这是辅助工具，不构成投资建议，请做自己的调查")
        lines.append("=" * 80)
        
        return "\n".join(lines)
    
    def _add_signal_block(self, lines: List[str], ticker: str, info: Dict, brief: bool = False):
        """添加单只股票的信号块"""
        fusion = info.get('fusion', {})
        indicators = info.get('indicators', {})
        sentiment = info.get('sentiment', {})
        
        # 头部
        confidence = fusion.get('confidence', 0)
        signal = fusion.get('signal', 'UNKNOWN')
        emoji_map = {
            'STRONG_BUY': '🟢',
            'BUY': '💚',
            'HOLD': '⏸️',
            'SELL': '📉',
            'STRONG_SELL': '🔴',
        }
        emoji = emoji_map.get(signal, '❓')
        
        price = info['latest_price']
        change_pct = ""  # 可选：添加涨跌幅
        
        lines.append(f"  {emoji} {ticker:6s} ${price:8.2f}  {change_pct:>8s}  信心度 {confidence:5.0f}%")
        
        if not brief:
            # 技术面
            if indicators:
                rsi = indicators.get('rsi', 0)
                sma_20 = indicators.get('sma_20', 0)
                sma_50 = indicators.get('sma_50', 0)
                
                if sma_20 > sma_50:
                    trend = "📈 向上"
                elif sma_20 < sma_50:
                    trend = "📉 向下"
                else:
                    trend = "➡️ 平横"
                
                rsi_status = ""
                if rsi < 30:
                    rsi_status = "(超卖)"
                elif rsi > 70:
                    rsi_status = "(超买)"
                
                lines.append(f"    技术: RSI {rsi:5.1f}{rsi_status:8s} | SMA20/50 {trend:8s}")
            
            # 新闻面
            if sentiment and sentiment.get('news_count', 0) > 0:
                pos = sentiment.get('positive_count', 0)
                neg = sentiment.get('negative_count', 0)
                neu = sentiment.get('neutral_count', 0)
                trend = sentiment.get('trend', 'stable')
                score = sentiment.get('sentiment_score_0_100', 50)
                
                trend_emoji = '📈' if trend == 'improving' else ('📉' if trend == 'declining' else '➡️')
                
                lines.append(
                    f"    新闻: {pos:2d}正 {neg:2d}负 {neu:2d}中 {trend_emoji} ({trend:10s}) | 情感评分 {score:3d}%"
                )
            
            # 价格目标
            target = info.get('target', 0)
            stop_loss = info.get('stop_loss', 0)
            lines.append(f"    目标: ${target:8.2f}  |  止损: ${stop_loss:8.2f}")
            
            # 推理
            reasoning = fusion.get('reasoning', '')
            if reasoning:
                lines.append(f"    推理: {reasoning}")
        
        lines.append("")


if __name__ == "__main__":
    # 测试
    test_signals = {
        'AAPL': {
            'status': 'OK',
            'latest_price': 250.5,
            'fusion': {
                'confidence': 85,
                'signal': 'STRONG_BUY',
                'divergence': 'aligned_bullish',
                'reasoning': 'RSI 超卖 + 新闻利好'
            },
            'indicators': {
                'rsi': 25,
                'sma_20': 248.0,
                'sma_50': 245.0,
            },
            'sentiment': {
                'news_count': 5,
                'positive_count': 4,
                'negative_count': 1,
                'neutral_count': 0,
                'sentiment_score_0_100': 80,
                'trend': 'improving',
            },
            'target': 260,
            'stop_loss': 245,
        },
    }
    
    generator = EnhancedReportGenerator()
    report = generator.generate_report(test_signals)
    print(report)
