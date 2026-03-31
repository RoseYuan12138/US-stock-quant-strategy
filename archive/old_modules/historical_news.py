"""
历史新闻情绪模块
数据源: HuggingFace datasets (FNSPID + ashraq/financial-news)
用途: 回测时提供历史新闻情绪评分

方法:
- 基于金融情绪词典的关键词评分 (Loughran-McDonald 风格)
- 不需要 LLM API，可以快速处理百万级标题
- 每个 ticker 在给定日期前 N 天的新闻标题做聚合情绪
"""

import logging
import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# 金融情绪词典 (Loughran-McDonald 风格精简版)
POSITIVE_WORDS = {
    # 财务正面
    'beat', 'beats', 'exceeded', 'exceeds', 'surpass', 'surpasses', 'surpassed',
    'outperform', 'outperforms', 'outperformed',
    'upgrade', 'upgrades', 'upgraded', 'upside', 'bullish',
    'profit', 'profitable', 'profitability',
    'growth', 'growing', 'grew', 'expand', 'expansion', 'expanding',
    'record', 'records', 'high', 'highs', 'highest', 'peak',
    'strong', 'stronger', 'strongest', 'strength',
    'gain', 'gains', 'gained', 'rally', 'rallies', 'rallied',
    'surge', 'surges', 'surged', 'soar', 'soars', 'soared',
    'jump', 'jumps', 'jumped', 'rise', 'rises', 'risen', 'rose',
    'boost', 'boosts', 'boosted',
    'improve', 'improves', 'improved', 'improvement',
    'positive', 'optimistic', 'optimism', 'confidence', 'confident',
    'dividend', 'buyback', 'repurchase',
    'innovation', 'breakthrough', 'launch', 'launches', 'launched',
    'approval', 'approved', 'win', 'wins', 'won', 'award',
    'recovery', 'recover', 'recovers', 'recovered', 'rebound', 'rebounds',
    'top', 'tops', 'topped', 'above',
}

NEGATIVE_WORDS = {
    # 财务负面
    'miss', 'misses', 'missed', 'below', 'under', 'underperform',
    'downgrade', 'downgrades', 'downgraded', 'downside', 'bearish',
    'loss', 'losses', 'lose', 'losing', 'lost',
    'decline', 'declines', 'declined', 'declining',
    'drop', 'drops', 'dropped', 'dropping',
    'fall', 'falls', 'fell', 'fallen', 'falling',
    'weak', 'weaker', 'weakest', 'weakness',
    'slump', 'slumps', 'slumped', 'plunge', 'plunges', 'plunged',
    'crash', 'crashes', 'crashed', 'tumble', 'tumbles', 'tumbled',
    'cut', 'cuts', 'slash', 'slashes', 'slashed',
    'layoff', 'layoffs', 'restructuring', 'restructure',
    'lawsuit', 'sue', 'sued', 'sues', 'fine', 'fined', 'penalty',
    'recall', 'recalls', 'recalled', 'warning', 'warn', 'warns', 'warned',
    'fraud', 'scandal', 'investigation', 'probe', 'subpoena',
    'bankruptcy', 'default', 'defaults', 'debt',
    'risk', 'risks', 'risky', 'concern', 'concerns', 'worried', 'worry',
    'negative', 'pessimistic', 'fear', 'fears', 'uncertainty',
    'suspend', 'suspends', 'suspended', 'halt', 'halts', 'halted',
    'short', 'shorts', 'shorting',  # short selling context
    'sell', 'selloff', 'selling',
}

# 强信号词 (权重 x2)
STRONG_POSITIVE = {
    'beat', 'beats', 'exceeded', 'surpass', 'surpassed', 'record',
    'upgrade', 'upgraded', 'breakthrough', 'approval', 'approved',
    'surge', 'surged', 'soar', 'soared', 'buyback',
}

STRONG_NEGATIVE = {
    'miss', 'missed', 'downgrade', 'downgraded', 'fraud', 'scandal',
    'bankruptcy', 'crash', 'crashed', 'plunge', 'plunged',
    'lawsuit', 'investigation', 'recall', 'recalled',
}


class FinancialSentimentScorer:
    """基于金融词典的标题情绪评分"""

    def score_headline(self, headline):
        """
        对单条标题评分

        Returns:
            float: -1.0 (极负) ~ +1.0 (极正), 0 = 中性
        """
        if not headline or not isinstance(headline, str):
            return 0.0

        words = set(headline.lower().split())

        pos_score = 0
        neg_score = 0

        for w in words:
            if w in POSITIVE_WORDS:
                pos_score += 2 if w in STRONG_POSITIVE else 1
            if w in NEGATIVE_WORDS:
                neg_score += 2 if w in STRONG_NEGATIVE else 1

        total = pos_score + neg_score
        if total == 0:
            return 0.0

        # 归一化到 [-1, 1]
        raw = (pos_score - neg_score) / total
        return max(-1.0, min(1.0, raw))

    def score_headlines(self, headlines):
        """对一组标题评分，返回聚合情绪"""
        if not headlines:
            return 0.0
        scores = [self.score_headline(h) for h in headlines]
        # 过滤中性
        non_zero = [s for s in scores if s != 0]
        if not non_zero:
            return 0.0
        return np.mean(non_zero)


class HistoricalNewsProvider:
    """
    历史新闻数据提供器

    从 HuggingFace 下载并缓存新闻数据,
    按 ticker + 日期提供标题
    """

    def __init__(self, cache_dir="./data/cache/news"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._data = {}  # ticker -> DataFrame(date, headline)
        self._loaded = False
        self._sentiment = FinancialSentimentScorer()

    def load_data(self, tickers=None, force=False):
        """
        加载新闻数据（从缓存或下载）

        Args:
            tickers: 需要加载的 ticker 列表 (None = 全部)
            force: 强制重新下载
        """
        index_file = self.cache_dir / "news_index.json"

        if not force and index_file.exists():
            # 从本地缓存加载
            try:
                with open(index_file, 'r') as f:
                    meta = json.load(f)
                loaded_count = 0
                for ticker in (tickers or meta.get('tickers', [])):
                    ticker = ticker.upper()
                    ticker_file = self.cache_dir / f"{ticker}.parquet"
                    if ticker_file.exists():
                        df = pd.read_parquet(ticker_file)
                        df['date'] = pd.to_datetime(df['date'])
                        self._data[ticker] = df
                        loaded_count += 1
                if loaded_count > 0:
                    self._loaded = True
                    logger.info(f"从缓存加载 {loaded_count} 个 ticker 的新闻数据")
                    print(f"  新闻缓存: {loaded_count} tickers")
                    return
            except Exception as e:
                logger.warning(f"缓存加载失败: {e}")

        # 从 HuggingFace 下载
        self._download_and_cache(tickers)

    def _download_and_cache(self, tickers=None):
        """从 HuggingFace 下载新闻数据"""
        if tickers:
            target_tickers = {t.upper() for t in tickers}
        else:
            target_tickers = None

        all_records = {}  # ticker -> list of {date, headline}

        # Dataset 1: ashraq/financial-news (主力数据源，小巧快速)
        print("  下载 ashraq/financial-news...")
        try:
            from datasets import load_dataset
            ds = load_dataset('ashraq/financial-news', split='train', streaming=True)

            count = 0
            for row in ds:
                ticker = row.get('stock', '').upper()
                if target_tickers and ticker not in target_tickers:
                    continue

                headline = row.get('headline', '')
                date_str = row.get('date', '')

                if not headline or not date_str or not ticker:
                    continue

                try:
                    date = pd.Timestamp(date_str).tz_localize(None).normalize()
                except Exception:
                    try:
                        date = pd.Timestamp(date_str).normalize()
                    except Exception:
                        continue

                if ticker not in all_records:
                    all_records[ticker] = []
                all_records[ticker].append({
                    'date': date,
                    'headline': headline,
                })
                count += 1

                if count % 100000 == 0:
                    print(f"    ashraq: {count:,} 条...")

            print(f"    ashraq 完成: {count:,} 条")

        except Exception as e:
            logger.warning(f"ashraq 下载失败: {e}")
            print(f"    ashraq 失败: {e}")

        # 保存到 parquet
        saved = 0
        for ticker, records in all_records.items():
            df = pd.DataFrame(records)
            df = df.drop_duplicates(subset=['date', 'headline'])
            df = df.sort_values('date').reset_index(drop=True)
            df.to_parquet(self.cache_dir / f"{ticker}.parquet", index=False)
            self._data[ticker] = df
            saved += 1

        # 保存索引
        with open(self.cache_dir / "news_index.json", 'w') as f:
            json.dump({
                'tickers': list(all_records.keys()),
                'total_records': sum(len(v) for v in all_records.values()),
                'fetch_date': datetime.now().isoformat(),
            }, f, indent=2)

        self._loaded = True
        print(f"  新闻数据保存完成: {saved} tickers, "
              f"{sum(len(v) for v in all_records.values()):,} 条")

    def get_news(self, ticker, start_date, end_date):
        """获取指定 ticker 在日期范围内的新闻标题"""
        ticker = ticker.upper()
        if ticker not in self._data:
            return []

        df = self._data[ticker]
        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date)
        mask = (df['date'] >= start) & (df['date'] <= end)
        return df.loc[mask, 'headline'].tolist()

    def score_at_date(self, ticker, target_date, lookback_days=30):
        """
        计算截至 target_date 前 lookback_days 天的新闻情绪评分

        Returns:
            dict: {
                'news_sentiment': float (-1 ~ +1),
                'news_count': int,
                'news_score': float (0-10, 用于投资组合评分),
                'data_available': bool,
            }
        """
        ticker = ticker.upper()

        if ticker not in self._data or self._data[ticker].empty:
            return {
                'news_sentiment': 0.0,
                'news_count': 0,
                'news_score': 5.0,  # 中性默认
                'data_available': False,
            }

        if isinstance(target_date, str):
            target_date = pd.Timestamp(target_date)

        start = target_date - timedelta(days=lookback_days)
        headlines = self.get_news(ticker, start, target_date)

        if not headlines:
            return {
                'news_sentiment': 0.0,
                'news_count': 0,
                'news_score': 5.0,
                'data_available': True,  # 有数据但该期间无新闻
            }

        sentiment = self._sentiment.score_headlines(headlines)

        # 新闻数量也是信号: 更多新闻 = 更多关注 = 分数更可靠
        # 将 sentiment (-1 ~ +1) 转化为 0-10 分
        # -1 → 0, 0 → 5, +1 → 10
        news_score = 5.0 + sentiment * 5.0
        news_score = max(0.0, min(10.0, news_score))

        # 如果新闻太少 (<3)，拉向中性
        if len(headlines) < 3:
            news_score = 5.0 + (news_score - 5.0) * 0.5

        return {
            'news_sentiment': round(sentiment, 4),
            'news_count': len(headlines),
            'news_score': round(news_score, 2),
            'data_available': True,
        }

    def score_universe(self, tickers, target_date, lookback_days=30):
        """对一组 ticker 计算新闻情绪"""
        results = {}
        for ticker in tickers:
            results[ticker] = self.score_at_date(ticker, target_date, lookback_days)
        return results

    def get_coverage_stats(self, tickers=None):
        """获取数据覆盖统计"""
        stats = {}
        for ticker, df in self._data.items():
            if tickers and ticker not in [t.upper() for t in tickers]:
                continue
            if df.empty:
                continue
            stats[ticker] = {
                'count': len(df),
                'min_date': str(df['date'].min().date()),
                'max_date': str(df['date'].max().date()),
            }
        return stats
