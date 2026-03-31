"""
新闻获取模块
集成 NewsAPI 和 Yahoo Finance 爬取，支持缓存和批量获取
"""

import json
import os
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class NewsFetcher:
    """新闻获取器 - 支持 NewsAPI 和 Yahoo Finance"""
    
    def __init__(self, api_key: Optional[str] = None, cache_dir: str = './data/cache/news'):
        """
        Args:
            api_key: NewsAPI 密钥（从环境变量 NEWSAPI_KEY 读取，或直接传入）
            cache_dir: 缓存目录
        """
        # NewsAPI 密钥
        self.api_key = api_key or os.environ.get('NEWSAPI_KEY', '')
        if not self.api_key:
            logger.warning("NewsAPI_KEY not found. Will try Yahoo Finance fallback.")
        
        self.base_url = "https://newsapi.org/v2"
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_ttl = 3600  # 缓存有效期：1小时
    
    def fetch_news_for_ticker(self, ticker: str, days: int = 1, limit: int = 10) -> List[Dict]:
        """
        获取某只股票的最近新闻
        
        Args:
            ticker: 股票代码 (e.g., 'AAPL')
            days: 获取最近 N 天的新闻
            limit: 最多返回的新闻数
        
        Returns:
            List[Dict]: 新闻列表，每条新闻包含 {
                'title': str,
                'description': str,
                'url': str,
                'published_at': str (ISO 8601),
                'source': str,
                'sentiment': str (由情感分析模块填充，这里为 None)
            }
        """
        # 检查缓存
        cache_key = f"{ticker}_{days}d"
        cached = self._get_cache(cache_key)
        if cached is not None:
            logger.info(f"从缓存获取 {ticker} 的新闻")
            return cached
        
        # 优先使用 NewsAPI
        if self.api_key:
            news = self._fetch_from_newsapi(ticker, days, limit)
            if news:
                self._set_cache(cache_key, news)
                return news
            else:
                logger.warning(f"NewsAPI 返回为空，尝试 Yahoo Finance...")
        
        # 备选：Yahoo Finance 爬取
        news = self._fetch_from_yahoo_finance(ticker, limit)
        if news:
            self._set_cache(cache_key, news)
            return news
        
        logger.warning(f"无法获取 {ticker} 的新闻")
        return []
    
    def _fetch_from_newsapi(self, ticker: str, days: int = 1, limit: int = 10) -> List[Dict]:
        """
        从 NewsAPI 获取新闻
        API 文档：https://newsapi.org/docs
        """
        if not self.api_key:
            logger.warning("NewsAPI key not configured")
            return []
        
        try:
            # 构建查询参数
            from_date = (datetime.utcnow() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            params = {
                'q': ticker,  # 股票代码
                'from': from_date,
                'sortBy': 'publishedAt',  # 按发布时间排序
                'language': 'en',
                'pageSize': min(limit, 100),  # NewsAPI 最多返回 100
                'apiKey': self.api_key
            }
            
            response = requests.get(
                f"{self.base_url}/everything",
                params=params,
                timeout=10
            )
            response.raise_for_status()
            
            data = response.json()
            if data.get('status') != 'ok':
                logger.error(f"NewsAPI error: {data.get('message')}")
                return []
            
            # 处理响应
            articles = data.get('articles', [])
            news = []
            for article in articles[:limit]:
                news.append({
                    'title': article.get('title', ''),
                    'description': article.get('description', ''),
                    'url': article.get('url', ''),
                    'published_at': article.get('publishedAt', ''),
                    'source': article.get('source', {}).get('name', 'Unknown'),
                    'sentiment': None,  # 由情感分析模块填充
                })
            
            logger.info(f"从 NewsAPI 获取 {len(news)} 条 {ticker} 的新闻")
            return news
        
        except requests.RequestException as e:
            logger.error(f"NewsAPI 请求失败: {e}")
            return []
        except Exception as e:
            logger.error(f"处理 NewsAPI 响应出错: {e}")
            return []
    
    def _fetch_from_yahoo_finance(self, ticker: str, limit: int = 10) -> List[Dict]:
        """
        从 Yahoo Finance 爬取新闻（备选方案）
        Yahoo Finance 没有官方 API，但可以通过爬虫获取
        """
        try:
            # 使用简单的爬虫 - 这里我们用 requests 获取页面
            # 实际上可以用 yfinance 库的新闻功能
            import yfinance as yf
            
            ticker_obj = yf.Ticker(ticker)
            # yfinance 有 news 属性
            news_list = ticker_obj.news
            
            if not news_list:
                logger.warning(f"Yahoo Finance 未找到 {ticker} 的新闻")
                return []
            
            news = []
            for item in news_list[:limit]:
                news.append({
                    'title': item.get('title', ''),
                    'description': item.get('summary', ''),  # Yahoo 用 summary 代替 description
                    'url': item.get('link', ''),
                    'published_at': datetime.fromtimestamp(item.get('providerPublishTime', 0)).isoformat(),
                    'source': item.get('publisher', 'Yahoo Finance'),
                    'sentiment': None,
                })
            
            logger.info(f"从 Yahoo Finance 获取 {len(news)} 条 {ticker} 的新闻")
            return news
        
        except ImportError:
            logger.error("yfinance 未安装，无法使用 Yahoo Finance 备选方案")
            return []
        except Exception as e:
            logger.error(f"Yahoo Finance 爬取失败: {e}")
            return []
    
    def _get_cache(self, key: str) -> Optional[List[Dict]]:
        """从缓存获取"""
        cache_file = self.cache_dir / f"{key}.json"
        
        if not cache_file.exists():
            return None
        
        # 检查缓存是否过期
        mtime = cache_file.stat().st_mtime
        if datetime.now().timestamp() - mtime > self.cache_ttl:
            logger.debug(f"缓存已过期: {key}")
            return None
        
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"读取缓存失败: {e}")
            return None
    
    def _set_cache(self, key: str, data: List[Dict]) -> None:
        """写入缓存"""
        cache_file = self.cache_dir / f"{key}.json"
        
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"写入缓存失败: {e}")
    
    def fetch_batch_news(self, tickers: List[str], days: int = 1, limit: int = 10) -> Dict[str, List[Dict]]:
        """
        批量获取多只股票的新闻
        
        Args:
            tickers: 股票代码列表
            days: 获取最近 N 天的新闻
            limit: 每只股票最多返回的新闻数
        
        Returns:
            Dict[ticker, List[news]]
        """
        result = {}
        for ticker in tickers:
            result[ticker] = self.fetch_news_for_ticker(ticker, days, limit)
        
        return result


if __name__ == "__main__":
    # 测试
    logging.basicConfig(level=logging.INFO)
    
    fetcher = NewsFetcher()
    
    # 获取 AAPL 的新闻
    news = fetcher.fetch_news_for_ticker('AAPL', days=1, limit=5)
    
    for item in news:
        print(f"\n{item['title']}")
        print(f"来源: {item['source']}")
        print(f"时间: {item['published_at']}")
        print(f"链接: {item['url']}")
