"""
组合管理策略
将选股（基本面+动量）、市场环境、仓位管理整合为一个完整的组合策略

核心流程（每月执行）：
1. 基本面评分 → 过滤掉差公司
2. 动量评分 → 过滤掉下跌趋势的公司（避免价值陷阱）
3. 综合评分排名 → 选 Top N
4. 市场环境 → 决定总仓位水平
5. 等权重（或评分加权）建仓
6. Trailing stop 保护个股下行
"""

import numpy as np
import pandas as pd
import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PortfolioConfig:
    """组合策略配置"""
    # 选股
    top_n: int = 8                       # 最多持有几只
    min_combined_score: float = 55       # 综合评分最低门槛
    min_momentum_score: float = 40       # 动量评分最低（过滤下跌趋势）

    # 权重
    weight_fundamental: float = 0.5      # 基本面权重
    weight_momentum: float = 0.3         # 动量权重
    weight_analyst: float = 0.2          # 分析师权重

    # 仓位
    max_single_weight: float = 0.15      # 单只股票最大仓位
    spy_base_weight: float = 0.20        # SPY 底仓比例
    use_regime_filter: bool = True       # 是否使用市场环境过滤

    # 风控
    trailing_stop_pct: float = 0.25      # 个股 trailing stop（从最高点回撤25%卖出）
    rebalance_freq: str = 'monthly'      # 再平衡频率：monthly / quarterly

    # 回测
    initial_cash: float = 100000         # 初始资金（组合回测用更大的金额）
    commission: float = 10               # 每笔佣金


@dataclass
class Position:
    """持仓记录"""
    ticker: str
    shares: float
    entry_price: float
    entry_date: pd.Timestamp
    highest_price: float  # 持仓期间最高价（用于 trailing stop）
    combined_score: float = 0
    cost_basis: float = 0  # 含佣金的总成本


class PortfolioStrategy:
    """
    组合管理策略

    不做日内择时，只在每月初做一次选股和再平衡。
    持仓期间只看 trailing stop。
    """

    def __init__(self, config: PortfolioConfig = None):
        self.config = config or PortfolioConfig()

    def select_stocks(self, fundamental_scores, momentum_scores,
                      short_interest=None, insider_scores=None,
                      news_scores=None):
        """
        月度选股：融合基本面 + 动量 + insider 信号，过滤高空头比例

        Args:
            fundamental_scores: dict {ticker: {'total_score': float, 'analyst_score': float, ...}}
            momentum_scores: dict {ticker: {'composite_score': float, 'above_200sma': bool, ...}}
            short_interest: dict {ticker: float} (short_percent_of_float, 可选)
            insider_scores: dict {ticker: {'insider_score': float, ...}} (可选)
            news_scores: dict {ticker: {'news_score': float, ...}} (可选)

        Returns:
            list of dict: 选中的股票列表，按综合评分降序
                [{'ticker': str, 'combined_score': float, 'fundamental_score': float,
                  'momentum_score': float, 'weight': float}, ...]
        """
        candidates = []

        for ticker, fund in fundamental_scores.items():
            fund_score = fund.get('total_score', 0)
            mom = momentum_scores.get(ticker)

            if mom is None:
                continue

            mom_score = mom.get('composite_score', 0)

            # 过滤：Short Interest > 15% 排除（高空头比例 = 高风险）
            if short_interest and ticker in short_interest:
                si = short_interest[ticker]
                if si is not None and si > 0.15:
                    logger.info(f"{ticker}: Short Interest {si:.1%} > 15%，排除")
                    continue

            # 过滤：动量太差的不要（避免价值陷阱）
            if mom_score < self.config.min_momentum_score:
                logger.info(f"{ticker}: 动量评分 {mom_score:.0f} 低于门槛 {self.config.min_momentum_score}，跳过")
                continue

            # 综合评分
            analyst_score = fund.get('analyst_score', fund_score)
            combined = (
                fund_score * self.config.weight_fundamental +
                mom_score * self.config.weight_momentum +
                analyst_score * self.config.weight_analyst
            )

            # Insider Trading 加分（集群买入 → +3~8分）
            insider_bonus = 0
            if insider_scores and ticker in insider_scores:
                ins = insider_scores[ticker]
                insider_bonus = ins.get('insider_bonus', 0)
                combined += insider_bonus

            # 新闻情绪调整（news_score 0-10, 中性=5）
            news_bonus = 0
            if news_scores and ticker in news_scores:
                ns = news_scores[ticker]
                if ns.get('data_available') and ns.get('news_count', 0) >= 3:
                    # news_score 5=中性, >5=正面, <5=负面
                    # 转化为 -3 ~ +3 的加分
                    news_bonus = (ns['news_score'] - 5.0) * 0.6
                    combined += news_bonus

            if combined < self.config.min_combined_score:
                continue

            candidates.append({
                'ticker': ticker,
                'combined_score': round(combined, 1),
                'fundamental_score': fund_score,
                'momentum_score': mom_score,
                'analyst_score': analyst_score,
                'above_200sma': mom.get('above_200sma', False),
                'insider_bonus': insider_bonus,
                'news_bonus': round(news_bonus, 1),
            })

        # 按综合评分排名，选 Top N
        candidates.sort(key=lambda x: x['combined_score'], reverse=True)
        selected = candidates[:self.config.top_n]

        # 分配权重（等权重，受 max_single_weight 限制）
        if selected:
            stock_pool_weight = 1.0 - self.config.spy_base_weight
            raw_weight = stock_pool_weight / len(selected)
            capped_weight = min(raw_weight, self.config.max_single_weight)

            for s in selected:
                s['weight'] = round(capped_weight, 4)

        return selected

    def check_trailing_stop(self, position, current_price):
        """
        检查个股是否触发 trailing stop

        Args:
            position: Position object
            current_price: 当前价格

        Returns:
            bool: True = 需要卖出
        """
        if current_price > position.highest_price:
            position.highest_price = current_price

        drawdown = (current_price - position.highest_price) / position.highest_price

        if drawdown <= -self.config.trailing_stop_pct:
            return True

        return False

    def should_rebalance(self, current_date, last_rebalance_date):
        """
        判断是否需要再平衡

        Args:
            current_date: 当前日期
            last_rebalance_date: 上次再平衡日期

        Returns:
            bool
        """
        if last_rebalance_date is None:
            return True

        if self.config.rebalance_freq == 'monthly':
            return current_date.month != last_rebalance_date.month or \
                   current_date.year != last_rebalance_date.year
        elif self.config.rebalance_freq == 'quarterly':
            current_q = (current_date.month - 1) // 3
            last_q = (last_rebalance_date.month - 1) // 3
            return current_q != last_q or current_date.year != last_rebalance_date.year
        else:
            return False
