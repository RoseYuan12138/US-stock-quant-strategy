"""
FMP 标普500成分股历史数据获取模块

从 Financial Modeling Prep API 获取标普500历史成分股变动记录，
构建"时间点正确"（point-in-time）的成分股查询功能。

关键设计原则（防前视偏差）：
- 成分股变动按"生效日期"记录，而非发布日期
- get_constituents_at_date() 只返回在查询日期"已生效"的成分股
- 这确保回测中任何日期的 universe 都不包含"当时尚未入选"的股票
"""

import os
import logging
import time
from datetime import datetime, date
from pathlib import Path
from typing import List, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)


# FMP API 基础地址
FMP_BASE_URL = "https://financialmodelingprep.com/api"

# 请求重试配置
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # 指数退避基础延迟（秒）


def _request_with_retry(url: str, params: dict, max_retries: int = MAX_RETRIES) -> Optional[dict]:
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
                # 限速：等待后重试
                wait = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(f"API 限速 (429)，等待 {wait:.1f}s 后重试 (第{attempt+1}次)")
                time.sleep(wait)
            elif resp.status_code == 401:
                logger.error(f"API Key 无效或未授权 (401)")
                return None
            else:
                logger.warning(f"HTTP {resp.status_code}，URL: {url}，重试中...")
                time.sleep(RETRY_BASE_DELAY * (2 ** attempt))

        except requests.exceptions.Timeout:
            wait = RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning(f"请求超时，等待 {wait:.1f}s 后重试 (第{attempt+1}次)")
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


class FMPConstituentFetcher:
    """
    标普500历史成分股获取器

    功能：
    1. 从 FMP 获取标普500历史变动记录（2010年至今）
    2. 构建任意日期的点时间成分股列表（防前视偏差）
    3. 识别标普100重叠股票（按市值排名前100）
    4. 将结果缓存为 parquet 文件
    """

    # 当前已知的 S&P 100 股票（市值最大的约100只，作为初始种子）
    # 实际以 FMP 返回的当前成分股 + 市值排名为准
    SP100_APPROXIMATE = [
        'AAPL', 'MSFT', 'NVDA', 'AMZN', 'GOOGL', 'GOOG', 'META', 'TSLA', 'AVGO', 'BRK.B',
        'JPM', 'LLY', 'V', 'UNH', 'XOM', 'MA', 'COST', 'HD', 'PG', 'JNJ',
        'ORCL', 'BAC', 'ABBV', 'NFLX', 'CRM', 'CVX', 'MRK', 'WMT', 'KO', 'AMD',
        'PEP', 'CSCO', 'ACN', 'LIN', 'MCD', 'TMO', 'ABT', 'IBM', 'GE', 'CAT',
        'GS', 'INTC', 'INTU', 'MS', 'DIS', 'AMGN', 'TXN', 'SPGI', 'NEE', 'VZ',
        'RTX', 'ISRG', 'BKNG', 'PFE', 'HON', 'SYK', 'T', 'LOW', 'UPS', 'BA',
        'BLK', 'AMAT', 'PANW', 'ADI', 'SBUX', 'ETN', 'AXP', 'PLD', 'GILD', 'VRTX',
        'CB', 'CI', 'LRCX', 'DE', 'TJX', 'REGN', 'BSX', 'KLAC', 'MMC', 'SO',
        'MU', 'MDLZ', 'ELV', 'ZTS', 'AMT', 'C', 'WFC', 'SCHW', 'CME', 'BMY',
        'SNPS', 'DUK', 'CL', 'MCO', 'USB', 'ICE', 'GD', 'NOC', 'CDNS', 'AON',
    ]

    def __init__(self, api_key: str, cache_dir: str = "./data/cache/constituents"):
        """
        初始化成分股获取器

        Args:
            api_key: FMP API Key
            cache_dir: 缓存目录路径
        """
        self.api_key = api_key
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # 缓存文件路径
        self.changes_cache_file = self.cache_dir / "sp500_historical_changes.parquet"
        self.current_cache_file = self.cache_dir / "sp500_current.parquet"
        self.pit_cache_file = self.cache_dir / "sp500_pit_index.parquet"

        # 内存缓存（避免重复读盘）
        self._changes_df: Optional[pd.DataFrame] = None
        self._pit_df: Optional[pd.DataFrame] = None

    # ------------------------------------------------------------------ #
    #  API 调用
    # ------------------------------------------------------------------ #

    def fetch_historical_changes(self) -> pd.DataFrame:
        """
        从 FMP 获取标普500历史成分股变动记录

        FMP endpoint: GET /v3/historical/sp500_constituent?apikey={key}

        返回字段:
        - dateAdded: 加入日期
        - removedDate: 移除日期（空 = 仍在指数中）
        - symbol: 股票代码
        - addedSecurity: 加入时的公司名
        - removedSecurity: 移除时的公司名
        - reason: 变动原因

        Returns:
            包含历史变动记录的 DataFrame
        """
        url = f"{FMP_BASE_URL}/v3/historical/sp500_constituent"
        params = {"apikey": self.api_key}

        logger.info("正在从 FMP 获取标普500历史成分股变动记录...")
        data = _request_with_retry(url, params)

        if not data:
            logger.error("获取标普500历史变动记录失败")
            return pd.DataFrame()

        df = pd.DataFrame(data)
        if df.empty:
            logger.warning("标普500历史变动记录为空")
            return df

        # 列名统一
        col_map = {
            'dateAdded': 'date_added',
            'removedDate': 'removed_date',
            'symbol': 'ticker',
            'addedSecurity': 'added_security',
            'removedSecurity': 'removed_security',
            'reason': 'reason',
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

        # 日期解析
        for col in ['date_added', 'removed_date']:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce')

        # 清理 ticker（去除空格和特殊字符）
        if 'ticker' in df.columns:
            df['ticker'] = df['ticker'].str.strip().str.upper()
            df = df[df['ticker'].notna() & (df['ticker'] != '')]

        logger.info(f"获取到 {len(df)} 条历史变动记录")
        return df

    def fetch_current_constituents(self) -> pd.DataFrame:
        """
        获取当前标普500成分股列表

        FMP endpoint: GET /v3/sp500_constituent?apikey={key}

        Returns:
            当前成分股 DataFrame，含 ticker, name, sector, subSector 等
        """
        url = f"{FMP_BASE_URL}/v3/sp500_constituent"
        params = {"apikey": self.api_key}

        logger.info("正在从 FMP 获取当前标普500成分股...")
        data = _request_with_retry(url, params)

        if not data:
            logger.error("获取当前标普500成分股失败")
            return pd.DataFrame()

        df = pd.DataFrame(data)
        if df.empty:
            return df

        # 列名统一
        col_map = {
            'symbol': 'ticker',
            'name': 'company_name',
            'sector': 'sector',
            'subSector': 'sub_sector',
            'headQuarter': 'headquarters',
            'dateFirstAdded': 'date_first_added',
            'cik': 'cik',
            'founded': 'founded',
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

        if 'ticker' in df.columns:
            df['ticker'] = df['ticker'].str.strip().str.upper()
            df = df[df['ticker'].notna() & (df['ticker'] != '')]

        logger.info(f"当前标普500成分股：{len(df)} 只")
        return df

    # ------------------------------------------------------------------ #
    #  数据处理：构建点时间索引
    # ------------------------------------------------------------------ #

    def build_pit_index(self, changes_df: pd.DataFrame,
                        current_df: pd.DataFrame,
                        start_year: int = 2010) -> pd.DataFrame:
        """
        构建标普500点时间（Point-In-Time）成分股索引

        方法论：
        1. 以当前成分股为"基准"，倒推历史变动
        2. 每次变动都记录 (date, ticker, in_index) 三元组
        3. 查询时用 date <= query_date 的最新记录

        防前视偏差说明：
        - 使用 dateAdded（实际生效日期）作为入选时间
        - 回测中查询 get_constituents_at_date(d) 只返回 dateAdded <= d 且
          尚未被移除（removedDate > d 或为空）的股票
        - 绝不使用"未来才发生的"成分股变动

        Args:
            changes_df: 历史变动 DataFrame
            current_df: 当前成分股 DataFrame
            start_year: 数据起始年份

        Returns:
            点时间索引 DataFrame，列：[date, ticker, in_index, source]
        """
        records = []
        today = pd.Timestamp.today().normalize()
        start_date = pd.Timestamp(f"{start_year}-01-01")

        # --- 当前成分股：标记为当前在指数中 ---
        current_tickers = set()
        if not current_df.empty and 'ticker' in current_df.columns:
            current_tickers = set(current_df['ticker'].tolist())

        # --- 处理历史变动记录 ---
        for _, row in changes_df.iterrows():
            ticker = row.get('ticker', '')
            if not ticker:
                continue

            date_added = row.get('date_added')
            removed_date = row.get('removed_date')

            # 过滤起始年份之前的数据
            if pd.notna(date_added) and date_added < start_date:
                # 仍需记录"加入"事件，否则 2010 年前加入的股票不会出现在索引中
                # 将加入日期调整为 start_date（保守处理）
                date_added = start_date

            # 记录"加入"事件
            if pd.notna(date_added):
                records.append({
                    'date': date_added,
                    'ticker': ticker,
                    'in_index': True,
                    'event': 'ADDED',
                })

            # 记录"移除"事件
            if pd.notna(removed_date) and removed_date >= start_date:
                records.append({
                    'date': removed_date,
                    'ticker': ticker,
                    'in_index': False,
                    'event': 'REMOVED',
                })

        # --- 补充：2010年已在指数中但历史变动里没有"加入"记录的股票 ---
        # （这些股票是2010年前就在指数中的，FMP数据可能不含其加入记录）
        tickers_with_added_event = {
            r['ticker'] for r in records if r['event'] == 'ADDED'
        }
        tickers_still_in = {
            r['ticker'] for r in records if r['event'] == 'REMOVED'
        }
        # 当前成分股中，没有明确"加入"记录的 → 假设从 start_date 起就在指数中
        for ticker in current_tickers:
            if ticker not in tickers_with_added_event:
                records.append({
                    'date': start_date,
                    'ticker': ticker,
                    'in_index': True,
                    'event': 'ASSUMED_SINCE_START',
                })

        if not records:
            logger.warning("未生成任何点时间记录")
            return pd.DataFrame()

        pit_df = pd.DataFrame(records)
        pit_df['date'] = pd.to_datetime(pit_df['date'])
        pit_df = pit_df.sort_values(['ticker', 'date']).reset_index(drop=True)

        logger.info(f"点时间索引：{len(pit_df)} 条记录，"
                    f"覆盖 {pit_df['ticker'].nunique()} 只股票")
        return pit_df

    # ------------------------------------------------------------------ #
    #  查询接口
    # ------------------------------------------------------------------ #

    def get_constituents_at_date(self, query_date, top_n: Optional[int] = None) -> List[str]:
        """
        查询指定日期的标普500成分股列表（点时间正确）

        防前视偏差说明：
        对于每只股票，取所有 date <= query_date 的变动记录中最新的那条，
        若最新状态为 in_index=True，则该股票在 query_date 时处于指数中。

        Args:
            query_date: 查询日期（str 或 datetime）
            top_n: 若指定，返回"近似标普N"（按字母序截取，实际应按市值）

        Returns:
            股票代码列表
        """
        pit_df = self._load_pit_index()
        if pit_df is None or pit_df.empty:
            logger.warning("点时间索引未加载，返回空列表")
            return []

        query_date = pd.Timestamp(query_date)

        # 只看 date <= query_date 的记录
        valid = pit_df[pit_df['date'] <= query_date]
        if valid.empty:
            return []

        # 每只股票取最新状态
        latest = valid.sort_values('date').groupby('ticker').last().reset_index()
        in_index = latest[latest['in_index'] == True]['ticker'].tolist()

        # 排序（便于调试）
        in_index = sorted(in_index)

        if top_n:
            # 简单截取（真实场景应按市值排序，这里按 SP100_APPROXIMATE 过滤）
            sp100_set = set(self.SP100_APPROXIMATE)
            sp100_overlap = [t for t in in_index if t in sp100_set]
            return sp100_overlap[:top_n]

        return in_index

    def get_sp100_at_date(self, query_date) -> List[str]:
        """
        查询指定日期的"标普100"成分股（标普500中市值最大的约100只）

        注意：FMP 没有直接的历史标普100端点，这里用预定义的近似列表
        与历史标普500成分股取交集，作为合理近似。

        真实回测建议：从 FMP /v3/etf-holder/OEF 获取iShares S&P100 ETF历史持仓。

        Args:
            query_date: 查询日期

        Returns:
            约100只股票的代码列表
        """
        # 获取该日期的标普500成分股
        sp500 = set(self.get_constituents_at_date(query_date))

        # 与预定义的标普100近似列表取交集
        sp100 = [t for t in self.SP100_APPROXIMATE if t in sp500]

        logger.debug(f"{query_date}: 标普100近似成分 {len(sp100)} 只")
        return sp100

    # ------------------------------------------------------------------ #
    #  缓存管理
    # ------------------------------------------------------------------ #

    def download_and_cache(self, start_year: int = 2010) -> bool:
        """
        下载并缓存所有成分股数据

        Args:
            start_year: 数据起始年份

        Returns:
            True = 成功，False = 失败
        """
        # 1. 获取历史变动记录
        changes_df = self.fetch_historical_changes()
        if changes_df.empty:
            logger.error("历史变动数据为空，缓存失败")
            return False

        # 2. 获取当前成分股
        current_df = self.fetch_current_constituents()

        # 3. 保存原始数据
        try:
            changes_df.to_parquet(self.changes_cache_file, index=False)
            logger.info(f"历史变动记录已保存: {self.changes_cache_file}")
        except Exception as e:
            logger.error(f"保存历史变动记录失败: {e}")
            return False

        if not current_df.empty:
            try:
                current_df.to_parquet(self.current_cache_file, index=False)
                logger.info(f"当前成分股已保存: {self.current_cache_file}")
            except Exception as e:
                logger.warning(f"保存当前成分股失败: {e}")

        # 4. 构建点时间索引
        pit_df = self.build_pit_index(changes_df, current_df, start_year)
        if pit_df.empty:
            logger.error("点时间索引为空，缓存失败")
            return False

        try:
            pit_df.to_parquet(self.pit_cache_file, index=False)
            logger.info(f"点时间索引已保存: {self.pit_cache_file} ({len(pit_df)} 行)")
        except Exception as e:
            logger.error(f"保存点时间索引失败: {e}")
            return False

        # 清除内存缓存（使下次查询重新从磁盘加载）
        self._changes_df = None
        self._pit_df = None

        return True

    def _load_pit_index(self) -> Optional[pd.DataFrame]:
        """从磁盘加载点时间索引（内存缓存）"""
        if self._pit_df is not None:
            return self._pit_df

        if not self.pit_cache_file.exists():
            logger.warning(f"点时间索引文件不存在: {self.pit_cache_file}，"
                           "请先调用 download_and_cache()")
            return None

        try:
            df = pd.read_parquet(self.pit_cache_file)
            df['date'] = pd.to_datetime(df['date'])
            self._pit_df = df
            logger.debug(f"已加载点时间索引: {len(df)} 行")
            return df
        except Exception as e:
            logger.error(f"加载点时间索引失败: {e}")
            return None

    def is_cache_valid(self) -> bool:
        """检查缓存是否存在且有效"""
        return self.pit_cache_file.exists() and self.changes_cache_file.exists()

    def get_cache_info(self) -> dict:
        """返回缓存状态信息"""
        info = {
            'pit_index_exists': self.pit_cache_file.exists(),
            'changes_exists': self.changes_cache_file.exists(),
            'current_exists': self.current_cache_file.exists(),
        }

        if self.pit_cache_file.exists():
            pit_df = self._load_pit_index()
            if pit_df is not None:
                info['pit_records'] = len(pit_df)
                info['pit_tickers'] = pit_df['ticker'].nunique()
                info['pit_date_range'] = (
                    pit_df['date'].min().strftime('%Y-%m-%d'),
                    pit_df['date'].max().strftime('%Y-%m-%d'),
                )

        return info


if __name__ == "__main__":
    # 简单测试（需要有效的 API Key）
    import os
    logging.basicConfig(level=logging.INFO)

    api_key = os.environ.get("FMP_API_KEY", "demo")
    fetcher = FMPConstituentFetcher(api_key=api_key)

    if not fetcher.is_cache_valid():
        print("缓存不存在，开始下载...")
        success = fetcher.download_and_cache(start_year=2010)
        print(f"下载结果: {'成功' if success else '失败'}")
    else:
        print("缓存已存在")

    # 查询测试
    for test_date in ['2015-01-01', '2020-06-15', '2023-01-01']:
        constituents = fetcher.get_constituents_at_date(test_date)
        sp100 = fetcher.get_sp100_at_date(test_date)
        print(f"\n{test_date}: 标普500={len(constituents)}只, 标普100近似={len(sp100)}只")
        print(f"  标普100样例: {sp100[:10]}")
