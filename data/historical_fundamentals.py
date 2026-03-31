"""
历史基本面数据模块
解决前视偏差：用每个时间点已知的财务数据做评分，而不是用当前快照

数据源：
  - yfinance（原始 HistoricalFundamentalFetcher，仅近4-8季度）
  - FMP parquet（FMPHistoricalFundamentalFetcher，2010-2025，真正的 PIT）

评分逻辑：PE, 利润率, ROE, 营收增长, 负债率
"""

import logging
import json
import numpy as np
import pandas as pd
import yfinance as yf
from pathlib import Path
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class HistoricalFundamentalFetcher:
    """
    获取历史季度财报数据，构建时间序列基本面评分

    用法：
        fetcher = HistoricalFundamentalFetcher()
        scores = fetcher.get_score_at_date("AAPL", "2023-06-01")
        # 返回截至 2023-06-01 已公开的最新财报数据的评分
    """

    def __init__(self, cache_dir="./data/cache/hist_fundamentals"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._ticker_cache = {}  # {ticker: processed_data}

    def load_ticker(self, ticker):
        """
        加载一只股票的全部历史财报数据并预处理

        Returns:
            dict with keys: 'quarterly_scores' (list of {date, score, metrics})
        """
        ticker = ticker.upper()

        if ticker in self._ticker_cache:
            return self._ticker_cache[ticker]

        # 尝试从磁盘缓存加载
        cache_file = self.cache_dir / f"{ticker}.json"
        if cache_file.exists():
            try:
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                # 检查缓存是否过期（7天）
                if data.get('fetch_date'):
                    fetch_dt = datetime.fromisoformat(data['fetch_date'])
                    if datetime.now() - fetch_dt < timedelta(days=7):
                        self._ticker_cache[ticker] = data
                        return data
            except Exception:
                pass

        # 从 yfinance 获取
        data = self._fetch_and_process(ticker)
        if data:
            self._ticker_cache[ticker] = data
            # 保存缓存
            try:
                with open(cache_file, 'w') as f:
                    json.dump(data, f, indent=2, default=str)
            except Exception as e:
                logger.warning(f"{ticker}: 缓存保存失败 - {e}")

        return data

    def get_score_at_date(self, ticker, target_date):
        """
        获取截至 target_date 已公开的最新基本面评分

        财报通常在季度结束后 1-2 个月发布，所以：
        - target_date = 2023-06-01 → 用的可能是 2023-Q1（3月结束，5月发布）的数据
        - 我们简化假设：季度结束后 60 天数据可用

        Args:
            ticker: 股票代码
            target_date: 评分日期（str 或 datetime）

        Returns:
            dict: {'score': float, 'metrics': dict} or None
        """
        data = self.load_ticker(ticker)
        if not data or not data.get('quarterly_scores'):
            return None

        if isinstance(target_date, str):
            target_date = pd.Timestamp(target_date)

        # 找到 target_date 之前最近的一条评分
        best = None
        for qs in data['quarterly_scores']:
            available_date = pd.Timestamp(qs['available_date'])
            if available_date <= target_date:
                if best is None or available_date > pd.Timestamp(best['available_date']):
                    best = qs

        return best

    def get_scores_timeseries(self, ticker):
        """
        获取一只股票的全部历史评分序列

        Returns:
            list of dict: [{'available_date': str, 'score': float, 'metrics': dict}, ...]
        """
        data = self.load_ticker(ticker)
        if not data:
            return []
        return data.get('quarterly_scores', [])

    def _fetch_and_process(self, ticker):
        """从 yfinance 获取并处理历史财报数据"""
        try:
            stock = yf.Ticker(ticker)

            # 获取季度财报
            income = stock.quarterly_income_stmt
            balance = stock.quarterly_balance_sheet
            # 获取当前价格信息用于 sector
            info = stock.info
            sector = info.get('sector', 'Unknown')

            if income is None or income.empty:
                logger.warning(f"{ticker}: 无季度财报数据")
                return None

            # 获取历史价格（用于计算 PE）
            hist = stock.history(period="max", interval="1d")
            if hist.empty:
                logger.warning(f"{ticker}: 无历史价格数据")
                return None

            quarterly_scores = []

            # income 的列是日期（季度结束日期），行是指标
            for col_date in income.columns:
                quarter_end = pd.Timestamp(col_date)
                # 假设财报在季度结束后 60 天可用
                available_date = quarter_end + timedelta(days=60)

                metrics = self._extract_metrics(
                    ticker, quarter_end, income, balance, hist, sector
                )

                if metrics:
                    score = self._score_from_metrics(metrics)
                    quarterly_scores.append({
                        'quarter_end': str(quarter_end.date()),
                        'available_date': str(available_date.date()),
                        'score': score,
                        'metrics': metrics,
                    })

            # 按日期排序
            quarterly_scores.sort(key=lambda x: x['available_date'])

            return {
                'ticker': ticker,
                'sector': sector,
                'fetch_date': datetime.now().isoformat(),
                'quarterly_scores': quarterly_scores,
            }

        except Exception as e:
            logger.error(f"{ticker}: 历史基本面获取失败 - {e}")
            return None

    def _extract_metrics(self, ticker, quarter_end, income, balance, hist, sector):
        """从财报中提取关键指标"""
        try:
            # 获取该季度的数据
            if quarter_end not in income.columns:
                return None

            inc = income[quarter_end]

            # 净利润
            net_income = self._safe_get(inc, ['Net Income', 'Net Income Common Stockholders'])
            revenue = self._safe_get(inc, ['Total Revenue', 'Operating Revenue'])
            operating_income = self._safe_get(inc, ['Operating Income', 'EBIT'])

            # 资产负债表
            bal = None
            if balance is not None and quarter_end in balance.columns:
                bal = balance[quarter_end]

            total_equity = None
            total_debt = None
            total_assets = None
            if bal is not None:
                total_equity = self._safe_get(bal, ['Stockholders Equity', 'Total Equity Gross Minority Interest', 'Common Stock Equity'])
                total_debt = self._safe_get(bal, ['Total Debt', 'Long Term Debt'])
                total_assets = self._safe_get(bal, ['Total Assets'])

            # 用季度结束时的价格算 PE
            # 找到最接近 quarter_end 的价格
            pe = None
            price_at_quarter = None
            if not hist.empty and net_income and net_income != 0:
                nearby = hist.loc[:quarter_end]
                if len(nearby) > 0:
                    price_at_quarter = nearby['Close'].iloc[-1]
                    # 年化净利润 = 季度 * 4（简化）
                    # 需要 shares outstanding 来算 EPS
                    # 用 market_cap / price 估算 shares
                    shares = self._safe_get(inc, ['Diluted Average Shares', 'Basic Average Shares'])
                    if shares and shares > 0:
                        annual_eps = (net_income / shares) * 4
                        if annual_eps > 0:
                            pe = price_at_quarter / annual_eps

            # 利润率
            profit_margin = None
            if revenue and revenue > 0 and net_income is not None:
                profit_margin = net_income / revenue

            operating_margin = None
            if revenue and revenue > 0 and operating_income is not None:
                operating_margin = operating_income / revenue

            # ROE（年化）
            roe = None
            if total_equity and total_equity > 0 and net_income is not None:
                roe = (net_income * 4) / total_equity

            # 负债权益比
            debt_to_equity = None
            if total_equity and total_equity > 0 and total_debt is not None:
                debt_to_equity = total_debt / total_equity * 100

            # 营收增长（同比需要4个季度前的数据）
            revenue_growth = None
            col_list = list(income.columns)
            current_idx = col_list.index(quarter_end)
            if current_idx + 4 < len(col_list):
                prev_quarter = col_list[current_idx + 4]  # yfinance columns are newest-first
                prev_rev = self._safe_get(income[prev_quarter], ['Total Revenue', 'Operating Revenue'])
                if prev_rev and prev_rev > 0 and revenue:
                    revenue_growth = (revenue - prev_rev) / prev_rev

            return {
                'pe': pe,
                'profit_margin': profit_margin,
                'operating_margin': operating_margin,
                'roe': roe,
                'debt_to_equity': debt_to_equity,
                'revenue_growth': revenue_growth,
                'revenue': revenue,
                'net_income': net_income,
                'price': price_at_quarter,
                'sector': sector,
            }

        except Exception as e:
            logger.debug(f"{ticker} {quarter_end}: 指标提取失败 - {e}")
            return None

    def _safe_get(self, series, keys):
        """安全获取 Series 中的值，尝试多个 key"""
        for key in keys:
            if key in series.index:
                val = series[key]
                if pd.notna(val) and val != 0:
                    return float(val)
        return None

    def _score_from_metrics(self, m):
        """
        从历史指标计算评分 (0-100)

        简化版评分，只用财报可推导的指标：
        - 估值 (PE): 30%
        - 质量 (利润率, ROE): 30%
        - 成长性 (营收增长): 25%
        - 财务健康 (负债率): 15%
        """
        score = 50  # 基础分

        # 估值 (PE)
        pe = m.get('pe')
        if pe is not None and pe > 0:
            if pe < 12:
                score += 12
            elif pe < 18:
                score += 8
            elif pe < 25:
                score += 3
            elif pe < 35:
                score -= 3
            elif pe < 50:
                score -= 8
            else:
                score -= 12

        # 质量
        margin = m.get('profit_margin')
        if margin is not None:
            if margin > 0.25:
                score += 10
            elif margin > 0.15:
                score += 6
            elif margin > 0.05:
                score += 2
            elif margin > 0:
                score -= 2
            else:
                score -= 8

        roe = m.get('roe')
        if roe is not None:
            if roe > 0.25:
                score += 10
            elif roe > 0.15:
                score += 6
            elif roe > 0.08:
                score += 2
            elif roe > 0:
                score -= 2
            else:
                score -= 8

        # 成长性
        rev_growth = m.get('revenue_growth')
        if rev_growth is not None:
            if rev_growth > 0.25:
                score += 12
            elif rev_growth > 0.10:
                score += 7
            elif rev_growth > 0:
                score += 2
            elif rev_growth > -0.10:
                score -= 3
            else:
                score -= 10

        # 财务健康
        dte = m.get('debt_to_equity')
        if dte is not None:
            if dte < 30:
                score += 6
            elif dte < 80:
                score += 2
            elif dte < 150:
                score -= 2
            else:
                score -= 6

        return max(0, min(100, round(score, 1)))


class FMPHistoricalFundamentalFetcher:
    """
    基于 FMP parquet 数据的历史基本面评分器。
    接口与 HistoricalFundamentalFetcher 完全兼容。

    优势：
    - 真正的 Point-in-Time（用 filingDate，不是财报期末）
    - 覆盖 2010-2025 全历史
    - 无网络调用，全离线
    """

    DEFAULT_PARQUET = Path(__file__).parent.parent / "fmp-datasource/cache/fundamentals_merged.parquet"

    def __init__(self, parquet_path=None):
        path = Path(parquet_path) if parquet_path else self.DEFAULT_PARQUET
        if not path.exists():
            raise FileNotFoundError(f"FMP fundamentals parquet not found: {path}")
        df = pd.read_parquet(path)
        df["filingDate"] = pd.to_datetime(df["filingDate"], errors="coerce")
        df = df.dropna(subset=["filingDate", "symbol"])
        df = df.sort_values(["symbol", "filingDate"]).reset_index(drop=True)
        self._df = df
        self._ticker_cache = {}

    def _get_ticker_df(self, ticker):
        ticker = ticker.upper()
        if ticker not in self._ticker_cache:
            self._ticker_cache[ticker] = self._df[self._df["symbol"] == ticker].copy()
        return self._ticker_cache[ticker]

    def get_score_at_date(self, ticker, target_date):
        """
        返回截至 target_date 最新已申报数据的评分，格式与原类一致。
        """
        tdf = self._get_ticker_df(ticker)
        if tdf.empty:
            return None

        target_ts = pd.Timestamp(target_date)
        available = tdf[tdf["filingDate"] <= target_ts]
        if available.empty:
            return None

        row = available.iloc[-1]
        metrics = self._compute_metrics(row, tdf, available)
        score = self._score_from_metrics(metrics)
        return {
            "quarter_end": str(row.get("date", ""))[:10],
            "available_date": str(row["filingDate"].date()),
            "score": score,
            "metrics": metrics,
        }

    def get_scores_timeseries(self, ticker):
        tdf = self._get_ticker_df(ticker)
        results = []
        for i in range(len(tdf)):
            row = tdf.iloc[i]
            available_so_far = tdf.iloc[: i + 1]
            metrics = self._compute_metrics(row, tdf, available_so_far)
            score = self._score_from_metrics(metrics)
            results.append({
                "quarter_end": str(row.get("date", ""))[:10],
                "available_date": str(row["filingDate"].date()),
                "score": score,
                "metrics": metrics,
            })
        return results

    def load_ticker(self, ticker):
        """兼容原类接口，预热缓存用。"""
        self._get_ticker_df(ticker)
        return True

    def _safe(self, row, col):
        v = row.get(col)
        if v is None:
            return None
        try:
            f = float(v)
            return f if pd.notna(f) and f != 0 else None
        except Exception:
            return None

    def _compute_metrics(self, row, full_tdf, available_tdf):
        revenue = self._safe(row, "revenue")
        net_income = self._safe(row, "netIncome")
        operating_income = self._safe(row, "operatingIncome")
        total_equity = self._safe(row, "totalEquity") or self._safe(row, "totalStockholdersEquity")
        total_debt = self._safe(row, "totalDebt")

        profit_margin = (net_income / revenue) if revenue and net_income is not None else None
        operating_margin = (operating_income / revenue) if revenue and operating_income is not None else None
        roe = ((net_income * 4) / total_equity) if total_equity and net_income is not None else None
        debt_to_equity = (total_debt / total_equity * 100) if total_equity and total_debt is not None else None

        # YoY 营收增长：和4行前比（约1年）
        revenue_growth = None
        idx = available_tdf.index.get_loc(row.name) if row.name in available_tdf.index else -1
        if idx >= 4:
            prev_rev = self._safe(available_tdf.iloc[idx - 4], "revenue")
            if prev_rev and prev_rev > 0 and revenue:
                revenue_growth = (revenue - prev_rev) / prev_rev

        return {
            "pe": None,  # 无价格数据，跳过
            "profit_margin": profit_margin,
            "operating_margin": operating_margin,
            "roe": roe,
            "debt_to_equity": debt_to_equity,
            "revenue_growth": revenue_growth,
            "revenue": revenue,
            "net_income": net_income,
        }

    def _score_from_metrics(self, m):
        score = 50

        margin = m.get("profit_margin")
        if margin is not None:
            if margin > 0.25:   score += 10
            elif margin > 0.15: score += 6
            elif margin > 0.05: score += 2
            elif margin > 0:    score -= 2
            else:               score -= 8

        roe = m.get("roe")
        if roe is not None:
            if roe > 0.25:   score += 10
            elif roe > 0.15: score += 6
            elif roe > 0.08: score += 2
            elif roe > 0:    score -= 2
            else:            score -= 8

        rev_growth = m.get("revenue_growth")
        if rev_growth is not None:
            if rev_growth > 0.25:   score += 12
            elif rev_growth > 0.10: score += 7
            elif rev_growth > 0:    score += 2
            elif rev_growth > -0.10: score -= 3
            else:                   score -= 10

        dte = m.get("debt_to_equity")
        if dte is not None:
            if dte < 30:    score += 6
            elif dte < 80:  score += 2
            elif dte < 150: score -= 2
            else:           score -= 6

        return max(0, min(100, round(score, 1)))
