"""
动量因子模块
计算价格动量评分，用于与基本面评分融合选股

核心逻辑：
- 6个月价格动量（剔除最近1个月，避免短期反转噪音）
- 相对强度评分 0-100
- 趋势确认：价格在200日均线之上加分
"""

import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class MomentumScorer:
    """
    动量评分器

    学术依据：Jegadeesh & Titman (1993) 动量效应
    - 过去6个月涨幅靠前的股票，未来3-12个月倾向继续跑赢
    - 剔除最近1个月（短期反转效应）
    - 结合趋势确认（200日均线）避免在下跌趋势中抄底
    """

    def __init__(self, lookback_months=6, skip_recent_months=1):
        """
        Args:
            lookback_months: 动量回看期（月），默认6个月
            skip_recent_months: 跳过最近N个月（避免短期反转），默认1个月
        """
        self.lookback_days = lookback_months * 21  # 约每月21个交易日
        self.skip_days = skip_recent_months * 21

    def calculate_momentum(self, price_data):
        """
        计算单只股票的动量指标

        Args:
            price_data: DataFrame with 'Close' column and DatetimeIndex

        Returns:
            dict: {
                'momentum_return': float,  # 动量期收益率
                'momentum_score': float,   # 0-100 评分
                'above_200sma': bool,      # 是否在200日均线之上
                'trend_score': float,      # 趋势分 0-100
                'composite_score': float,  # 综合动量分（动量70% + 趋势30%）
            }
        """
        if price_data is None or len(price_data) < self.lookback_days + self.skip_days:
            return None

        close = price_data['Close']

        # 动量收益：过去6个月到1个月前的涨幅
        end_idx = len(close) - self.skip_days
        start_idx = end_idx - self.lookback_days

        if start_idx < 0 or end_idx <= start_idx:
            return None

        price_start = close.iloc[start_idx]
        price_end = close.iloc[end_idx]
        momentum_return = (price_end - price_start) / price_start

        # 动量评分：将收益率映射到 0-100
        # 经验参考：6个月涨幅 -30%~+60% 映射到 0~100
        momentum_score = self._return_to_score(momentum_return)

        # 200日均线趋势确认
        sma200 = close.rolling(window=200).mean()
        current_price = close.iloc[-1]
        current_sma200 = sma200.iloc[-1]

        above_200sma = False
        trend_score = 50  # 默认中性

        if not np.isnan(current_sma200):
            above_200sma = current_price > current_sma200
            # 价格相对200日均线的位置
            pct_above = (current_price - current_sma200) / current_sma200
            # 映射到 0-100：-20% → 0, 0% → 50, +20% → 100
            trend_score = max(0, min(100, 50 + pct_above * 250))

        # 综合动量分 = 动量 70% + 趋势 30%
        composite_score = momentum_score * 0.7 + trend_score * 0.3

        return {
            'momentum_return': momentum_return,
            'momentum_score': round(momentum_score, 1),
            'above_200sma': above_200sma,
            'trend_score': round(trend_score, 1),
            'composite_score': round(composite_score, 1),
        }

    def score_universe(self, price_data_dict):
        """
        对一组股票计算动量评分

        Args:
            price_data_dict: {ticker: DataFrame}

        Returns:
            dict: {ticker: momentum_dict}
        """
        results = {}
        for ticker, data in price_data_dict.items():
            score = self.calculate_momentum(data)
            if score is not None:
                score['ticker'] = ticker
                results[ticker] = score

        return results

    def rank_by_momentum(self, price_data_dict):
        """
        按动量排名，返回排序后的 DataFrame

        Args:
            price_data_dict: {ticker: DataFrame}

        Returns:
            pd.DataFrame: 按 composite_score 降序排列
        """
        scores = self.score_universe(price_data_dict)
        if not scores:
            return pd.DataFrame()

        df = pd.DataFrame(scores.values())
        df = df.sort_values('composite_score', ascending=False)
        df['rank'] = range(1, len(df) + 1)
        return df

    def _return_to_score(self, ret):
        """
        将收益率映射到 0-100 评分

        映射逻辑：
        -30% 以下 → 0
        0% → 50
        +60% 以上 → 100
        线性插值
        """
        if ret <= -0.30:
            return 0
        elif ret >= 0.60:
            return 100
        elif ret < 0:
            # -30% → 0, 0% → 50，线性
            return (ret + 0.30) / 0.30 * 50
        else:
            # 0% → 50, 60% → 100，线性
            return 50 + ret / 0.60 * 50


def combine_scores(fundamental_score, momentum_score,
                   weight_fundamental=0.5, weight_momentum=0.3, weight_analyst=0.2,
                   analyst_score=None):
    """
    融合基本面 + 动量 + 分析师评分

    Args:
        fundamental_score: 基本面评分 0-100
        momentum_score: 动量综合评分 0-100
        weight_fundamental: 基本面权重 (default 0.5)
        weight_momentum: 动量权重 (default 0.3)
        weight_analyst: 分析师权重 (default 0.2)
        analyst_score: 分析师评分 0-100 (None 则用基本面中的分析师分)

    Returns:
        float: 综合评分 0-100
    """
    if analyst_score is None:
        # 没有单独的分析师分，权重归入基本面
        combined = fundamental_score * (weight_fundamental + weight_analyst) + \
                   momentum_score * weight_momentum
    else:
        combined = fundamental_score * weight_fundamental + \
                   momentum_score * weight_momentum + \
                   analyst_score * weight_analyst

    return round(max(0, min(100, combined)), 1)
