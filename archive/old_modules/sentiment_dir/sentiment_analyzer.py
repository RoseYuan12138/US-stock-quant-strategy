"""
情感分析模块
使用 Claude Haiku 进行金融新闻事件分析

替代原 TextBlob 方案：
- TextBlob: 通用NLP，不懂金融语境，只输出 polarity
- Haiku: 理解金融事件含义，输出结构化事件分类 + 严重等级 + 建议行动

核心定位：事件驱动的风控工具，不是每日情感打分器
"""

import os
import json
import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Haiku 分析的 system prompt
SYSTEM_PROMPT = """You are a financial news analyst. Analyze the given news headline and description for a specific stock.

Return a JSON object with these fields:
- event_type: one of ["earnings_beat", "earnings_miss", "guidance_up", "guidance_down", "upgrade", "downgrade", "partnership", "acquisition", "lawsuit", "sec_investigation", "management_change", "layoff", "product_launch", "product_recall", "macro_positive", "macro_negative", "sector_rotation", "neutral", "other"]
- severity: one of ["critical", "high", "medium", "low", "negligible"]
  - critical: material impact likely (SEC investigation, earnings miss >20%, bankruptcy risk)
  - high: significant price impact expected (earnings miss/beat >10%, major lawsuit)
  - medium: moderate impact (analyst upgrade/downgrade, partnerships)
  - low: minor or expected news
  - negligible: noise, not actionable
- sentiment: float from -1.0 (very negative) to 1.0 (very positive)
- action: one of ["review_position", "hold", "ignore"]
  - review_position: human should review this, potential risk or opportunity
  - hold: stay the course, no action needed
  - ignore: noise, skip
- summary: one sentence summary of why this matters (max 20 words)
- confidence: float from 0.0 to 1.0

Return ONLY valid JSON, no markdown or explanation."""


class SentimentAnalyzer:
    """
    金融新闻事件分析器

    Primary: Claude Haiku API（高精度，每条 ~$0.0001）
    Fallback: 关键词匹配（离线可用，低精度）
    """

    # 关键词匹配作为 fallback
    POSITIVE_KEYWORDS = {
        'beat': 0.15, 'beats': 0.15, 'exceeded': 0.12,
        'bullish': 0.12, 'surge': 0.10, 'surges': 0.10,
        'rally': 0.10, 'upgrade': 0.12, 'upgraded': 0.12,
        'outperform': 0.10, 'growth': 0.08, 'record': 0.08,
        'breakthrough': 0.15, 'approved': 0.12, 'partnership': 0.08,
        'acquisition': 0.08, 'strong': 0.08, 'profit': 0.08,
    }

    NEGATIVE_KEYWORDS = {
        'miss': -0.15, 'misses': -0.15, 'missed': -0.15,
        'bearish': -0.12, 'collapse': -0.15, 'plunge': -0.12,
        'decline': -0.08, 'bankruptcy': -0.20, 'downgrade': -0.12,
        'downgraded': -0.12, 'underperform': -0.10, 'lawsuit': -0.12,
        'investigation': -0.15, 'recall': -0.12, 'layoff': -0.10,
        'layoffs': -0.10, 'warning': -0.10, 'fraud': -0.20,
        'scandal': -0.15, 'sec': -0.12, 'weak': -0.08,
    }

    CRITICAL_KEYWORDS = {'sec', 'fraud', 'bankruptcy', 'investigation', 'scandal'}

    def __init__(self, use_haiku=True):
        """
        Args:
            use_haiku: 是否使用 Haiku API（需要 ANTHROPIC_API_KEY）
        """
        self.use_haiku = use_haiku
        self.client = None

        if use_haiku:
            api_key = os.environ.get('ANTHROPIC_API_KEY')
            if api_key:
                try:
                    import anthropic
                    self.client = anthropic.Anthropic(api_key=api_key)
                    logger.info("Haiku sentiment analyzer initialized")
                except ImportError:
                    logger.warning("anthropic package not installed. pip install anthropic")
                    self.client = None
            else:
                logger.warning("ANTHROPIC_API_KEY not set. Falling back to keyword analysis.")

    def analyze_single_news(self, title: str, description: str = '',
                            ticker: str = '') -> Dict:
        """
        分析单条新闻

        Args:
            title: 新闻标题
            description: 新闻描述
            ticker: 相关股票代码

        Returns:
            Dict: {
                'event_type': str,
                'severity': str,
                'sentiment': float (-1.0 ~ 1.0),
                'action': str,
                'summary': str,
                'confidence': float,
                'source': 'haiku' | 'keyword_fallback',
                # 兼容旧接口
                'polarity': float,
                'label': str,
            }
        """
        if self.client:
            result = self._analyze_with_haiku(title, description, ticker)
            if result:
                return result

        # Fallback: 关键词分析
        return self._analyze_with_keywords(title, description)

    def analyze_batch_news(self, news_list: List[Dict], ticker: str = '') -> List[Dict]:
        """
        批量分析新闻

        Args:
            news_list: [{'title': str, 'description': str, ...}]
            ticker: 股票代码

        Returns:
            List[Dict]: 每条新闻添加 'sentiment' 字段
        """
        analyzed = []
        for news in news_list:
            sentiment = self.analyze_single_news(
                news.get('title', ''),
                news.get('description', ''),
                ticker=ticker,
            )
            news['sentiment'] = sentiment
            analyzed.append(news)
        return analyzed

    def aggregate_sentiment(self, news_list: List[Dict], hours: int = 24) -> Dict:
        """
        聚合新闻情感，计算综合得分
        保持与旧接口兼容

        Returns:
            Dict: {
                'average_sentiment': float,
                'sentiment_score_0_100': int,
                'positive_count': int,
                'negative_count': int,
                'neutral_count': int,
                'trend': str,
                'news_count': int,
                'critical_events': list,  # 新增：严重事件列表
                'action_required': bool,  # 新增：是否需要人工审查
            }
        """
        if not news_list:
            return self._default_aggregate()

        sentiments = [n.get('sentiment', {}) for n in news_list]
        polarities = [s.get('polarity', s.get('sentiment', 0)) for s in sentiments]

        average = sum(polarities) / len(polarities) if polarities else 0
        score_0_100 = int((average + 1) / 2 * 100)

        positive_count = sum(1 for p in polarities if p > 0.1)
        negative_count = sum(1 for p in polarities if p < -0.1)
        neutral_count = len(polarities) - positive_count - negative_count

        # 趋势
        mid = len(polarities) // 2
        if mid > 0:
            early = sum(polarities[:mid]) / mid
            late = sum(polarities[mid:]) / len(polarities[mid:])
            if late > early + 0.1:
                trend = 'improving'
            elif late < early - 0.1:
                trend = 'declining'
            else:
                trend = 'stable'
        else:
            trend = 'stable'

        # 严重事件检测
        critical_events = []
        action_required = False
        for s in sentiments:
            severity = s.get('severity', 'negligible')
            if severity in ('critical', 'high'):
                critical_events.append({
                    'event_type': s.get('event_type', 'unknown'),
                    'severity': severity,
                    'summary': s.get('summary', ''),
                    'action': s.get('action', 'hold'),
                })
                if s.get('action') == 'review_position':
                    action_required = True

        return {
            'average_sentiment': average,
            'sentiment_score_0_100': score_0_100,
            'positive_count': positive_count,
            'negative_count': negative_count,
            'neutral_count': neutral_count,
            'trend': trend,
            'news_count': len(news_list),
            'critical_events': critical_events,
            'action_required': action_required,
        }

    def _analyze_with_haiku(self, title: str, description: str,
                            ticker: str) -> Optional[Dict]:
        """使用 Haiku API 分析"""
        try:
            user_msg = f"Stock: {ticker}\nHeadline: {title}"
            if description:
                user_msg += f"\nDescription: {description}"

            response = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )

            text = response.content[0].text.strip()

            # 清理可能的 markdown 包裹
            if text.startswith('```'):
                text = text.split('\n', 1)[1] if '\n' in text else text[3:]
                if text.endswith('```'):
                    text = text[:-3]
                text = text.strip()

            result = json.loads(text)

            # 标准化输出
            sentiment_val = float(result.get('sentiment', 0))
            return {
                'event_type': result.get('event_type', 'other'),
                'severity': result.get('severity', 'low'),
                'sentiment': sentiment_val,
                'action': result.get('action', 'hold'),
                'summary': result.get('summary', ''),
                'confidence': float(result.get('confidence', 0.5)),
                'source': 'haiku',
                # 兼容旧接口
                'polarity': sentiment_val,
                'label': 'Positive' if sentiment_val > 0.1 else ('Negative' if sentiment_val < -0.1 else 'Neutral'),
                'subjectivity': 0.5,
                'keywords_boost': 0.0,
            }

        except json.JSONDecodeError as e:
            logger.warning(f"Haiku response not valid JSON: {e}")
            return None
        except Exception as e:
            logger.warning(f"Haiku analysis failed: {e}")
            return None

    def _analyze_with_keywords(self, title: str, description: str) -> Dict:
        """关键词匹配 fallback（离线可用）"""
        text = f"{title} {description}".lower()

        boost = 0.0
        for keyword, weight in self.POSITIVE_KEYWORDS.items():
            if keyword in text:
                boost += weight
        for keyword, weight in self.NEGATIVE_KEYWORDS.items():
            if keyword in text:
                boost += weight

        boost = max(-0.8, min(0.8, boost))

        # 检查严重关键词
        severity = 'low'
        action = 'hold'
        event_type = 'other'

        for kw in self.CRITICAL_KEYWORDS:
            if kw in text:
                severity = 'high'
                action = 'review_position'
                break

        if boost > 0.1:
            label = 'Positive'
            event_type = 'neutral'  # 关键词无法精确判断事件类型
        elif boost < -0.1:
            label = 'Negative'
        else:
            label = 'Neutral'

        return {
            'event_type': event_type,
            'severity': severity,
            'sentiment': boost,
            'action': action,
            'summary': 'Keyword-based analysis (Haiku unavailable)',
            'confidence': 0.3,  # 关键词分析低置信度
            'source': 'keyword_fallback',
            # 兼容旧接口
            'polarity': boost,
            'label': label,
            'subjectivity': 0.5,
            'keywords_boost': boost,
        }

    def _default_aggregate(self) -> Dict:
        return {
            'average_sentiment': 0,
            'sentiment_score_0_100': 50,
            'positive_count': 0,
            'negative_count': 0,
            'neutral_count': 0,
            'trend': 'stable',
            'news_count': 0,
            'critical_events': [],
            'action_required': False,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    analyzer = SentimentAnalyzer()

    test_news = [
        {
            'title': 'Apple beats Q1 earnings expectations with record revenue',
            'description': 'Apple exceeded analyst expectations in Q1 with strong iPhone sales.'
        },
        {
            'title': 'SEC launches investigation into Tesla accounting practices',
            'description': 'The Securities and Exchange Commission has opened a formal investigation.'
        },
        {
            'title': 'Microsoft announces new partnership with Google on AI',
            'description': 'Tech companies to collaborate on enterprise AI infrastructure.'
        },
    ]

    print("Testing sentiment analyzer...\n")

    for news in test_news:
        result = analyzer.analyze_single_news(
            news['title'], news['description'], ticker='TEST'
        )
        print(f"Title: {news['title']}")
        print(f"  Source:    {result['source']}")
        print(f"  Event:    {result['event_type']}")
        print(f"  Severity: {result['severity']}")
        print(f"  Sentiment:{result['sentiment']:+.2f}")
        print(f"  Action:   {result['action']}")
        print(f"  Summary:  {result['summary']}")
        print()

    # 聚合
    analyzed = analyzer.analyze_batch_news(test_news, ticker='TEST')
    agg = analyzer.aggregate_sentiment(analyzed)
    print(f"Aggregate: score={agg['sentiment_score_0_100']}, "
          f"trend={agg['trend']}, "
          f"critical={len(agg['critical_events'])}, "
          f"action_required={agg['action_required']}")
