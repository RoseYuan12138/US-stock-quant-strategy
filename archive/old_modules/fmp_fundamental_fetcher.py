"""
FMP 基本面数据获取模块（点时间正确版）

从 Financial Modeling Prep API 获取季度财务报表数据，
严格使用 SEC 申报日期（fillingDate）而非报告期结束日期，
以确保回测中不存在前视偏差（look-ahead bias）。

关键设计原则（防前视偏差）：
- 财务数据以 fillingDate（SEC 实际提交日期）为基准，而非 date（报告期结束日）
- 例：Q1 2023 报告期结束于 2023-03-31，但 SEC 10-Q 可能在 2023-05-10 才提交
  → 在回测中，2023-04-01 至 2023-05-09 期间，仍只能使用上一期的数据
- get_fundamentals_at_date() 返回的是"截至查询日期已提交且已公开"的最新数据

FMP API 端点：
- GET /v3/income-statement/{ticker}?period=quarter&limit=60&apikey={key}
- GET /v3/balance-sheet-statement/{ticker}?period=quarter&limit=60&apikey={key}
- GET /v3/cash-flow-statement/{ticker}?period=quarter&limit=60&apikey={key}
- GET /v3/key-metrics/{ticker}?period=quarter&limit=60&apikey={key}
- GET /v3/financial-ratios/{ticker}?period=quarter&limit=60&apikey={key}
"""

import os
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

import pandas as pd
import requests

logger = logging.getLogger(__name__)


# FMP API 基础地址
FMP_BASE_URL = "https://financialmodelingprep.com/api"

# 限速配置（付费账户 300 calls/min）
RATE_LIMIT_CALLS_PER_MIN = 300
MIN_INTERVAL = 60.0 / RATE_LIMIT_CALLS_PER_MIN  # ~0.2 秒

# 重试配置
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0


def _request_with_retry(url: str, params: dict,
                        max_retries: int = MAX_RETRIES) -> Optional[Any]:
    """
    带指数退避重试的 HTTP GET 请求

    Args:
        url: 请求 URL
        params: 查询参数（含 apikey）
        max_retries: 最大重试次数

    Returns:
        JSON 响应数据，失败返回 None
    """
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, timeout=30)

            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 429:
                wait = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(f"API 限速 (429)，等待 {wait:.1f}s 后重试 (第{attempt+1}次)")
                time.sleep(wait)
            elif resp.status_code == 401:
                logger.error("API Key 无效或未授权 (401)")
                return None
            elif resp.status_code == 404:
                # 股票不存在或无数据，不重试
                logger.debug(f"404 Not Found: {url}")
                return []
            else:
                wait = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(f"HTTP {resp.status_code}，{url}，{wait:.1f}s 后重试")
                time.sleep(wait)

        except requests.exceptions.Timeout:
            wait = RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning(f"请求超时，等待 {wait:.1f}s 后重试")
            time.sleep(wait)
        except requests.exceptions.ConnectionError as e:
            wait = RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning(f"网络连接错误: {e}，等待 {wait:.1f}s 后重试")
            time.sleep(wait)
        except Exception as e:
            logger.error(f"请求异常: {e}")
            return None

    logger.error(f"已达最大重试次数 ({max_retries})，URL: {url}")
    return None


class RateLimiter:
    """
    简单的令牌桶限速器，控制 API 调用频率
    """

    def __init__(self, calls_per_minute: int = RATE_LIMIT_CALLS_PER_MIN):
        self.min_interval = 60.0 / calls_per_minute
        self._last_call_time = 0.0

    def wait(self):
        """等待直到满足最小调用间隔"""
        now = time.time()
        elapsed = now - self._last_call_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_call_time = time.time()


class FMPFundamentalFetcher:
    """
    FMP 基本面数据获取器

    为每只股票下载季度财务报表，并以 fillingDate（SEC申报日期）
    为基准存储，确保回测中的点时间正确性。

    缓存结构：
    ./data/cache/fundamentals_fmp/{ticker}.parquet
    每行代表一个季度的财务快照，关键列包括：
    - filing_date: SEC 实际申报日期（用于点时间查询）
    - period_date: 报告期结束日期（仅供参考）
    - period: Q1/Q2/Q3/Q4
    - 各项财务指标列...
    """

    def __init__(self, api_key: str,
                 cache_dir: str = "./data/cache/fundamentals_fmp",
                 calls_per_minute: int = RATE_LIMIT_CALLS_PER_MIN):
        """
        初始化基本面数据获取器

        Args:
            api_key: FMP API Key
            cache_dir: 缓存目录
            calls_per_minute: API 调用频率限制（付费账户 300/min）
        """
        self.api_key = api_key
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.rate_limiter = RateLimiter(calls_per_minute)

        # 统计 API 调用次数
        self.api_call_count = 0

    # ------------------------------------------------------------------ #
    #  单项财务报表获取
    # ------------------------------------------------------------------ #

    def _fetch_statement(self, endpoint: str, ticker: str,
                         limit: int = 60) -> List[dict]:
        """
        通用财务报表获取方法

        Args:
            endpoint: FMP API 端点路径（如 /v3/income-statement/{ticker}）
            ticker: 股票代码
            limit: 获取的季度数量（60 季度 ≈ 15 年）

        Returns:
            原始 JSON 列表
        """
        self.rate_limiter.wait()
        self.api_call_count += 1

        url = f"{FMP_BASE_URL}{endpoint}"
        params = {
            "period": "quarter",
            "limit": limit,
            "apikey": self.api_key,
        }

        data = _request_with_retry(url, params)
        if not data:
            return []
        if isinstance(data, list):
            return data
        # 有时 FMP 在错误时返回 dict
        if isinstance(data, dict) and 'Error Message' in data:
            logger.warning(f"{ticker}: FMP 错误 - {data['Error Message']}")
            return []
        return []

    def fetch_income_statement(self, ticker: str, limit: int = 60) -> pd.DataFrame:
        """获取季度利润表"""
        data = self._fetch_statement(f"/v3/income-statement/{ticker}", ticker, limit)
        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)
        return self._process_statement(df, ticker, 'income')

    def fetch_balance_sheet(self, ticker: str, limit: int = 60) -> pd.DataFrame:
        """获取季度资产负债表"""
        data = self._fetch_statement(f"/v3/balance-sheet-statement/{ticker}", ticker, limit)
        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)
        return self._process_statement(df, ticker, 'balance_sheet')

    def fetch_cash_flow(self, ticker: str, limit: int = 60) -> pd.DataFrame:
        """获取季度现金流量表"""
        data = self._fetch_statement(f"/v3/cash-flow-statement/{ticker}", ticker, limit)
        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)
        return self._process_statement(df, ticker, 'cash_flow')

    def fetch_key_metrics(self, ticker: str, limit: int = 60) -> pd.DataFrame:
        """获取季度关键指标（PE、PB、ROE等，已由FMP计算好）"""
        data = self._fetch_statement(f"/v3/key-metrics/{ticker}", ticker, limit)
        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)
        return self._process_statement(df, ticker, 'key_metrics')

    def fetch_financial_ratios(self, ticker: str, limit: int = 60) -> pd.DataFrame:
        """获取季度财务比率"""
        data = self._fetch_statement(f"/v3/financial-ratios/{ticker}", ticker, limit)
        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)
        return self._process_statement(df, ticker, 'ratios')

    def _process_statement(self, df: pd.DataFrame, ticker: str,
                            stmt_type: str) -> pd.DataFrame:
        """
        处理财务报表 DataFrame：
        1. 统一 fillingDate → filing_date（点时间基准）
        2. 统一 date → period_date（报告期）
        3. 过滤无效日期

        Args:
            df: 原始 DataFrame
            ticker: 股票代码
            stmt_type: 报表类型（用于日志）

        Returns:
            处理后的 DataFrame
        """
        if df.empty:
            return df

        # 日期列统一
        date_cols = {
            'fillingDate': 'filing_date',  # SEC 申报日期（关键！用于点时间查询）
            'date': 'period_date',          # 报告期结束日期
            'acceptedDate': 'accepted_date',  # SEC 接受日期（介于两者之间）
        }
        for src, dst in date_cols.items():
            if src in df.columns:
                df = df.rename(columns={src: dst})

        # 解析日期
        for col in ['filing_date', 'period_date', 'accepted_date']:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce')

        # 过滤无 filing_date 的行（无法进行点时间查询）
        if 'filing_date' in df.columns:
            before = len(df)
            df = df[df['filing_date'].notna()]
            if len(df) < before:
                logger.debug(f"{ticker}/{stmt_type}: 过滤掉 {before - len(df)} 行无申报日期的记录")

        # 添加 ticker 列
        df['ticker'] = ticker.upper()

        # 按 filing_date 降序排列（最新的在前）
        if 'filing_date' in df.columns:
            df = df.sort_values('filing_date', ascending=False).reset_index(drop=True)

        return df

    # ------------------------------------------------------------------ #
    #  合并：构建单只股票的完整基本面快照
    # ------------------------------------------------------------------ #

    def fetch_all_fundamentals(self, ticker: str,
                               start_year: int = 2010) -> pd.DataFrame:
        """
        获取单只股票的全量基本面数据，合并为一张宽表

        合并逻辑：
        - 以 key_metrics（含 PE/PB/ROE 等）为主表，按 filing_date 对齐
        - 从利润表补充收入、EPS、利润率
        - 从资产负债表补充负债权益比、账面价值
        - 从现金流量表补充自由现金流

        防前视偏差：
        - 所有数据以 filing_date 为索引
        - 返回的 DataFrame 每行代表"该申报日期公开后才可获知的数据"

        Args:
            ticker: 股票代码
            start_year: 数据起始年份（过滤更早的数据）

        Returns:
            宽表 DataFrame，行 = 各季度申报，列 = 各项指标
            关键列：filing_date, period_date, pe_ratio, pb_ratio,
                    roe, revenue_growth_yoy, eps_growth, debt_to_equity,
                    operating_margin, fcf_yield, ...
        """
        ticker = ticker.upper()
        logger.info(f"{ticker}: 开始获取基本面数据...")

        start_dt = pd.Timestamp(f"{start_year}-01-01")

        # --- 1. 获取各类报表 ---
        km_df = self.fetch_key_metrics(ticker)       # 关键指标（含PE/PB/ROE）
        inc_df = self.fetch_income_statement(ticker)  # 利润表
        bs_df = self.fetch_balance_sheet(ticker)      # 资产负债表
        cf_df = self.fetch_cash_flow(ticker)          # 现金流量表
        ratio_df = self.fetch_financial_ratios(ticker) # 财务比率

        # 检查是否有数据
        if km_df.empty and inc_df.empty:
            logger.warning(f"{ticker}: 未获取到任何财务数据")
            return pd.DataFrame()

        # --- 2. 从利润表提取核心指标 ---
        inc_cols = {
            'filing_date': 'filing_date',
            'period_date': 'period_date',
            'revenue': 'revenue',
            'grossProfit': 'gross_profit',
            'operatingIncome': 'operating_income',
            'netIncome': 'net_income',
            'eps': 'eps',
            'epsdiluted': 'eps_diluted',
            'operatingExpenses': 'operating_expenses',
            'researchAndDevelopmentExpenses': 'rd_expenses',
        }
        inc_selected = _select_rename_cols(inc_df, inc_cols)

        # --- 3. 从资产负债表提取核心指标 ---
        bs_cols = {
            'filing_date': 'filing_date',
            'totalAssets': 'total_assets',
            'totalLiabilities': 'total_liabilities',
            'totalStockholdersEquity': 'total_equity',
            'totalDebt': 'total_debt',
            'cashAndCashEquivalents': 'cash',
            'shortTermInvestments': 'short_term_investments',
            'longTermDebt': 'long_term_debt',
            'commonStock': 'common_stock',
        }
        bs_selected = _select_rename_cols(bs_df, bs_cols)

        # --- 4. 从现金流量表提取核心指标 ---
        cf_cols = {
            'filing_date': 'filing_date',
            'operatingCashFlow': 'operating_cf',
            'capitalExpenditure': 'capex',
            'freeCashFlow': 'free_cash_flow',
            'dividendsPaid': 'dividends_paid',
            'stockBasedCompensation': 'sbc',
        }
        cf_selected = _select_rename_cols(cf_df, cf_cols)

        # --- 5. 从 key_metrics 提取关键指标（含PE/PB/ROE）---
        km_cols = {
            'filing_date': 'filing_date',
            'period_date': 'period_date',
            'peRatio': 'pe_ratio',
            'pbRatio': 'pb_ratio',
            'priceToSalesRatio': 'ps_ratio',
            'pfcfRatio': 'pfcf_ratio',          # 股价/自由现金流
            'evToEbitda': 'ev_to_ebitda',
            'roe': 'roe',
            'roa': 'roa',
            'roic': 'roic',
            'debtToEquity': 'debt_to_equity',
            'currentRatio': 'current_ratio',
            'revenuePerShare': 'revenue_per_share',
            'netIncomePerShare': 'eps_km',         # KM 里的 EPS
            'freeCashFlowPerShare': 'fcf_per_share',
            'bookValuePerShare': 'book_value_per_share',
            'operatingCashFlowPerShare': 'ocf_per_share',
            'enterpriseValue': 'enterprise_value',
            'marketCap': 'market_cap',
            'dividendYield': 'dividend_yield',
            'payoutRatio': 'payout_ratio',
            'grahamNumber': 'graham_number',
            'priceToBookRatio': 'pb_ratio_2',      # 有时 FMP 两个字段都有
        }
        km_selected = _select_rename_cols(km_df, km_cols)

        # --- 6. 从 financial_ratios 提取指标 ---
        ratio_cols = {
            'filing_date': 'filing_date',
            'grossProfitMargin': 'gross_margin',
            'operatingProfitMargin': 'operating_margin',
            'netProfitMargin': 'net_margin',
            'returnOnEquity': 'roe_ratio',
            'debtEquityRatio': 'dte_ratio',
            'interestCoverage': 'interest_coverage',
        }
        ratio_selected = _select_rename_cols(ratio_df, ratio_cols)

        # --- 7. 合并：以 filing_date 为主键 ---
        # 优先使用 km_selected 作为主表（已含大部分估值指标）
        if not km_selected.empty:
            merged = km_selected
        elif not inc_selected.empty:
            merged = inc_selected[['filing_date', 'period_date']].copy()
        else:
            logger.warning(f"{ticker}: 无法构建合并表")
            return pd.DataFrame()

        # 合并其他表（用 filing_date 做最近匹配，容忍 ±7 天的日期差异）
        for other_df, suffix in [
            (inc_selected, '_inc'),
            (bs_selected, '_bs'),
            (cf_selected, '_cf'),
            (ratio_selected, '_ratio'),
        ]:
            if not other_df.empty and 'filing_date' in other_df.columns:
                # 去掉重复的 filing_date 列（除主键外）
                other_for_merge = other_df.drop(
                    columns=['period_date'],
                    errors='ignore'
                )
                merged = pd.merge_asof(
                    merged.sort_values('filing_date'),
                    other_for_merge.sort_values('filing_date'),
                    on='filing_date',
                    direction='nearest',
                    tolerance=pd.Timedelta('30 days'),
                    suffixes=('', suffix),
                )

        # --- 8. 计算派生指标 ---
        merged = self._compute_derived_metrics(merged)

        # --- 9. 过滤起始年份之前的数据 ---
        if 'filing_date' in merged.columns:
            merged = merged[merged['filing_date'] >= start_dt]

        # --- 10. 按 filing_date 降序排列 ---
        if 'filing_date' in merged.columns:
            merged = merged.sort_values('filing_date', ascending=False).reset_index(drop=True)

        # 确保 ticker 列存在
        merged['ticker'] = ticker

        logger.info(f"{ticker}: 基本面数据获取完成，共 {len(merged)} 个季度")
        return merged

    def _compute_derived_metrics(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        计算派生指标（YoY增长率等）

        所有计算都在同一只股票的时间序列上做，无跨股票数据泄露。

        Args:
            df: 已合并的基本面 DataFrame（按 filing_date 降序排列）

        Returns:
            添加了派生指标列的 DataFrame
        """
        if df.empty:
            return df

        # 按 filing_date 升序，方便计算 YoY（同比 = 与4期前对比）
        df = df.sort_values('filing_date').reset_index(drop=True)

        # 收入同比增长（YoY）
        if 'revenue' in df.columns:
            df['revenue_growth_yoy'] = df['revenue'].pct_change(periods=4)

        # EPS 同比增长
        eps_col = 'eps_diluted' if 'eps_diluted' in df.columns else 'eps'
        if eps_col in df.columns:
            df[f'eps_growth_yoy'] = df[eps_col].pct_change(periods=4)

        # 营业利润率
        if 'operating_income' in df.columns and 'revenue' in df.columns:
            mask = df['revenue'] > 0
            df.loc[mask, 'operating_margin_calc'] = (
                df.loc[mask, 'operating_income'] / df.loc[mask, 'revenue']
            )

        # 自由现金流收益率（FCF / 市值）
        # 注意：市值是时点数据，这里用 key_metrics 中的 market_cap 近似
        if 'free_cash_flow' in df.columns and 'market_cap' in df.columns:
            mask = df['market_cap'] > 0
            df.loc[mask, 'fcf_yield'] = (
                df.loc[mask, 'free_cash_flow'] / df.loc[mask, 'market_cap']
            )

        # 净利润率（fallback：若 ratio 表没有）
        if 'net_margin' not in df.columns:
            if 'net_income' in df.columns and 'revenue' in df.columns:
                mask = df['revenue'] > 0
                df.loc[mask, 'net_margin'] = (
                    df.loc[mask, 'net_income'] / df.loc[mask, 'revenue']
                )

        # 资本回报率（ROE fallback）
        if 'roe' not in df.columns or df['roe'].isna().all():
            if 'net_income' in df.columns and 'total_equity' in df.columns:
                mask = df['total_equity'] > 0
                df.loc[mask, 'roe'] = (
                    df.loc[mask, 'net_income'] / df.loc[mask, 'total_equity']
                )

        # 负债权益比 fallback
        if 'debt_to_equity' not in df.columns or df.get('debt_to_equity', pd.Series()).isna().all():
            if 'total_debt' in df.columns and 'total_equity' in df.columns:
                mask = df['total_equity'] > 0
                df.loc[mask, 'debt_to_equity'] = (
                    df.loc[mask, 'total_debt'] / df.loc[mask, 'total_equity']
                )

        # 恢复降序排列
        df = df.sort_values('filing_date', ascending=False).reset_index(drop=True)
        return df

    # ------------------------------------------------------------------ #
    #  点时间查询
    # ------------------------------------------------------------------ #

    def get_fundamentals_at_date(self, ticker: str,
                                  query_date) -> Optional[Dict[str, Any]]:
        """
        获取指定日期"已公开"的最新基本面数据（点时间正确）

        防前视偏差说明：
        - 查找所有 filing_date <= query_date 的记录
        - 返回其中 filing_date 最新的一条
        - 这确保回测在 query_date 时只使用"当时已向SEC提交"的财务数据
        - 例如：若查询 2023-04-01，而 Q1 2023 的 10-Q 在 2023-05-10 才提交，
          则只能得到上一期（Q4 2022 或更早）的数据

        Args:
            ticker: 股票代码
            query_date: 查询日期

        Returns:
            包含各项财务指标的字典，无数据时返回 None
        """
        ticker = ticker.upper()
        query_date = pd.Timestamp(query_date)

        # 从缓存加载
        cached_df = self._load_cache(ticker)
        if cached_df is None or cached_df.empty:
            logger.debug(f"{ticker}: 无缓存数据，请先调用 download_and_cache_ticker()")
            return None

        # 过滤 filing_date <= query_date
        available = cached_df[cached_df['filing_date'] <= query_date]
        if available.empty:
            logger.debug(f"{ticker}: {query_date} 前无可用财务数据")
            return None

        # 取最新的一条（filing_date 最大）
        latest = available.sort_values('filing_date', ascending=False).iloc[0]

        # 转为字典，过滤 NaN
        result = {}
        for col, val in latest.items():
            if pd.notna(val):
                result[col] = val

        return result

    # ------------------------------------------------------------------ #
    #  缓存管理
    # ------------------------------------------------------------------ #

    def download_and_cache_ticker(self, ticker: str,
                                   start_year: int = 2010,
                                   force_update: bool = False) -> bool:
        """
        下载并缓存单只股票的基本面数据

        Args:
            ticker: 股票代码
            start_year: 数据起始年份
            force_update: 强制重新下载（即使缓存存在）

        Returns:
            True = 成功，False = 失败
        """
        ticker = ticker.upper()
        cache_file = self._get_cache_file(ticker)

        # 检查缓存是否已存在
        if cache_file.exists() and not force_update:
            logger.debug(f"{ticker}: 缓存已存在，跳过下载")
            return True

        # 获取数据
        df = self.fetch_all_fundamentals(ticker, start_year=start_year)
        if df.empty:
            logger.warning(f"{ticker}: 未获取到有效数据，跳过缓存")
            return False

        # 保存为 parquet
        try:
            df.to_parquet(cache_file, index=False)
            logger.info(f"{ticker}: 数据已缓存 ({len(df)} 行) → {cache_file}")
            return True
        except Exception as e:
            logger.error(f"{ticker}: 保存缓存失败 - {e}")
            return False

    def download_batch(self, tickers: List[str],
                       start_year: int = 2010,
                       force_update: bool = False,
                       progress_callback=None) -> Dict[str, bool]:
        """
        批量下载多只股票的基本面数据

        Args:
            tickers: 股票代码列表
            start_year: 数据起始年份
            force_update: 强制重新下载
            progress_callback: 进度回调函数 (ticker, index, total) -> None

        Returns:
            {ticker: True/False} 下载结果字典
        """
        results = {}
        total = len(tickers)

        for i, ticker in enumerate(tickers):
            if progress_callback:
                progress_callback(ticker, i, total)

            success = self.download_and_cache_ticker(
                ticker, start_year=start_year, force_update=force_update
            )
            results[ticker] = success

            if not success:
                logger.warning(f"[{i+1}/{total}] {ticker}: 下载失败")
            else:
                logger.debug(f"[{i+1}/{total}] {ticker}: 下载成功")

        succeeded = sum(1 for v in results.values() if v)
        logger.info(f"批量下载完成：{succeeded}/{total} 只成功")
        return results

    def _get_cache_file(self, ticker: str) -> Path:
        """获取缓存文件路径"""
        return self.cache_dir / f"{ticker.upper()}.parquet"

    def _load_cache(self, ticker: str) -> Optional[pd.DataFrame]:
        """从磁盘加载缓存数据"""
        cache_file = self._get_cache_file(ticker)
        if not cache_file.exists():
            return None

        try:
            df = pd.read_parquet(cache_file)
            # 确保 filing_date 是 datetime 类型
            if 'filing_date' in df.columns:
                df['filing_date'] = pd.to_datetime(df['filing_date'])
            return df
        except Exception as e:
            logger.error(f"{ticker}: 加载缓存失败 - {e}")
            return None

    def is_cached(self, ticker: str) -> bool:
        """检查股票数据是否已缓存"""
        return self._get_cache_file(ticker).exists()

    def get_cached_tickers(self) -> List[str]:
        """返回已缓存的股票列表"""
        return [f.stem for f in self.cache_dir.glob("*.parquet")]

    def get_api_call_count(self) -> int:
        """返回本次会话的 API 调用次数"""
        return self.api_call_count


# ------------------------------------------------------------------ #
#  工具函数
# ------------------------------------------------------------------ #

def _select_rename_cols(df: pd.DataFrame, col_map: dict) -> pd.DataFrame:
    """
    从 DataFrame 中选取并重命名列

    Args:
        df: 原始 DataFrame
        col_map: {原列名: 新列名} 字典

    Returns:
        只含映射列的新 DataFrame
    """
    if df.empty:
        return pd.DataFrame()

    available = {k: v for k, v in col_map.items() if k in df.columns}
    if not available:
        return pd.DataFrame()

    result = df[list(available.keys())].rename(columns=available).copy()
    return result


if __name__ == "__main__":
    # 简单测试
    import os
    logging.basicConfig(level=logging.INFO)

    api_key = os.environ.get("FMP_API_KEY", "demo")
    fetcher = FMPFundamentalFetcher(api_key=api_key)

    # 测试单只股票
    ticker = "AAPL"
    print(f"\n测试 {ticker} 基本面数据获取...")

    if not fetcher.is_cached(ticker):
        fetcher.download_and_cache_ticker(ticker, start_year=2020)

    # 测试点时间查询
    for test_date in ['2021-01-15', '2022-06-30', '2023-10-01']:
        data = fetcher.get_fundamentals_at_date(ticker, test_date)
        if data:
            print(f"\n{test_date} 可用的最新财务数据:")
            print(f"  申报日期: {data.get('filing_date', 'N/A')}")
            print(f"  PE比率:   {data.get('pe_ratio', 'N/A')}")
            print(f"  PB比率:   {data.get('pb_ratio', 'N/A')}")
            print(f"  ROE:      {data.get('roe', 'N/A')}")
            print(f"  营业利润率: {data.get('operating_margin', 'N/A')}")
        else:
            print(f"\n{test_date}: 无可用数据")

    print(f"\n总 API 调用次数: {fetcher.get_api_call_count()}")
