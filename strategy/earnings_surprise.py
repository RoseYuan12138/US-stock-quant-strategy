"""
Earnings Surprise 因子（盈利惊喜）
财报超预期/低于预期是最强的短期 alpha 信号之一

学术依据：
- Post-Earnings Announcement Drift (PEAD) — Bernard & Thomas (1989)
- 财报超预期后，股价在 60-90 天内持续漂移（市场对盈利信息反应不足）
- 这是金融学中最持久的异象之一，发现 30+ 年仍然有效

数据源：yfinance Ticker.earnings_dates 或 quarterly_earnings
"""

import logging
import numpy as np
import pandas as pd
import yfinance as yf
from pathlib import Path
from datetime import datetime, timedelta
import json

logger = logging.getLogger(__name__)


class EarningsSurpriseScorer:
    """
    Earnings Surprise 评分器

    逻辑：
    - 获取最近几个季度的 EPS actual vs EPS estimate
    - 计算 surprise % = (actual - estimate) / |estimate|
    - 正 surprise → 加分，负 surprise → 减分
    - 连续 beat/miss 有额外权重（趋势性）
    """

    def __init__(self, cache_dir="./data/cache/earnings"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache = {}

    def get_earnings_data(self, ticker):
        """
        获取历史 earnings surprise 数据

        Returns:
            list of dict: [
                {'date': str, 'eps_actual': float, 'eps_estimate': float,
                 'surprise_pct': float, 'beat': bool},
                ...
            ]
            按日期降序（最新的在前）
        """
        ticker = ticker.upper()

        if ticker in self._cache:
            return self._cache[ticker]

        # 磁盘缓存
        cache_file = self.cache_dir / f"{ticker}.json"
        if cache_file.exists():
            try:
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                if data.get('fetch_date'):
                    fetch_dt = datetime.fromisoformat(data['fetch_date'])
                    if datetime.now() - fetch_dt < timedelta(days=7):
                        self._cache[ticker] = data.get('earnings', [])
                        return self._cache[ticker]
            except Exception:
                pass

        # 从 yfinance 获取
        earnings = self._fetch_earnings(ticker)
        self._cache[ticker] = earnings

        # 保存缓存
        try:
            with open(cache_file, 'w') as f:
                json.dump({
                    'ticker': ticker,
                    'fetch_date': datetime.now().isoformat(),
                    'earnings': earnings,
                }, f, indent=2, default=str)
        except Exception:
            pass

        return earnings

    def score_at_date(self, ticker, target_date):
        """
        计算截至 target_date 的 earnings surprise 评分

        考虑：
        - 最近一次 earnings surprise 的方向和幅度
        - 连续 beat/miss 的趋势
        - 时间衰减（越近的 earnings 影响越大）

        Returns:
            dict: {
                'earnings_score': float (0-100),
                'last_surprise_pct': float,
                'consecutive_beats': int,
                'consecutive_misses': int,
                'data_available': bool,
            }
        """
        earnings = self.get_earnings_data(ticker)
        if not earnings:
            return {'earnings_score': 50, 'data_available': False,
                    'last_surprise_pct': 0, 'consecutive_beats': 0,
                    'consecutive_misses': 0}

        if isinstance(target_date, str):
            target_date = pd.Timestamp(target_date)

        # 只用 target_date 之前已公布的 earnings
        # 财报通常在 earnings date 当天收盘后或次日盘前公布
        available = [e for e in earnings
                     if pd.Timestamp(e['date']) <= target_date + timedelta(days=1)]

        if not available:
            return {'earnings_score': 50, 'data_available': False,
                    'last_surprise_pct': 0, 'consecutive_beats': 0,
                    'consecutive_misses': 0}

        score = 50  # 基础分

        # 最近一次 surprise
        last = available[0]
        last_surprise = last.get('surprise_pct', 0)

        if last_surprise > 20:
            score += 20
        elif last_surprise > 10:
            score += 15
        elif last_surprise > 5:
            score += 10
        elif last_surprise > 0:
            score += 5
        elif last_surprise > -5:
            score -= 5
        elif last_surprise > -10:
            score -= 10
        elif last_surprise > -20:
            score -= 15
        else:
            score -= 20

        # 连续性（最多看最近4个季度）
        recent = available[:4]
        consecutive_beats = 0
        consecutive_misses = 0

        for e in recent:
            if e.get('beat', False):
                consecutive_beats += 1
            else:
                break

        for e in recent:
            if not e.get('beat', True):
                consecutive_misses += 1
            else:
                break

        # 连续 beat 加分
        if consecutive_beats >= 4:
            score += 10
        elif consecutive_beats >= 3:
            score += 6
        elif consecutive_beats >= 2:
            score += 3

        # 连续 miss 减分
        if consecutive_misses >= 4:
            score -= 10
        elif consecutive_misses >= 3:
            score -= 6
        elif consecutive_misses >= 2:
            score -= 3

        # 时间衰减：如果最近一次 earnings 是很久以前的，影响减弱
        days_since = (target_date - pd.Timestamp(last['date'])).days
        if days_since > 120:
            # 超过 4 个月没有新财报，分数衰减向 50
            decay = min(1.0, (days_since - 120) / 120)
            score = score * (1 - decay) + 50 * decay

        return {
            'earnings_score': round(max(0, min(100, score)), 1),
            'last_surprise_pct': round(last_surprise, 2),
            'consecutive_beats': consecutive_beats,
            'consecutive_misses': consecutive_misses,
            'data_available': True,
        }

    def score_universe(self, tickers, target_date):
        """
        对一组股票计算 earnings surprise 评分

        Returns:
            dict: {ticker: score_dict}
        """
        results = {}
        for ticker in tickers:
            results[ticker] = self.score_at_date(ticker, target_date)
        return results

    def _fetch_earnings(self, ticker):
        """从 yfinance 获取 earnings data"""
        try:
            stock = yf.Ticker(ticker)

            # 方法1：earnings_dates（较新版 yfinance）
            try:
                ed = stock.earnings_dates
                if ed is not None and not ed.empty:
                    return self._parse_earnings_dates(ed)
            except Exception:
                pass

            # 方法2：quarterly_earnings
            try:
                qe = stock.quarterly_earnings
                if qe is not None and not qe.empty:
                    return self._parse_quarterly_earnings(qe)
            except Exception:
                pass

            # 方法3：earnings_history（某些版本）
            try:
                eh = stock.earnings_history
                if eh is not None and not eh.empty:
                    return self._parse_earnings_history(eh)
            except Exception:
                pass

            logger.warning(f"{ticker}: 无法获取 earnings data")
            return []

        except Exception as e:
            logger.warning(f"{ticker}: earnings 获取失败 - {e}")
            return []

    def _parse_earnings_dates(self, df):
        """解析 earnings_dates 格式"""
        results = []
        for date, row in df.iterrows():
            actual = row.get('Reported EPS')
            estimate = row.get('EPS Estimate')

            if pd.notna(actual) and pd.notna(estimate) and estimate != 0:
                surprise_pct = (actual - estimate) / abs(estimate) * 100
                results.append({
                    'date': str(pd.Timestamp(date).date()),
                    'eps_actual': float(actual),
                    'eps_estimate': float(estimate),
                    'surprise_pct': round(float(surprise_pct), 2),
                    'beat': actual > estimate,
                })

        # 按日期降序
        results.sort(key=lambda x: x['date'], reverse=True)
        return results

    def _parse_quarterly_earnings(self, df):
        """解析 quarterly_earnings 格式"""
        results = []
        for date, row in df.iterrows():
            actual = row.get('Actual') or row.get('Revenue')
            estimate = row.get('Estimate')

            if pd.notna(actual) and pd.notna(estimate) and estimate != 0:
                surprise_pct = (actual - estimate) / abs(estimate) * 100
                results.append({
                    'date': str(pd.Timestamp(date).date()),
                    'eps_actual': float(actual),
                    'eps_estimate': float(estimate),
                    'surprise_pct': round(float(surprise_pct), 2),
                    'beat': actual > estimate,
                })

        results.sort(key=lambda x: x['date'], reverse=True)
        return results

    def _parse_earnings_history(self, df):
        """解析 earnings_history 格式（备用）"""
        results = []
        for _, row in df.iterrows():
            actual = row.get('epsActual')
            estimate = row.get('epsEstimate')
            date = row.get('quarter') or row.get('date')

            if pd.notna(actual) and pd.notna(estimate) and estimate != 0:
                surprise_pct = (actual - estimate) / abs(estimate) * 100
                results.append({
                    'date': str(pd.Timestamp(date).date()) if date else '',
                    'eps_actual': float(actual),
                    'eps_estimate': float(estimate),
                    'surprise_pct': round(float(surprise_pct), 2),
                    'beat': actual > estimate,
                })

        results.sort(key=lambda x: x['date'], reverse=True)
        return results
