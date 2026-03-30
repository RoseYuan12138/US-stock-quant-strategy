"""
实时新闻情绪分析 — 使用 Haiku
数据源: yfinance ticker.news (免费)
分析: Claude Haiku 3.5 (每天 <$0.01)

用法:
    scorer = LiveNewsScorer(api_key="sk-ant-...")
    result = scorer.score_ticker("AAPL")
    # {'sentiment': 0.6, 'news_score': 8.0, 'news_count': 5, 'headlines': [...]}
"""

import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class LiveNewsScorer:
    """
    实时新闻情绪评分

    用 yfinance 获取最近新闻，用 Haiku 分析情绪。
    每天 S&P 100 大约 50-100 条新闻，成本 < $0.01/天。
    """

    def __init__(self, api_key=None, cache_dir="./data/cache/live_news"):
        """
        Args:
            api_key: Anthropic API key (或从环境变量 ANTHROPIC_API_KEY 读取)
            cache_dir: 缓存目录（避免重复调用 API）
        """
        self.api_key = api_key or os.environ.get('ANTHROPIC_API_KEY', '')
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = None

    def _get_client(self):
        """懒加载 Anthropic client"""
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                raise ImportError("需要安装 anthropic: pip install anthropic")
        return self._client

    def fetch_news(self, ticker, max_items=20):
        """
        从 yfinance 获取最近新闻

        Returns:
            list of dict: [{'title': str, 'publisher': str, 'date': str}, ...]
        """
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            news = t.news or []

            results = []
            for item in news[:max_items]:
                title = item.get('title', '')
                publisher = item.get('publisher', '')
                pub_date = ''
                if 'providerPublishTime' in item:
                    pub_date = datetime.fromtimestamp(
                        item['providerPublishTime']
                    ).strftime('%Y-%m-%d %H:%M')

                if title:
                    results.append({
                        'title': title,
                        'publisher': publisher,
                        'date': pub_date,
                    })

            return results

        except Exception as e:
            logger.warning(f"{ticker}: 新闻获取失败: {e}")
            return []

    def score_with_haiku(self, headlines, ticker):
        """
        用 Haiku 批量分析新闻标题情绪

        Args:
            headlines: list of str
            ticker: 股票代码（提供上下文）

        Returns:
            list of float: 每条标题的情绪分 (-1.0 ~ +1.0)
        """
        if not headlines:
            return []

        # 检查今日缓存
        cache_file = self.cache_dir / f"{ticker}_{datetime.now().strftime('%Y%m%d')}.json"
        if cache_file.exists():
            try:
                with open(cache_file) as f:
                    cached = json.load(f)
                if cached.get('headlines') == headlines:
                    return cached['scores']
            except Exception:
                pass

        # 构建 prompt — 批量处理所有标题
        headlines_text = "\n".join(
            f"{i+1}. {h}" for i, h in enumerate(headlines)
        )

        prompt = f"""Rate the financial sentiment of each headline for stock {ticker}.
Score each from -1.0 (very negative) to +1.0 (very positive). 0 = neutral.

Headlines:
{headlines_text}

Respond with ONLY a JSON array of numbers, one per headline. Example: [-0.5, 0.8, 0.0]"""

        try:
            client = self._get_client()
            response = client.messages.create(
                model="claude-haiku-4-20250414",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )

            # 解析响应
            text = response.content[0].text.strip()
            # 提取 JSON 数组
            if '[' in text:
                json_str = text[text.index('['):text.rindex(']')+1]
                scores = json.loads(json_str)
                scores = [max(-1.0, min(1.0, float(s))) for s in scores]
            else:
                scores = [0.0] * len(headlines)

            # 缓存
            with open(cache_file, 'w') as f:
                json.dump({'headlines': headlines, 'scores': scores,
                          'ticker': ticker, 'date': datetime.now().isoformat()}, f)

            return scores

        except Exception as e:
            logger.warning(f"Haiku 分析失败: {e}")
            # fallback 到关键词方法
            return self._keyword_fallback(headlines)

    def _keyword_fallback(self, headlines):
        """关键词方法作为 fallback"""
        from data.historical_news import FinancialSentimentScorer
        scorer = FinancialSentimentScorer()
        return [scorer.score_headline(h) for h in headlines]

    def score_ticker(self, ticker):
        """
        对单只股票做实时新闻情绪评分

        Returns:
            dict: {
                'news_sentiment': float (-1 ~ +1),
                'news_score': float (0 ~ 10),
                'news_count': int,
                'headlines': list of {title, sentiment},
                'data_available': bool,
            }
        """
        news = self.fetch_news(ticker)

        if not news:
            return {
                'news_sentiment': 0.0,
                'news_score': 5.0,
                'news_count': 0,
                'headlines': [],
                'data_available': False,
            }

        headlines = [n['title'] for n in news]

        # 用 Haiku 评分（如果有 API key），否则用关键词
        if self.api_key:
            scores = self.score_with_haiku(headlines, ticker)
        else:
            scores = self._keyword_fallback(headlines)

        # 聚合
        non_zero = [s for s in scores if abs(s) > 0.05]
        avg_sentiment = sum(non_zero) / len(non_zero) if non_zero else 0.0

        # 映射到 0-10
        news_score = 5.0 + avg_sentiment * 5.0
        news_score = max(0.0, min(10.0, news_score))

        # 新闻太少拉向中性
        if len(non_zero) < 3:
            news_score = 5.0 + (news_score - 5.0) * 0.5

        # 标题+分数明细
        headline_details = [
            {'title': h, 'sentiment': round(s, 2), 'publisher': n.get('publisher', ''), 'date': n.get('date', '')}
            for h, s, n in zip(headlines, scores, news)
        ]

        return {
            'news_sentiment': round(avg_sentiment, 4),
            'news_score': round(news_score, 2),
            'news_count': len(headlines),
            'headlines': headline_details,
            'data_available': True,
        }

    def score_universe(self, tickers):
        """
        对一组 ticker 做实时新闻情绪评分

        Returns:
            dict: {ticker: score_dict}
        """
        results = {}
        for ticker in tickers:
            results[ticker] = self.score_ticker(ticker)
        return results

    def format_for_telegram(self, ticker, score_result):
        """格式化为 Telegram 消息"""
        if not score_result['data_available']:
            return f"{ticker}: 无新闻数据"

        sentiment = score_result['news_sentiment']
        emoji = "🟢" if sentiment > 0.2 else ("🔴" if sentiment < -0.2 else "⚪")

        lines = [f"{emoji} <b>{ticker}</b> 新闻情绪: {sentiment:+.2f} ({score_result['news_count']}条)"]

        # 前 3 条重要新闻
        sorted_headlines = sorted(
            score_result['headlines'],
            key=lambda x: abs(x['sentiment']),
            reverse=True
        )
        for h in sorted_headlines[:3]:
            h_emoji = "📈" if h['sentiment'] > 0.1 else ("📉" if h['sentiment'] < -0.1 else "➡️")
            lines.append(f"  {h_emoji} {h['title'][:60]}...")

        return "\n".join(lines)
