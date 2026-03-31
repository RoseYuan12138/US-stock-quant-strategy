"""
基本面数据获取模块
使用 yfinance 获取市盈率、市净率、股息率、分析师评级等基本面数据
未来可接入 Morningstar MCP / S&P Global MCP 补充 fair value 和 moat 评级
"""

import logging
import json
import numpy as np
import pandas as pd
import yfinance as yf
from pathlib import Path
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class FundamentalFetcher:
    """基本面数据获取器"""

    def __init__(self, cache_dir="./data/cache/fundamentals"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch_fundamentals(self, ticker, use_cache=True):
        """
        获取单只股票的基本面数据

        Returns:
            dict 包含:
            - pe_ratio: 市盈率 (trailing)
            - forward_pe: 前瞻市盈率
            - pb_ratio: 市净率
            - ps_ratio: 市销率
            - dividend_yield: 股息率
            - payout_ratio: 派息率
            - roe: 净资产收益率
            - debt_to_equity: 负债权益比
            - current_ratio: 流动比率
            - revenue_growth: 营收增长率
            - earnings_growth: 盈利增长率
            - profit_margin: 净利润率
            - analyst_rating: 分析师评级 (1-5, 5=strong buy)
            - target_price: 分析师目标价
            - current_price: 当前价格
            - market_cap: 市值
            - sector: 行业
            - beta: 贝塔系数
        """
        ticker = ticker.upper()

        # 尝试缓存
        if use_cache:
            cached = self._load_cache(ticker)
            if cached is not None:
                return cached

        try:
            stock = yf.Ticker(ticker)
            info = stock.info

            fundamentals = {
                'ticker': ticker,
                'fetch_date': datetime.now().isoformat(),
                'current_price': info.get('currentPrice') or info.get('regularMarketPrice', 0),
                'market_cap': info.get('marketCap', 0),
                'sector': info.get('sector', 'Unknown'),
                'industry': info.get('industry', 'Unknown'),

                # 估值指标
                'pe_ratio': info.get('trailingPE'),
                'forward_pe': info.get('forwardPE'),
                'pb_ratio': info.get('priceToBook'),
                'ps_ratio': info.get('priceToSalesTrailing12Months'),
                'peg_ratio': info.get('pegRatio'),
                'ev_to_ebitda': info.get('enterpriseToEbitda'),

                # 盈利能力
                'profit_margin': info.get('profitMargins'),
                'operating_margin': info.get('operatingMargins'),
                'roe': info.get('returnOnEquity'),
                'roa': info.get('returnOnAssets'),

                # 成长性
                'revenue_growth': info.get('revenueGrowth'),
                'earnings_growth': info.get('earningsGrowth'),
                'earnings_quarterly_growth': info.get('earningsQuarterlyGrowth'),

                # 分红
                'dividend_yield': info.get('dividendYield'),
                'payout_ratio': info.get('payoutRatio'),
                'five_year_avg_dividend_yield': info.get('fiveYearAvgDividendYield'),

                # 财务健康
                'debt_to_equity': info.get('debtToEquity'),
                'current_ratio': info.get('currentRatio'),
                'quick_ratio': info.get('quickRatio'),
                'total_cash_per_share': info.get('totalCashPerShare'),

                # 风险指标
                'beta': info.get('beta'),
                'short_percent_of_float': info.get('shortPercentOfFloat'),

                # 分析师评级
                'analyst_rating': self._parse_recommendation(info.get('recommendationKey', '')),
                'analyst_mean_rating': info.get('recommendationMean'),  # 1=strong buy, 5=sell
                'target_mean_price': info.get('targetMeanPrice'),
                'target_low_price': info.get('targetLowPrice'),
                'target_high_price': info.get('targetHighPrice'),
                'number_of_analysts': info.get('numberOfAnalystOpinions', 0),

                # 估值折扣 (目标价 vs 当前价)
                'upside_pct': self._calc_upside(
                    info.get('currentPrice') or info.get('regularMarketPrice', 0),
                    info.get('targetMeanPrice')
                ),
            }

            # 缓存
            self._save_cache(ticker, fundamentals)
            logger.info(f"{ticker}: 基本面数据获取成功")
            return fundamentals

        except Exception as e:
            logger.error(f"{ticker}: 基本面数据获取失败 - {e}")
            return None

    def fetch_batch(self, tickers):
        """批量获取基本面数据"""
        results = {}
        for ticker in tickers:
            data = self.fetch_fundamentals(ticker)
            if data is not None:
                results[ticker] = data
        return results

    def _parse_recommendation(self, rec_key):
        """
        将 yfinance 推荐转换为 1-5 评分
        strong_buy=5, buy=4, hold=3, underperform=2, sell=1
        """
        mapping = {
            'strong_buy': 5, 'buy': 4, 'hold': 3,
            'underperform': 2, 'sell': 1, 'strong_sell': 1
        }
        return mapping.get(rec_key, 0)

    def _calc_upside(self, current, target):
        """计算目标价相对当前价的上涨空间"""
        if current and target and current > 0:
            return (target - current) / current * 100
        return None

    def _save_cache(self, ticker, data):
        cache_file = self.cache_dir / f"{ticker}.json"
        try:
            with open(cache_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"{ticker}: 缓存保存失败 - {e}")

    def _load_cache(self, ticker):
        """加载缓存（24小时有效）"""
        cache_file = self.cache_dir / f"{ticker}.json"
        if not cache_file.exists():
            return None
        try:
            with open(cache_file, 'r') as f:
                data = json.load(f)
            # 检查是否过期（24小时）
            fetch_date = datetime.fromisoformat(data.get('fetch_date', '2000-01-01'))
            if datetime.now() - fetch_date > timedelta(hours=24):
                return None
            logger.info(f"{ticker}: 使用基本面缓存")
            return data
        except Exception:
            return None


class ValueScreener:
    """
    价值筛选器
    根据基本面指标对股票进行评分和筛选

    评分维度:
    1. 估值 (便宜程度)  - 30%
    2. 质量 (盈利能力)  - 25%
    3. 成长性           - 20%
    4. 分析师共识       - 15%
    5. 财务健康         - 10%
    """

    # 行业 PE 中位数参考（大致值，用于相对估值）
    SECTOR_PE_MEDIAN = {
        'Technology': 30,
        'Financial Services': 14,
        'Healthcare': 22,
        'Consumer Cyclical': 22,
        'Consumer Defensive': 24,
        'Energy': 12,
        'Industrials': 20,
        'Communication Services': 18,
        'Basic Materials': 15,
        'Real Estate': 35,
        'Utilities': 18,
    }

    def score_stock(self, fundamentals):
        """
        对单只股票评分 (0-100)

        Returns:
            dict: {
                total_score: 综合得分,
                valuation_score: 估值得分,
                quality_score: 质量得分,
                growth_score: 成长得分,
                analyst_score: 分析师得分,
                health_score: 财务健康得分,
                signal: 'BUY' / 'HOLD' / 'AVOID',
                reasons: [理由列表]
            }
        """
        if fundamentals is None:
            return None

        scores = {}
        reasons = []

        # 1. 估值评分 (30%)
        scores['valuation'] = self._score_valuation(fundamentals, reasons)

        # 2. 质量评分 (25%)
        scores['quality'] = self._score_quality(fundamentals, reasons)

        # 3. 成长性评分 (20%)
        scores['growth'] = self._score_growth(fundamentals, reasons)

        # 4. 分析师评分 (15%)
        scores['analyst'] = self._score_analyst(fundamentals, reasons)

        # 5. 财务健康评分 (10%)
        scores['health'] = self._score_health(fundamentals, reasons)

        # 加权总分
        total = (
            scores['valuation'] * 0.30 +
            scores['quality'] * 0.25 +
            scores['growth'] * 0.20 +
            scores['analyst'] * 0.15 +
            scores['health'] * 0.10
        )

        # 信号判断
        if total >= 70:
            signal = 'BUY'
        elif total >= 50:
            signal = 'HOLD'
        else:
            signal = 'AVOID'

        return {
            'ticker': fundamentals.get('ticker', ''),
            'total_score': round(total, 1),
            'valuation_score': round(scores['valuation'], 1),
            'quality_score': round(scores['quality'], 1),
            'growth_score': round(scores['growth'], 1),
            'analyst_score': round(scores['analyst'], 1),
            'health_score': round(scores['health'], 1),
            'signal': signal,
            'reasons': reasons,
        }

    def _score_valuation(self, f, reasons):
        """估值评分：PE/PB/PS 相对行业水平，目标价上涨空间"""
        score = 50  # 基础分

        # PE 相对估值
        pe = f.get('pe_ratio')
        sector = f.get('sector', 'Unknown')
        sector_pe = self.SECTOR_PE_MEDIAN.get(sector, 20)

        if pe is not None and pe > 0:
            pe_ratio_vs_sector = pe / sector_pe
            if pe_ratio_vs_sector < 0.7:
                score += 20
                reasons.append(f"估值便宜: PE {pe:.1f} 远低于行业 {sector_pe}")
            elif pe_ratio_vs_sector < 1.0:
                score += 10
                reasons.append(f"估值合理偏低: PE {pe:.1f} vs 行业 {sector_pe}")
            elif pe_ratio_vs_sector > 1.5:
                score -= 15
                reasons.append(f"估值偏高: PE {pe:.1f} 远高于行业 {sector_pe}")
            elif pe_ratio_vs_sector > 1.2:
                score -= 5
        elif pe is not None and pe < 0:
            score -= 20
            reasons.append("公司亏损 (PE 为负)")

        # Forward PE vs Trailing PE (盈利预期改善?)
        fwd_pe = f.get('forward_pe')
        if pe and fwd_pe and pe > 0 and fwd_pe > 0:
            if fwd_pe < pe * 0.85:
                score += 10
                reasons.append(f"盈利预期改善: Forward PE {fwd_pe:.1f} < Trailing {pe:.1f}")

        # 目标价上涨空间
        upside = f.get('upside_pct')
        if upside is not None:
            if upside > 30:
                score += 15
                reasons.append(f"分析师目标价有 {upside:.0f}% 上涨空间")
            elif upside > 15:
                score += 8
            elif upside < -10:
                score -= 10
                reasons.append(f"分析师目标价已低于现价 {upside:.0f}%")

        # PEG ratio
        peg = f.get('peg_ratio')
        if peg is not None and peg > 0:
            if peg < 1.0:
                score += 5
            elif peg > 3.0:
                score -= 5

        return max(0, min(100, score))

    def _score_quality(self, f, reasons):
        """质量评分：ROE、利润率、盈利稳定性"""
        score = 50

        # ROE
        roe = f.get('roe')
        if roe is not None:
            if roe > 0.25:
                score += 20
                reasons.append(f"优秀 ROE: {roe*100:.1f}%")
            elif roe > 0.15:
                score += 10
            elif roe > 0.08:
                score += 0
            elif roe > 0:
                score -= 5
            else:
                score -= 15
                reasons.append(f"ROE 为负: {roe*100:.1f}%")

        # 利润率
        margin = f.get('profit_margin')
        if margin is not None:
            if margin > 0.25:
                score += 15
                reasons.append(f"高利润率: {margin*100:.1f}%")
            elif margin > 0.15:
                score += 8
            elif margin > 0.05:
                score += 0
            elif margin > 0:
                score -= 5
            else:
                score -= 15

        # 运营利润率
        op_margin = f.get('operating_margin')
        if op_margin is not None:
            if op_margin > 0.30:
                score += 10
            elif op_margin > 0.15:
                score += 5

        return max(0, min(100, score))

    def _score_growth(self, f, reasons):
        """成长性评分：营收增长、盈利增长"""
        score = 50

        # 营收增长
        rev_growth = f.get('revenue_growth')
        if rev_growth is not None:
            if rev_growth > 0.25:
                score += 20
                reasons.append(f"强劲营收增长: {rev_growth*100:.1f}%")
            elif rev_growth > 0.10:
                score += 10
            elif rev_growth > 0:
                score += 3
            elif rev_growth > -0.10:
                score -= 5
            else:
                score -= 15
                reasons.append(f"营收下滑: {rev_growth*100:.1f}%")

        # 盈利增长
        earn_growth = f.get('earnings_growth')
        if earn_growth is not None:
            if earn_growth > 0.30:
                score += 15
            elif earn_growth > 0.10:
                score += 8
            elif earn_growth > 0:
                score += 3
            elif earn_growth > -0.20:
                score -= 5
            else:
                score -= 15

        return max(0, min(100, score))

    def _score_analyst(self, f, reasons):
        """分析师评分"""
        score = 50

        # 分析师推荐
        mean_rating = f.get('analyst_mean_rating')  # 1=strong buy, 5=sell
        n_analysts = f.get('number_of_analysts', 0)

        if mean_rating and n_analysts >= 5:
            if mean_rating <= 1.5:
                score += 25
                reasons.append(f"分析师强烈推荐买入 (评分 {mean_rating:.1f}, {n_analysts}人)")
            elif mean_rating <= 2.0:
                score += 15
            elif mean_rating <= 2.5:
                score += 8
            elif mean_rating <= 3.0:
                score += 0
            elif mean_rating <= 3.5:
                score -= 10
            else:
                score -= 20
                reasons.append(f"分析师偏空 (评分 {mean_rating:.1f})")
        elif n_analysts < 5:
            score -= 5  # 分析师覆盖不足

        return max(0, min(100, score))

    def _score_health(self, f, reasons):
        """财务健康评分"""
        score = 50

        # 负债率
        dte = f.get('debt_to_equity')
        if dte is not None:
            if dte < 30:
                score += 15
            elif dte < 80:
                score += 5
            elif dte < 150:
                score -= 5
            else:
                score -= 15
                reasons.append(f"高负债: D/E={dte:.0f}")

        # 流动比率
        cr = f.get('current_ratio')
        if cr is not None:
            if cr > 2.0:
                score += 10
            elif cr > 1.5:
                score += 5
            elif cr < 1.0:
                score -= 10
                reasons.append(f"流动性风险: 流动比率 {cr:.2f}")

        return max(0, min(100, score))

    def screen_universe(self, fundamentals_dict):
        """
        对一组股票进行筛选评分

        Args:
            fundamentals_dict: {ticker: fundamentals_data}

        Returns:
            pd.DataFrame: 按分数排序的评分结果
        """
        results = []
        for ticker, fund_data in fundamentals_dict.items():
            score = self.score_stock(fund_data)
            if score:
                score['current_price'] = fund_data.get('current_price', 0)
                score['pe_ratio'] = fund_data.get('pe_ratio')
                score['dividend_yield'] = fund_data.get('dividend_yield')
                score['sector'] = fund_data.get('sector', '')
                score['upside_pct'] = fund_data.get('upside_pct')
                results.append(score)

        if not results:
            return pd.DataFrame()

        df = pd.DataFrame(results)
        df = df.sort_values('total_score', ascending=False)
        return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    fetcher = FundamentalFetcher()
    screener = ValueScreener()

    tickers = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'JPM', 'JNJ', 'PFE', 'KO']

    print("获取基本面数据...")
    fund_data = fetcher.fetch_batch(tickers)

    print(f"\n筛选评分 ({len(fund_data)} 只股票):\n")
    df = screener.screen_universe(fund_data)

    for _, row in df.iterrows():
        pe_str = f"{row['pe_ratio']:.1f}" if pd.notna(row['pe_ratio']) else "N/A"
        div_str = f"{row['dividend_yield']*100:.1f}%" if pd.notna(row['dividend_yield']) and row['dividend_yield'] else "N/A"
        upside_str = f"{row['upside_pct']:.0f}%" if pd.notna(row['upside_pct']) else "N/A"

        print(f"  {row['signal']:5s} | {row['ticker']:6s} | "
              f"得分 {row['total_score']:5.1f} | "
              f"PE {pe_str:>6s} | 股息 {div_str:>6s} | "
              f"上涨空间 {upside_str:>5s} | "
              f"{row['sector']}")

    print(f"\nBUY 信号: {len(df[df['signal']=='BUY'])} 只")
    print(f"HOLD 信号: {len(df[df['signal']=='HOLD'])} 只")
    print(f"AVOID 信号: {len(df[df['signal']=='AVOID'])} 只")
