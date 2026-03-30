"""
市场环境（Regime）过滤器 V2
跨资产信号升级：收益率曲线 + VIX + 信用利差 + SPY 均线

核心逻辑（加权投票）：
1. SPY 均线信号（原有）：价格 vs 200日/10月均线
2. 收益率曲线信号（新增）：10Y-3M 利差，倒挂预警衰退
3. VIX 信号（新增）：恐慌水平 + 趋势
4. 信用利差信号（新增）：HYG vs LQD 价差变化，信用紧缩预警

学术依据：
- Faber (2007) "A Quantitative Approach to Tactical Asset Allocation"
- Harvey (1988) 收益率曲线预测衰退，准确率 7/7
- VIX 期限结构 contango/backwardation 是经典风险开关
- 信用利差扩大是衰退和市场下跌的领先指标 (Gilchrist & Zakrajsek 2012)

数据源：全部通过 yfinance 获取，无需额外 API key
- ^TNX: 10年期国债收益率
- ^IRX: 13周国库券收益率
- ^VIX: VIX 恐慌指数
- HYG: 高收益债 ETF
- LQD: 投资级债 ETF
"""

import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class RegimeFilter:
    """
    市场环境过滤器 V2

    使用 SPY + 跨资产宏观信号判断市场环境。
    4 个子信号加权投票，比单一均线更早发出预警。
    """

    # 市场状态
    BULL = 'BULL'           # 牛市：正常仓位
    CAUTION = 'CAUTION'     # 谨慎：减半仓位
    BEAR = 'BEAR'           # 熊市：最小仓位
    RECOVERY = 'RECOVERY'   # 恢复期：从 BEAR 退出后阶梯式恢复仓位

    # 子信号权重（总和 = 1.0）
    # SMA 主导，跨资产信号作为辅助减分/加分
    WEIGHT_SMA = 0.55       # SPY 均线（主导信号）
    WEIGHT_YIELD = 0.15     # 收益率曲线（辅助）
    WEIGHT_VIX = 0.15       # VIX（辅助）
    WEIGHT_CREDIT = 0.15    # 信用利差（辅助）

    def __init__(self, sma_period=200, monthly_sma=10,
                 yield_curve_window=20, vix_threshold=25,
                 credit_spread_window=60):
        """
        Args:
            sma_period: 日线均线周期（默认200日）
            monthly_sma: 月线均线周期（默认10个月）
            yield_curve_window: 收益率曲线平滑窗口（天）
            vix_threshold: VIX 恐慌阈值
            credit_spread_window: 信用利差变化计算窗口（天）
        """
        self.sma_period = sma_period
        self.monthly_sma_days = monthly_sma * 21
        self.yield_curve_window = yield_curve_window
        self.vix_threshold = vix_threshold
        self.credit_spread_window = credit_spread_window

    def get_regime(self, benchmark_data, macro_data=None,
                   previous_regime=None, days_since_bear_exit=None):
        """
        判断当前市场状态

        Args:
            benchmark_data: SPY 的 DataFrame (OHLCV, DatetimeIndex)
            macro_data: dict of DataFrames，可选跨资产数据
                {'tnx': df, 'irx': df, 'vix': df, 'hyg': df, 'lqd': df}
            previous_regime: 上一期的 regime 状态（用于不对称转换判断），
                如果为 None 则退化为无状态行为（向后兼容）
            days_since_bear_exit: 退出 BEAR 后经过的交易日数，
                仅当 previous_regime 为 RECOVERY 时有效

        Returns:
            dict: {
                'regime': 'BULL' / 'CAUTION' / 'BEAR' / 'RECOVERY',
                'position_multiplier': float (0.0 ~ 1.0),
                'composite_score': float (0-100),
                'signals': dict (各子信号详情),
            }
        """
        if benchmark_data is None or len(benchmark_data) < self.sma_period:
            logger.warning("基准数据不足，默认返回 BULL")
            return self._default_regime()

        close = benchmark_data['Close']
        current_price = close.iloc[-1]

        # 子信号1: SPY 均线
        sma_score = self._sma_signal(close)

        # 子信号2-4: 跨资产信号
        yield_score = self._yield_curve_signal(macro_data) if macro_data else 50
        vix_score = self._vix_signal(macro_data) if macro_data else 50
        credit_score = self._credit_spread_signal(macro_data) if macro_data else 50

        # 加权合成
        composite = (
            sma_score * self.WEIGHT_SMA +
            yield_score * self.WEIGHT_YIELD +
            vix_score * self.WEIGHT_VIX +
            credit_score * self.WEIGHT_CREDIT
        )

        signals = {
            'sma_score': round(sma_score, 1),
            'yield_curve_score': round(yield_score, 1),
            'vix_score': round(vix_score, 1),
            'credit_spread_score': round(credit_score, 1),
        }

        # 无状态模式（向后兼容）：previous_regime 为 None 时走原逻辑
        if previous_regime is None:
            regime, multiplier = self._score_to_regime(composite)
        else:
            # 有状态不对称转换逻辑
            suggested_regime, suggested_mult = self._score_to_regime(composite)

            if previous_regime == self.BEAR:
                # 从 BEAR 退出：宽松条件
                if self.should_exit_bear(close):
                    regime = self.RECOVERY
                    multiplier = 0.5  # RECOVERY 起始仓位
                    logger.info(
                        f"Regime 转换: BEAR -> RECOVERY (价格收复50日均线且不创新低, "
                        f"composite={composite:.1f})"
                    )
                else:
                    regime = self.BEAR
                    multiplier = 0.25
            elif previous_regime == self.RECOVERY:
                if self.should_enter_bear(signals):
                    regime = self.BEAR
                    multiplier = 0.25
                    logger.info(
                        f"Regime 转换: RECOVERY -> BEAR (严格条件再次满足, "
                        f"composite={composite:.1f})"
                    )
                else:
                    days = days_since_bear_exit if days_since_bear_exit is not None else 0
                    multiplier = self._recovery_multiplier(days, close)
                    if multiplier >= 1.0:
                        regime = suggested_regime
                        multiplier = suggested_mult
                        logger.info(
                            f"Regime 转换: RECOVERY -> {regime} (收复200DMA, "
                            f"composite={composite:.1f})"
                        )
                    else:
                        regime = self.RECOVERY
            else:
                # 从非 BEAR 进入 BEAR：严格条件
                if suggested_regime == self.BEAR and self.should_enter_bear(signals):
                    regime = self.BEAR
                    multiplier = 0.25
                    logger.info(
                        f"Regime 转换: {previous_regime} -> BEAR (严格条件满足, "
                        f"composite={composite:.1f})"
                    )
                elif suggested_regime == self.BEAR:
                    # composite 建议 BEAR 但严格条件不满足，降级为 CAUTION
                    regime = self.CAUTION
                    multiplier = 0.5
                    logger.info(
                        f"Regime 保持 CAUTION (composite={composite:.1f} 建议 BEAR, "
                        f"但严格条件不满足)"
                    )
                else:
                    regime = suggested_regime
                    multiplier = suggested_mult

        return {
            'regime': regime,
            'position_multiplier': multiplier,
            'composite_score': round(composite, 1),
            'signals': signals,
            'current_price': current_price,
        }

    def get_regime_series(self, benchmark_data, macro_data=None,
                          asymmetric=True):
        """
        为回测生成每日的市场状态序列

        Args:
            benchmark_data: SPY DataFrame
            macro_data: dict of DataFrames (可选)
            asymmetric: 是否启用不对称转换逻辑（默认 True）。
                设为 False 时退化为无状态行为（向后兼容）。

        Returns:
            pd.DataFrame: columns=['regime', 'position_multiplier', 'composite_score']
        """
        if benchmark_data is None or len(benchmark_data) < self.sma_period:
            return None

        close = benchmark_data['Close']
        sma200 = close.rolling(window=self.sma_period).mean()
        monthly_sma = close.rolling(window=self.monthly_sma_days).mean()

        # 预计算跨资产信号序列
        yield_series = self._yield_curve_series(macro_data) if macro_data else None
        vix_series = self._vix_series(macro_data) if macro_data else None
        credit_series = self._credit_spread_series(macro_data) if macro_data else None

        regimes = []
        multipliers = []
        scores = []

        # 有状态变量
        current_regime = self.BULL
        days_since_bear_exit = 0

        for i in range(len(close)):
            date = close.index[i]
            price = close.iloc[i]
            s200 = sma200.iloc[i]
            ms = monthly_sma.iloc[i]

            # 子信号1: SMA
            if np.isnan(s200) or np.isnan(ms):
                sma_score = 75  # 数据不足，偏乐观
            elif price > s200 and price > ms:
                sma_score = 100
            elif price > s200 or price > ms:
                sma_score = 50
            else:
                sma_score = 0

            # 子信号2-4: 跨资产（从预计算序列取值）
            yield_score = self._get_series_value(yield_series, date, 50)
            vix_score = self._get_series_value(vix_series, date, 50)
            credit_score = self._get_series_value(credit_series, date, 50)

            # 加权合成
            composite = (
                sma_score * self.WEIGHT_SMA +
                yield_score * self.WEIGHT_YIELD +
                vix_score * self.WEIGHT_VIX +
                credit_score * self.WEIGHT_CREDIT
            )

            if not asymmetric:
                # 无状态模式（向后兼容）
                regime, multiplier = self._score_to_regime(composite)
            else:
                # 有状态不对称转换逻辑
                suggested_regime, suggested_mult = self._score_to_regime(composite)

                signals = {
                    'sma_score': sma_score,
                    'vix_score': vix_score,
                    'credit_spread_score': credit_score,
                    'yield_curve_score': yield_score,
                }

                if current_regime == self.BEAR:
                    # 从 BEAR 退出：宽松条件
                    close_up_to_now = close.iloc[:i + 1]
                    if self._should_exit_bear_at(close_up_to_now):
                        current_regime = self.RECOVERY
                        days_since_bear_exit = 0
                        logger.info(
                            f"[{date.strftime('%Y-%m-%d')}] Regime: BEAR -> RECOVERY "
                            f"(composite={composite:.1f})"
                        )
                    regime = current_regime
                    multiplier = 0.25 if current_regime == self.BEAR else 0.5

                elif current_regime == self.RECOVERY:
                    days_since_bear_exit += 1
                    close_up_to_now = close.iloc[:i + 1]

                    if self.should_enter_bear(signals):
                        # RECOVERY 期间再次触发严格 BEAR 条件
                        current_regime = self.BEAR
                        days_since_bear_exit = 0
                        regime = self.BEAR
                        multiplier = 0.25
                        logger.info(
                            f"[{date.strftime('%Y-%m-%d')}] Regime: RECOVERY -> BEAR "
                            f"(严格条件再次满足, composite={composite:.1f})"
                        )
                    else:
                        # 价格驱动恢复
                        multiplier = self._recovery_multiplier(
                            days_since_bear_exit, close_up_to_now
                        )

                        if multiplier >= 1.0:
                            # 收复 200DMA → RECOVERY 结束，回归正常
                            current_regime = suggested_regime
                            regime = suggested_regime
                            multiplier = suggested_mult
                            logger.info(
                                f"[{date.strftime('%Y-%m-%d')}] Regime: RECOVERY -> {regime} "
                                f"(收复200DMA, composite={composite:.1f})"
                            )
                        else:
                            regime = self.RECOVERY

                else:
                    # 从非 BEAR（BULL / CAUTION）进入 BEAR：严格条件
                    if suggested_regime == self.BEAR and self.should_enter_bear(signals):
                        prev = current_regime
                        current_regime = self.BEAR
                        regime = self.BEAR
                        multiplier = 0.25
                        logger.info(
                            f"[{date.strftime('%Y-%m-%d')}] Regime: {prev} -> BEAR "
                            f"(严格条件满足, composite={composite:.1f})"
                        )
                    elif suggested_regime == self.BEAR:
                        # composite 建议 BEAR 但严格条件不满足 -> CAUTION
                        current_regime = self.CAUTION
                        regime = self.CAUTION
                        multiplier = 0.5
                    else:
                        current_regime = suggested_regime
                        regime = suggested_regime
                        multiplier = suggested_mult

            regimes.append(regime)
            multipliers.append(multiplier)
            scores.append(round(composite, 1))

        return pd.DataFrame({
            'regime': regimes,
            'position_multiplier': multipliers,
            'composite_score': scores,
        }, index=benchmark_data.index)

    # ========== 不对称 Regime 转换 ==========

    def should_enter_bear(self, signals):
        """严格条件：至少 3/4 个宏观指标同时看空才进入 BEAR"""
        bearish_count = 0
        if signals['sma_score'] < 30:           bearish_count += 1
        if signals['vix_score'] < 30:           bearish_count += 1
        if signals['credit_spread_score'] < 30: bearish_count += 1
        if signals['yield_curve_score'] < 30:   bearish_count += 1
        return bearish_count >= 3

    def should_exit_bear(self, close):
        """宽松条件：价格收复 50 日均线 + 近 10 天不创新低"""
        if len(close) < 50:
            return False
        sma50 = close.rolling(50).mean().iloc[-1]
        price = close.iloc[-1]
        price_recovered = price > sma50
        recent_low = close.iloc[-10:].min()
        prior_low = close.iloc[-30:-10].min() if len(close) >= 30 else close.iloc[0]
        no_new_low = recent_low > prior_low
        return price_recovered and no_new_low

    def _should_exit_bear_at(self, close):
        """should_exit_bear 的内部版本，直接接受 close Series 切片"""
        if len(close) < 50:
            return False
        sma50 = close.rolling(50).mean().iloc[-1]
        price = close.iloc[-1]
        price_recovered = price > sma50
        recent_low = close.iloc[-10:].min()
        prior_low = close.iloc[-30:-10].min() if len(close) >= 30 else close.iloc[0]
        no_new_low = recent_low > prior_low
        return price_recovered and no_new_low

    def _recovery_multiplier(self, days_since_exit, close):
        """RECOVERY 期间的价格驱动仓位恢复

        不用固定天数，看价格收复了哪条均线：
        - 收复 20DMA → 0.5（已在 RECOVERY 入口保证）
        - 收复 50DMA → 0.75
        - 收复 200DMA → 1.0（RECOVERY 结束）

        Args:
            days_since_exit: 退出 BEAR 后经过的交易日数（仅做安全上限）
            close: 价格序列

        Returns:
            float: position_multiplier
        """
        price = close.iloc[-1]

        # 收复 200DMA → 满仓
        if len(close) >= 200:
            sma200 = close.rolling(200).mean().iloc[-1]
            if not np.isnan(sma200) and price > sma200:
                return 1.0

        # 收复 50DMA → 0.75
        if len(close) >= 50:
            sma50 = close.rolling(50).mean().iloc[-1]
            if not np.isnan(sma50) and price > sma50:
                return 0.75

        # 只收复 20DMA（进入 RECOVERY 的条件）→ 0.5
        return 0.5

    # ========== 子信号实现 ==========

    def _sma_signal(self, close):
        """SPY 均线信号 → 0-100 分"""
        sma200 = close.rolling(window=self.sma_period).mean().iloc[-1]
        monthly_sma = close.rolling(window=self.monthly_sma_days).mean().iloc[-1]
        price = close.iloc[-1]

        if np.isnan(sma200) or np.isnan(monthly_sma):
            return 75

        if price > sma200 and price > monthly_sma:
            return 100
        elif price > sma200 or price > monthly_sma:
            return 50
        else:
            return 0

    def _yield_curve_signal(self, macro_data):
        """
        收益率曲线信号 → 0-100 分

        10Y - 3M 利差：
        - 正常（>100bp）→ 高分（牛市）
        - 平坦化（0-100bp）→ 中性
        - 倒挂（<0）→ 低分（衰退预警）
        """
        tnx = macro_data.get('tnx')  # 10Y yield
        irx = macro_data.get('irx')  # 13W yield (3M proxy)

        if tnx is None or irx is None:
            return 50

        try:
            tnx_close = tnx['Close']
            irx_close = irx['Close']

            # 对齐日期
            aligned = pd.DataFrame({'tnx': tnx_close, 'irx': irx_close}).dropna()
            if len(aligned) < self.yield_curve_window:
                return 50

            # 利差（百分点）
            spread = aligned['tnx'] - aligned['irx']
            # 平滑
            spread_smooth = spread.rolling(window=self.yield_curve_window, min_periods=5).mean()
            current_spread = spread_smooth.iloc[-1]

            if np.isnan(current_spread):
                return 50

            # 利差趋势（近60天变化）
            if len(spread_smooth) > 60:
                spread_change = current_spread - spread_smooth.iloc[-60]
            else:
                spread_change = 0

            # 评分
            score = 50
            # 利差水平
            if current_spread > 1.5:
                score += 30  # 健康利差
            elif current_spread > 0.5:
                score += 15
            elif current_spread > 0:
                score += 0   # 平坦
            elif current_spread > -0.5:
                score -= 20  # 轻度倒挂
            else:
                score -= 40  # 深度倒挂

            # 趋势加减分
            if spread_change < -0.5:
                score -= 10  # 快速平坦化/倒挂加深
            elif spread_change > 0.3:
                score += 10  # 利差恢复

            return max(0, min(100, score))

        except Exception as e:
            logger.debug(f"收益率曲线信号计算失败: {e}")
            return 50

    def _vix_signal(self, macro_data):
        """
        VIX 信号 → 0-100 分

        VIX 水平 + 趋势：
        - VIX < 15 → 市场平静，高分
        - VIX 15-25 → 正常
        - VIX 25-35 → 恐慌升温
        - VIX > 35 → 极度恐慌
        - VIX 快速上升 → 额外减分
        """
        vix = macro_data.get('vix')
        if vix is None:
            return 50

        try:
            vix_close = vix['Close'].dropna()
            if len(vix_close) < 20:
                return 50

            current_vix = vix_close.iloc[-1]
            vix_sma20 = vix_close.rolling(window=20).mean().iloc[-1]

            if np.isnan(current_vix) or np.isnan(vix_sma20):
                return 50

            # VIX 水平评分
            score = 50
            if current_vix < 13:
                score += 30
            elif current_vix < 18:
                score += 20
            elif current_vix < self.vix_threshold:
                score += 5
            elif current_vix < 30:
                score -= 15
            elif current_vix < 40:
                score -= 30
            else:
                score -= 45  # 极度恐慌

            # VIX 趋势（相对20日均线）
            vix_vs_sma = (current_vix - vix_sma20) / vix_sma20
            if vix_vs_sma > 0.3:
                score -= 10  # VIX 急速上升
            elif vix_vs_sma > 0.15:
                score -= 5
            elif vix_vs_sma < -0.15:
                score += 5   # VIX 回落

            return max(0, min(100, score))

        except Exception as e:
            logger.debug(f"VIX 信号计算失败: {e}")
            return 50

    def _credit_spread_signal(self, macro_data):
        """
        信用利差信号 → 0-100 分

        HYG (高收益) vs LQD (投资级) 的价格比：
        - 比值上升 → 信用环境改善（HYG 跑赢 LQD）→ 高分
        - 比值下降 → 信用紧缩（资金逃向安全资产）→ 低分
        """
        hyg = macro_data.get('hyg')
        lqd = macro_data.get('lqd')

        if hyg is None or lqd is None:
            return 50

        try:
            hyg_close = hyg['Close']
            lqd_close = lqd['Close']

            aligned = pd.DataFrame({'hyg': hyg_close, 'lqd': lqd_close}).dropna()
            if len(aligned) < self.credit_spread_window:
                return 50

            # HYG/LQD 比值
            ratio = aligned['hyg'] / aligned['lqd']
            ratio_sma = ratio.rolling(window=self.credit_spread_window, min_periods=20).mean()

            current_ratio = ratio.iloc[-1]
            sma_ratio = ratio_sma.iloc[-1]

            if np.isnan(current_ratio) or np.isnan(sma_ratio):
                return 50

            # 比值相对均线的位置
            pct_from_sma = (current_ratio - sma_ratio) / sma_ratio

            # 比值的变化趋势（60天）
            if len(ratio) > 60:
                ratio_change = (ratio.iloc[-1] - ratio.iloc[-60]) / ratio.iloc[-60]
            else:
                ratio_change = 0

            score = 50
            # 当前位置
            if pct_from_sma > 0.02:
                score += 20  # HYG 明显跑赢，信用宽松
            elif pct_from_sma > 0:
                score += 10
            elif pct_from_sma > -0.02:
                score -= 10
            else:
                score -= 25  # 信用紧缩

            # 趋势
            if ratio_change > 0.02:
                score += 10
            elif ratio_change < -0.03:
                score -= 15  # 信用快速恶化

            return max(0, min(100, score))

        except Exception as e:
            logger.debug(f"信用利差信号计算失败: {e}")
            return 50

    # ========== 序列版本（回测用） ==========

    def _yield_curve_series(self, macro_data):
        """生成收益率曲线信号的日频序列"""
        tnx = macro_data.get('tnx')
        irx = macro_data.get('irx')
        if tnx is None or irx is None:
            return None

        try:
            aligned = pd.DataFrame({
                'tnx': tnx['Close'], 'irx': irx['Close']
            }).dropna()
            if len(aligned) < self.yield_curve_window:
                return None

            spread = aligned['tnx'] - aligned['irx']
            spread_smooth = spread.rolling(window=self.yield_curve_window, min_periods=5).mean()
            spread_change_60d = spread_smooth - spread_smooth.shift(60)

            scores = pd.Series(index=aligned.index, dtype=float)
            for i in range(len(aligned)):
                s = spread_smooth.iloc[i]
                c = spread_change_60d.iloc[i] if i >= 60 else 0

                if np.isnan(s):
                    scores.iloc[i] = 50
                    continue

                score = 50
                if s > 1.5:
                    score += 30
                elif s > 0.5:
                    score += 15
                elif s > 0:
                    score += 0
                elif s > -0.5:
                    score -= 20
                else:
                    score -= 40

                if not np.isnan(c):
                    if c < -0.5:
                        score -= 10
                    elif c > 0.3:
                        score += 10

                scores.iloc[i] = max(0, min(100, score))

            return scores

        except Exception as e:
            logger.debug(f"收益率曲线序列计算失败: {e}")
            return None

    def _vix_series(self, macro_data):
        """生成 VIX 信号的日频序列"""
        vix = macro_data.get('vix')
        if vix is None:
            return None

        try:
            vix_close = vix['Close'].dropna()
            if len(vix_close) < 20:
                return None

            vix_sma20 = vix_close.rolling(window=20).mean()
            scores = pd.Series(index=vix_close.index, dtype=float)

            for i in range(len(vix_close)):
                v = vix_close.iloc[i]
                sma = vix_sma20.iloc[i]

                if np.isnan(v):
                    scores.iloc[i] = 50
                    continue

                score = 50
                if v < 13:
                    score += 30
                elif v < 18:
                    score += 20
                elif v < self.vix_threshold:
                    score += 5
                elif v < 30:
                    score -= 15
                elif v < 40:
                    score -= 30
                else:
                    score -= 45

                if not np.isnan(sma) and sma > 0:
                    vix_vs_sma = (v - sma) / sma
                    if vix_vs_sma > 0.3:
                        score -= 10
                    elif vix_vs_sma > 0.15:
                        score -= 5
                    elif vix_vs_sma < -0.15:
                        score += 5

                scores.iloc[i] = max(0, min(100, score))

            return scores

        except Exception as e:
            logger.debug(f"VIX 序列计算失败: {e}")
            return None

    def _credit_spread_series(self, macro_data):
        """生成信用利差信号的日频序列"""
        hyg = macro_data.get('hyg')
        lqd = macro_data.get('lqd')
        if hyg is None or lqd is None:
            return None

        try:
            aligned = pd.DataFrame({
                'hyg': hyg['Close'], 'lqd': lqd['Close']
            }).dropna()
            if len(aligned) < self.credit_spread_window:
                return None

            ratio = aligned['hyg'] / aligned['lqd']
            ratio_sma = ratio.rolling(window=self.credit_spread_window, min_periods=20).mean()
            ratio_change_60d = (ratio - ratio.shift(60)) / ratio.shift(60)

            scores = pd.Series(index=aligned.index, dtype=float)
            for i in range(len(aligned)):
                r = ratio.iloc[i]
                sma = ratio_sma.iloc[i]
                rc = ratio_change_60d.iloc[i] if i >= 60 else 0

                if np.isnan(r) or np.isnan(sma) or sma == 0:
                    scores.iloc[i] = 50
                    continue

                pct = (r - sma) / sma
                score = 50

                if pct > 0.02:
                    score += 20
                elif pct > 0:
                    score += 10
                elif pct > -0.02:
                    score -= 10
                else:
                    score -= 25

                if not np.isnan(rc):
                    if rc > 0.02:
                        score += 10
                    elif rc < -0.03:
                        score -= 15

                scores.iloc[i] = max(0, min(100, score))

            return scores

        except Exception as e:
            logger.debug(f"信用利差序列计算失败: {e}")
            return None

    # ========== 工具函数 ==========

    def _get_series_value(self, series, date, default=50):
        """从预计算序列中安全取值"""
        if series is None:
            return default
        if date in series.index:
            val = series.loc[date]
            return val if not np.isnan(val) else default
        # 找最近的前一个值
        prior = series.loc[:date]
        if len(prior) > 0:
            val = prior.iloc[-1]
            return val if not np.isnan(val) else default
        return default

    def _score_to_regime(self, composite_score):
        """合成分数 → 市场状态 + 仓位乘数

        阈值设计：只有多个信号同时恶化才触发减仓
        - BULL: 55+ (SMA 看多 + 至少1个跨资产信号正常即可)
        - CAUTION: 25-55 (SMA 看空 或 多个跨资产信号同时恶化)
        - BEAR: <25 (SMA 看空 + 跨资产信号全面恶化)
        """
        if composite_score >= 55:
            return self.BULL, 1.0
        elif composite_score >= 25:
            return self.CAUTION, 0.5
        else:
            return self.BEAR, 0.25

    def _default_regime(self):
        return {
            'regime': self.BULL,
            'position_multiplier': 1.0,
            'composite_score': 75,
            'signals': {
                'sma_score': 75,
                'yield_curve_score': 50,
                'vix_score': 50,
                'credit_spread_score': 50,
            },
            'current_price': 0,
        }
