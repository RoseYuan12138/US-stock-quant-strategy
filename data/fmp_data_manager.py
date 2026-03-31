"""
FMP 数据管理器

统一管理标普500成分股和基本面数据的下载、缓存和查询。
作为回测系统的数据层接口，对上层策略屏蔽 API 细节。

主要功能：
1. get_universe(date)       → 获取指定日期的标普100成分股列表（防前视偏差）
2. get_fundamentals(ticker, date) → 获取指定日期可用的最新财务数据（防前视偏差）
3. run_full_download(...)   → 一次性下载所有数据并缓存到本地

防前视偏差说明：
- get_universe() 使用标普500历史变动记录，只返回在查询日期已加入指数的股票
- get_fundamentals() 使用 SEC 申报日期（fillingDate），确保只返回
  在查询日期前已公开提交的财务数据
- 这两个机制共同防止回测中意外使用"未来"信息
"""

import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

import pandas as pd

from data.fmp_constituent_fetcher import FMPConstituentFetcher
from data.fmp_fundamental_fetcher import FMPFundamentalFetcher

logger = logging.getLogger(__name__)

# 清单文件名
MANIFEST_FILENAME = "fmp_download_manifest.json"


class FMPDataManager:
    """
    FMP 数据管理器

    统一协调成分股数据和基本面数据的获取与查询。
    所有查询方法均保证点时间正确性（无前视偏差）。

    使用方式：
        manager = FMPDataManager()  # 从环境变量读取 API Key
        # 或
        manager = FMPDataManager(api_key="your_key")

        # 首次使用需下载数据
        manager.run_full_download(start_year=2010)

        # 回测中使用
        tickers = manager.get_universe("2022-03-15")     # 该日期的标普100
        fund = manager.get_fundamentals("AAPL", "2022-03-15")  # 该日期可用的财务数据
    """

    def __init__(self,
                 api_key: Optional[str] = None,
                 cache_base_dir: str = "./data/cache",
                 calls_per_minute: int = 300):
        """
        初始化数据管理器

        Args:
            api_key: FMP API Key。若为 None，从环境变量 FMP_API_KEY 读取
            cache_base_dir: 本地缓存根目录
            calls_per_minute: API 调用频率限制（付费账户 300/min，免费 5/min）
        """
        # 从环境变量读取 API Key
        self.api_key = api_key or os.environ.get("FMP_API_KEY", "")
        if not self.api_key:
            logger.warning("FMP_API_KEY 未设置。请设置环境变量或在初始化时传入 api_key 参数")

        self.cache_base_dir = Path(cache_base_dir)

        # 初始化子模块
        self.constituent_fetcher = FMPConstituentFetcher(
            api_key=self.api_key,
            cache_dir=str(self.cache_base_dir / "constituents"),
        )

        self.fundamental_fetcher = FMPFundamentalFetcher(
            api_key=self.api_key,
            cache_dir=str(self.cache_base_dir / "fundamentals_fmp"),
            calls_per_minute=calls_per_minute,
        )

        # 清单文件路径
        self.manifest_file = self.cache_base_dir / MANIFEST_FILENAME

    # ------------------------------------------------------------------ #
    #  核心查询接口（供回测系统调用）
    # ------------------------------------------------------------------ #

    def get_universe(self, date, size: int = 100) -> List[str]:
        """
        获取指定日期的股票池（标普100近似列表）

        防前视偏差说明：
        - 利用标普500历史成分股变动记录（以 dateAdded 为准）
        - 只返回在 date 当天"已加入且未被移除"的股票
        - 不会包含任何在 date 之后才加入指数的股票

        Args:
            date: 查询日期（str 如 '2022-03-15'，或 datetime/Timestamp）
            size: 返回股票数量（默认 100，对应标普100）

        Returns:
            股票代码列表（按字母排序）

        Raises:
            RuntimeError: 成分股数据未下载
        """
        if not self.constituent_fetcher.is_cache_valid():
            raise RuntimeError(
                "成分股缓存不存在，请先调用 run_full_download() 或 "
                "constituent_fetcher.download_and_cache()"
            )

        if size == 100:
            return self.constituent_fetcher.get_sp100_at_date(date)
        else:
            constituents = self.constituent_fetcher.get_constituents_at_date(date)
            return constituents[:size]

    def get_fundamentals(self, ticker: str, date) -> Optional[Dict[str, Any]]:
        """
        获取指定日期"已公开"的最新基本面数据（点时间正确）

        防前视偏差说明：
        - 查找该股票所有 filing_date（SEC申报日期）<= date 的财务数据
        - 返回其中最新（filing_date 最大）的一条
        - 严格使用 filing_date 而非 period_date（报告期结束日）
        - 原因：季度报告在报告期结束后数周至数月才会向SEC提交，
          使用报告期结束日会导致"超前知道"尚未公布的财务数据

        例如：
            若某公司 Q1 2023（期末 2023-03-31）在 2023-05-08 才向SEC提交，
            则 get_fundamentals("AAPL", "2023-04-15") 将返回 Q4 2022 的数据，
            而非 Q1 2023 的数据——因为 Q1 2023 在 2023-04-15 尚未公开。

        Args:
            ticker: 股票代码（如 'AAPL'）
            date: 查询日期

        Returns:
            包含财务指标的字典，关键字段：
            - filing_date: 实际申报日期
            - period_date: 对应报告期
            - pe_ratio, pb_ratio: 估值指标
            - roe, roa, roic: 盈利能力
            - revenue_growth_yoy, eps_growth_yoy: 成长性
            - debt_to_equity: 财务杠杆
            - operating_margin, net_margin: 利润率
            - fcf_yield: 自由现金流收益率
            未找到数据时返回 None
        """
        return self.fundamental_fetcher.get_fundamentals_at_date(ticker, date)

    def get_fundamentals_batch(self, tickers: List[str],
                                date) -> Dict[str, Optional[Dict]]:
        """
        批量获取多只股票在指定日期的基本面数据

        Args:
            tickers: 股票代码列表
            date: 查询日期

        Returns:
            {ticker: fundamentals_dict or None}
        """
        results = {}
        for ticker in tickers:
            results[ticker] = self.get_fundamentals(ticker, date)
        return results

    def is_data_available(self, ticker: str) -> bool:
        """检查股票的基本面数据是否已下载并缓存"""
        return self.fundamental_fetcher.is_cached(ticker)

    # ------------------------------------------------------------------ #
    #  全量数据下载
    # ------------------------------------------------------------------ #

    def run_full_download(self,
                          api_key: Optional[str] = None,
                          start_year: int = 2010,
                          force_update: bool = False,
                          progress_callback=None) -> Dict:
        """
        执行全量数据下载：成分股 + 所有标普100股票的基本面数据

        下载顺序：
        1. 下载标普500历史成分股变动记录并构建点时间索引
        2. 获取当前标普100股票列表
        3. 对每只股票下载季度财务数据

        Args:
            api_key: FMP API Key（可覆盖初始化时的设置）
            start_year: 数据起始年份（2010 ≈ 15 年历史）
            force_update: 强制重新下载已有缓存的数据
            progress_callback: 进度回调 (phase, current, total, message) -> None

        Returns:
            下载结果摘要字典

        API 调用估算（标普100 × 5个端点）：
        - 成分股：2 次
        - 每只股票：5 次（income + balance_sheet + cash_flow + key_metrics + ratios）
        - 总计：~502 次（约 2 分钟，付费账户）
        """
        if api_key:
            self.api_key = api_key
            self.constituent_fetcher.api_key = api_key
            self.fundamental_fetcher.api_key = api_key

        if not self.api_key:
            raise ValueError("FMP API Key 未提供。请传入 api_key 参数或设置 FMP_API_KEY 环境变量")

        summary = {
            'start_time': datetime.now().isoformat(),
            'start_year': start_year,
            'constituent_success': False,
            'fundamental_results': {},
            'total_tickers': 0,
            'success_count': 0,
            'fail_count': 0,
        }

        # ---- Phase 1: 成分股 ----
        logger.info("=" * 60)
        logger.info("Phase 1: 下载标普500历史成分股数据")
        logger.info("=" * 60)

        if progress_callback:
            progress_callback('constituents', 0, 1, "正在下载标普500历史成分股...")

        if force_update or not self.constituent_fetcher.is_cache_valid():
            success = self.constituent_fetcher.download_and_cache(start_year=start_year)
            summary['constituent_success'] = success
            if not success:
                logger.error("成分股下载失败！基本面下载仍将继续（使用预定义的标普100列表）")
        else:
            logger.info("成分股缓存已存在，跳过（使用 force_update=True 强制重新下载）")
            summary['constituent_success'] = True

        if progress_callback:
            progress_callback('constituents', 1, 1, "成分股下载完成")

        # ---- Phase 2: 确定需要下载的股票列表 ----
        logger.info("\n" + "=" * 60)
        logger.info("Phase 2: 确定标普100股票列表")
        logger.info("=" * 60)

        tickers_to_download = self._get_download_tickers()
        summary['total_tickers'] = len(tickers_to_download)
        logger.info(f"需要下载基本面数据的股票：{len(tickers_to_download)} 只")

        # ---- Phase 3: 基本面数据 ----
        logger.info("\n" + "=" * 60)
        logger.info(f"Phase 3: 下载 {len(tickers_to_download)} 只股票的基本面数据")
        logger.info("预计 API 调用次数: ~{} 次".format(len(tickers_to_download) * 5))
        logger.info("=" * 60)

        def _fundamental_progress(ticker, index, total):
            if progress_callback:
                progress_callback(
                    'fundamentals', index, total,
                    f"[{index+1}/{total}] 正在下载 {ticker} 基本面数据..."
                )

        fund_results = self.fundamental_fetcher.download_batch(
            tickers=tickers_to_download,
            start_year=start_year,
            force_update=force_update,
            progress_callback=_fundamental_progress,
        )

        summary['fundamental_results'] = fund_results
        summary['success_count'] = sum(1 for v in fund_results.values() if v)
        summary['fail_count'] = sum(1 for v in fund_results.values() if not v)
        summary['failed_tickers'] = [t for t, v in fund_results.items() if not v]
        summary['end_time'] = datetime.now().isoformat()
        summary['api_calls_used'] = self.fundamental_fetcher.get_api_call_count()

        # ---- 保存清单 ----
        self._save_manifest(summary)

        # ---- 打印摘要 ----
        logger.info("\n" + "=" * 60)
        logger.info("下载完成！摘要：")
        logger.info(f"  成分股:     {'✓' if summary['constituent_success'] else '✗'}")
        logger.info(f"  基本面成功: {summary['success_count']} / {summary['total_tickers']}")
        logger.info(f"  API调用数:  {summary['api_calls_used']}")
        if summary['failed_tickers']:
            logger.warning(f"  失败股票:   {summary['failed_tickers'][:10]}...")
        logger.info("=" * 60)

        return summary

    def _get_download_tickers(self) -> List[str]:
        """
        获取需要下载基本面数据的股票列表

        优先从缓存的成分股中取当前标普100，
        若成分股数据不可用则回退到预定义列表。
        """
        if self.constituent_fetcher.is_cache_valid():
            # 使用当前日期获取标普100
            today = datetime.now().strftime('%Y-%m-%d')
            sp100 = self.constituent_fetcher.get_sp100_at_date(today)
            if sp100:
                logger.info(f"从成分股缓存获取到 {len(sp100)} 只标普100股票")
                return sp100

        # 回退到预定义列表
        logger.warning("使用预定义的标普100列表（成分股缓存不可用）")
        return FMPConstituentFetcher.SP100_APPROXIMATE.copy()

    # ------------------------------------------------------------------ #
    #  缓存状态查询
    # ------------------------------------------------------------------ #

    def get_status(self) -> Dict:
        """
        返回当前缓存状态信息

        Returns:
            包含缓存统计的字典
        """
        status = {
            'constituent_cache': self.constituent_fetcher.get_cache_info(),
            'fundamental_cache': {
                'cached_tickers': len(self.fundamental_fetcher.get_cached_tickers()),
                'tickers': self.fundamental_fetcher.get_cached_tickers(),
            },
            'manifest': self._load_manifest(),
        }
        return status

    def _save_manifest(self, summary: dict):
        """保存下载清单文件"""
        try:
            # 去掉不可序列化的字段
            manifest = {k: v for k, v in summary.items()
                        if k != 'fundamental_results'}
            manifest['fundamental_results_summary'] = {
                'success': summary.get('success_count', 0),
                'fail': summary.get('fail_count', 0),
                'failed_tickers': summary.get('failed_tickers', []),
            }

            self.cache_base_dir.mkdir(parents=True, exist_ok=True)
            with open(self.manifest_file, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)

            logger.info(f"清单文件已保存: {self.manifest_file}")
        except Exception as e:
            logger.warning(f"保存清单文件失败: {e}")

    def _load_manifest(self) -> Optional[dict]:
        """加载清单文件"""
        if not self.manifest_file.exists():
            return None
        try:
            with open(self.manifest_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None


if __name__ == "__main__":
    import os
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # 从环境变量读取 API Key
    api_key = os.environ.get("FMP_API_KEY")
    if not api_key:
        print("请设置环境变量 FMP_API_KEY")
        exit(1)

    manager = FMPDataManager(api_key=api_key)

    # 显示当前状态
    status = manager.get_status()
    print("\n当前缓存状态:")
    print(f"  成分股缓存: {status['constituent_cache']}")
    print(f"  基本面缓存: {status['fundamental_cache']['cached_tickers']} 只股票")

    if status['manifest']:
        print(f"  上次下载: {status['manifest'].get('end_time', 'N/A')}")
        print(f"  成功/失败: {status['manifest'].get('success_count', 0)}/"
              f"{status['manifest'].get('fail_count', 0)}")

    # 测试查询（需要先下载数据）
    test_date = "2022-06-30"
    try:
        universe = manager.get_universe(test_date)
        print(f"\n{test_date} 标普100成分股 ({len(universe)} 只): {universe[:5]}...")

        if universe:
            ticker = universe[0]
            fund_data = manager.get_fundamentals(ticker, test_date)
            if fund_data:
                print(f"\n{ticker} @ {test_date}:")
                print(f"  申报日期:   {fund_data.get('filing_date', 'N/A')}")
                print(f"  PE 比率:    {fund_data.get('pe_ratio', 'N/A')}")
                print(f"  ROE:        {fund_data.get('roe', 'N/A')}")
            else:
                print(f"\n{ticker}: 无可用基本面数据（请先下载）")
    except RuntimeError as e:
        print(f"\n提示: {e}")
        print("运行 manager.run_full_download() 下载数据")
