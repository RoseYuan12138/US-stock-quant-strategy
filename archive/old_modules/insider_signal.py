"""
Insider Trading 信号模块
SEC Form 4 高管买卖交易作为选股加分信号

学术依据：
- Lakonishok & Lee (2001): insider buy portfolios 年化超额 7-10%
- Jeng, Metrick & Zeckhauser (2003): insider purchases are informative
- 关键信号：多个 insider 在短时间内同时买入（cluster buy）比单人买入信号更强

数据源：yfinance insider_transactions（来自 SEC EDGAR Form 4）
"""

import logging
import json
import numpy as np
import pandas as pd
import yfinance as yf
from pathlib import Path
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class InsiderSignalScorer:
    """
    Insider Trading 评分器

    逻辑：
    - 获取近 12 个月的 insider 交易记录
    - 统计买入/卖出的人数和金额
    - 集群买入（3个月内 ≥3 个不同 insider 买入）→ 强信号加分
    - 大额 insider 卖出 → 轻微减分（注意：卖出原因很多，信号弱于买入）
    - 输出 insider_bonus (0-8 分) 加到综合评分上
    """

    def __init__(self, cache_dir="./data/cache/insider"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache = {}

    def get_insider_data(self, ticker):
        """
        获取 insider 交易数据

        Returns:
            pd.DataFrame or None
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
                        records = data.get('transactions', [])
                        if records:
                            df = pd.DataFrame(records)
                            df['date'] = pd.to_datetime(df['date'])
                            self._cache[ticker] = df
                            return df
                        self._cache[ticker] = None
                        return None
            except Exception:
                pass

        # 从 yfinance 获取
        df = self._fetch_insider(ticker)
        self._cache[ticker] = df

        # 保存缓存
        try:
            records = []
            if df is not None and not df.empty:
                records = df.to_dict('records')
                for r in records:
                    if isinstance(r.get('date'), pd.Timestamp):
                        r['date'] = str(r['date'].date())
            with open(cache_file, 'w') as f:
                json.dump({
                    'ticker': ticker,
                    'fetch_date': datetime.now().isoformat(),
                    'transactions': records,
                }, f, indent=2, default=str)
        except Exception:
            pass

        return df

    def score_at_date(self, ticker, target_date):
        """
        计算截至 target_date 的 insider trading 评分

        Returns:
            dict: {
                'insider_bonus': float (0-8),
                'cluster_buy': bool,
                'net_buy_count_90d': int,
                'net_buy_count_180d': int,
                'data_available': bool,
            }
        """
        df = self.get_insider_data(ticker)

        if df is None or df.empty:
            return {
                'insider_bonus': 0, 'cluster_buy': False,
                'net_buy_count_90d': 0, 'net_buy_count_180d': 0,
                'data_available': False,
            }

        if isinstance(target_date, str):
            target_date = pd.Timestamp(target_date)

        # 只看 target_date 之前的交易
        available = df[df['date'] <= target_date].copy()
        if available.empty:
            return {
                'insider_bonus': 0, 'cluster_buy': False,
                'net_buy_count_90d': 0, 'net_buy_count_180d': 0,
                'data_available': True,
            }

        # 最近 90 天
        d90 = available[available['date'] >= target_date - timedelta(days=90)]
        # 最近 180 天
        d180 = available[available['date'] >= target_date - timedelta(days=180)]

        # 统计买入/卖出的不同 insider 人数
        buys_90d = d90[d90['is_buy'] == True]
        sells_90d = d90[d90['is_buy'] == False]
        buys_180d = d180[d180['is_buy'] == True]
        sells_180d = d180[d180['is_buy'] == False]

        unique_buyers_90d = buys_90d['insider'].nunique() if not buys_90d.empty else 0
        unique_sellers_90d = sells_90d['insider'].nunique() if not sells_90d.empty else 0
        unique_buyers_180d = buys_180d['insider'].nunique() if not buys_180d.empty else 0
        unique_sellers_180d = sells_180d['insider'].nunique() if not sells_180d.empty else 0

        net_buy_90d = unique_buyers_90d - unique_sellers_90d
        net_buy_180d = unique_buyers_180d - unique_sellers_180d

        # 集群买入判定：90天内 ≥3 个不同 insider 买入
        cluster_buy = unique_buyers_90d >= 3

        # 评分
        bonus = 0

        # 集群买入：最强信号
        if cluster_buy:
            bonus += 5
            if unique_buyers_90d >= 5:
                bonus += 3  # 超大集群

        # 单人/双人买入
        elif unique_buyers_90d >= 2:
            bonus += 3
        elif unique_buyers_90d >= 1:
            bonus += 1

        # 180天净买入趋势
        if net_buy_180d >= 3:
            bonus += 2
        elif net_buy_180d >= 1:
            bonus += 1

        # 大量卖出轻微减分（但不扣太多，卖出原因复杂）
        if unique_sellers_90d >= 5 and unique_buyers_90d == 0:
            bonus -= 2

        bonus = max(0, min(8, bonus))

        return {
            'insider_bonus': bonus,
            'cluster_buy': cluster_buy,
            'net_buy_count_90d': net_buy_90d,
            'net_buy_count_180d': net_buy_180d,
            'unique_buyers_90d': unique_buyers_90d,
            'unique_sellers_90d': unique_sellers_90d,
            'data_available': True,
        }

    def score_universe(self, tickers, target_date):
        """对一组股票计算 insider 评分"""
        results = {}
        for ticker in tickers:
            results[ticker] = self.score_at_date(ticker, target_date)
        return results

    def _fetch_insider(self, ticker):
        """从 yfinance 获取 insider 交易记录"""
        try:
            stock = yf.Ticker(ticker)

            # 方法1: insider_transactions
            try:
                txns = stock.insider_transactions
                if txns is not None and not txns.empty:
                    return self._parse_transactions(txns)
            except Exception:
                pass

            # 方法2: get_insider_transactions()
            try:
                txns = stock.get_insider_transactions()
                if txns is not None and not txns.empty:
                    return self._parse_transactions(txns)
            except Exception:
                pass

            logger.debug(f"{ticker}: 无 insider 交易数据")
            return None

        except Exception as e:
            logger.debug(f"{ticker}: insider 数据获取失败 - {e}")
            return None

    def _parse_transactions(self, df):
        """
        解析 yfinance insider_transactions 为标准格式

        yfinance 返回的列名可能包括:
        - Shares, Value, URL, Text, Insider, Position, Transaction, Start Date, Ownership
        """
        records = []

        for idx, row in df.iterrows():
            try:
                # 日期
                date = None
                if 'Start Date' in df.columns:
                    date = pd.Timestamp(row['Start Date'])
                elif isinstance(idx, (pd.Timestamp, datetime)):
                    date = pd.Timestamp(idx)

                if date is None or pd.isna(date):
                    continue

                # Insider 名字
                insider = row.get('Insider', '')
                if not insider or pd.isna(insider):
                    insider = 'Unknown'

                # 买入还是卖出？从 Text 或 Shares 判断
                text = str(row.get('Text', '')).lower()
                shares = row.get('Shares', 0)
                if pd.isna(shares):
                    shares = 0

                # 判断买卖方向
                is_buy = None
                if 'purchase' in text or 'buy' in text or 'acquisition' in text:
                    is_buy = True
                elif 'sale' in text or 'sell' in text or 'disposition' in text:
                    is_buy = False
                elif shares > 0:
                    # 正数股份且没有明确文本 → 可能是买入
                    # 但很多 sale 也显示正数，所以这个不太可靠
                    # 保守处理：跳过无法判断的
                    continue
                else:
                    continue

                if is_buy is None:
                    continue

                value = row.get('Value', 0)
                if pd.isna(value):
                    value = 0

                position = row.get('Position', '')
                if pd.isna(position):
                    position = ''

                records.append({
                    'date': date,
                    'insider': str(insider).strip(),
                    'position': str(position).strip(),
                    'is_buy': is_buy,
                    'shares': abs(int(shares)),
                    'value': abs(float(value)),
                })

            except Exception:
                continue

        if not records:
            return None

        result = pd.DataFrame(records)
        result = result.sort_values('date', ascending=False).reset_index(drop=True)
        return result
