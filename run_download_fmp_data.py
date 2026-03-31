"""
FMP 数据下载 CLI 脚本

一键下载标普500历史成分股和标普100股票的基本面数据，
并缓存为本地 parquet 文件，供回测系统使用。

使用方式：
    # 基本用法（从环境变量读取 API Key）
    export FMP_API_KEY=your_api_key_here
    python run_download_fmp_data.py

    # 指定 API Key 和起始年份
    python run_download_fmp_data.py --api-key YOUR_KEY --start-year 2010

    # 强制重新下载（忽略已有缓存）
    python run_download_fmp_data.py --force-update

    # 仅下载成分股数据
    python run_download_fmp_data.py --only-constituents

    # 仅下载基本面数据（需成分股缓存已存在）
    python run_download_fmp_data.py --only-fundamentals

    # 查看当前缓存状态
    python run_download_fmp_data.py --status

注意：
    - FMP 付费账户限速 300 calls/min，免费账户限速 5 calls/min
    - 下载约100只股票的全量数据（2010-至今）约需 ~502 次 API 调用
    - 预计耗时：付费账户约 3-5 分钟，免费账户约 100 分钟
    - 数据存储在 ./data/cache/ 目录下
"""

import os
import sys
import json
import argparse
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

# 将项目根目录加入 sys.path，以便跨目录导入
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    print("提示：安装 tqdm 可获得进度条显示: pip install tqdm")

from data.fmp_data_manager import FMPDataManager
from data.fmp_constituent_fetcher import FMPConstituentFetcher

# 日志配置
logging.basicConfig(
    level=logging.WARNING,  # CLI 模式下只显示警告和错误，详情通过进度条展示
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  API 调用量和费用估算
# ------------------------------------------------------------------ #

def estimate_api_calls(num_tickers: int, start_year: int) -> dict:
    """
    估算本次下载需要的 API 调用次数和费用

    FMP 收费标准（以官网为准）：
    - 免费: 5 calls/min, 250 calls/day
    - Starter: $19/mo, 300 calls/min
    - Premium: $39/mo, 无限制

    Args:
        num_tickers: 需要下载的股票数量
        start_year: 数据起始年份

    Returns:
        估算结果字典
    """
    years = datetime.now().year - start_year + 1

    # 每只股票的 API 调用：
    # income-statement + balance-sheet + cash-flow + key-metrics + financial-ratios
    calls_per_ticker = 5
    constituent_calls = 2  # historical + current

    total_calls = constituent_calls + num_tickers * calls_per_ticker

    # 时间估算（付费账户 300 calls/min）
    paid_minutes = total_calls / 300
    free_minutes = total_calls / 5

    return {
        'num_tickers': num_tickers,
        'years_of_data': years,
        'calls_per_ticker': calls_per_ticker,
        'constituent_calls': constituent_calls,
        'total_api_calls': total_calls,
        'estimated_time_paid_min': round(paid_minutes, 1),
        'estimated_time_free_min': round(free_minutes, 1),
        'estimated_storage_mb': round(num_tickers * 0.1, 1),  # 约 100KB/股票
    }


# ------------------------------------------------------------------ #
#  进度条
# ------------------------------------------------------------------ #

class ProgressTracker:
    """多阶段进度追踪器"""

    def __init__(self, total_tickers: int, use_tqdm: bool = True):
        self.total_tickers = total_tickers
        self.use_tqdm = use_tqdm and HAS_TQDM
        self._pbar = None
        self._current_phase = None

    def update(self, phase: str, current: int, total: int, message: str = ""):
        """
        更新进度

        Args:
            phase: 阶段名称（'constituents' 或 'fundamentals'）
            current: 当前进度
            total: 总量
            message: 状态描述
        """
        if phase != self._current_phase:
            # 阶段切换，关闭旧的进度条
            if self._pbar is not None:
                self._pbar.close()
                self._pbar = None

            self._current_phase = phase

            if phase == 'constituents':
                print("\n[Phase 1/2] 下载标普500历史成分股数据...")
            elif phase == 'fundamentals':
                print(f"\n[Phase 2/2] 下载 {total} 只股票的基本面数据...")
                if self.use_tqdm:
                    self._pbar = tqdm(
                        total=total,
                        desc="基本面下载",
                        unit="只股票",
                        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]",
                    )

        if phase == 'fundamentals' and self._pbar is not None:
            # 更新进度条
            self._pbar.update(1)
            # 在进度条后面显示当前股票名称
            if message:
                ticker = message.split()[-2] if len(message.split()) >= 2 else ""
                self._pbar.set_postfix_str(ticker)
        else:
            # 无进度条时直接打印
            if message:
                print(f"  {message}")

    def close(self):
        if self._pbar is not None:
            self._pbar.close()
            self._pbar = None


# ------------------------------------------------------------------ #
#  子命令实现
# ------------------------------------------------------------------ #

def cmd_status(args):
    """显示当前缓存状态"""
    manager = FMPDataManager(
        api_key=args.api_key,
        cache_base_dir=args.cache_dir,
    )
    status = manager.get_status()

    print("\n" + "=" * 60)
    print("FMP 数据缓存状态")
    print("=" * 60)

    # 成分股状态
    c_info = status['constituent_cache']
    print(f"\n成分股数据:")
    print(f"  点时间索引:    {'✓ 已缓存' if c_info.get('pit_index_exists') else '✗ 未下载'}")
    print(f"  历史变动记录:  {'✓ 已缓存' if c_info.get('changes_exists') else '✗ 未下载'}")
    if c_info.get('pit_records'):
        print(f"  记录条数:      {c_info['pit_records']}")
        print(f"  覆盖股票数:    {c_info['pit_tickers']}")
        date_range = c_info.get('pit_date_range', ('N/A', 'N/A'))
        print(f"  日期范围:      {date_range[0]} ~ {date_range[1]}")

    # 基本面状态
    f_info = status['fundamental_cache']
    print(f"\n基本面数据:")
    print(f"  已缓存股票数:  {f_info['cached_tickers']}")
    if f_info['tickers']:
        sample = sorted(f_info['tickers'])[:10]
        print(f"  样例股票:      {', '.join(sample)}")
        if len(f_info['tickers']) > 10:
            print(f"                 ...等共 {len(f_info['tickers'])} 只")

    # 上次下载信息
    manifest = status.get('manifest')
    if manifest:
        print(f"\n上次下载记录:")
        print(f"  下载时间:    {manifest.get('end_time', 'N/A')[:19]}")
        print(f"  起始年份:    {manifest.get('start_year', 'N/A')}")
        frs = manifest.get('fundamental_results_summary', {})
        print(f"  成功/失败:   {frs.get('success', 0)} / {frs.get('fail', 0)}")
        if frs.get('failed_tickers'):
            print(f"  失败股票:    {frs['failed_tickers'][:5]}")
        print(f"  API调用次数: {manifest.get('api_calls_used', 'N/A')}")
    else:
        print("\n尚未执行过下载（无清单文件）")

    print("=" * 60)


def cmd_download(args):
    """执行全量数据下载"""

    # ---- 确认 API Key ----
    api_key = args.api_key or os.environ.get("FMP_API_KEY", "")
    if not api_key:
        print("\n错误：未提供 FMP API Key")
        print("  方式1: python run_download_fmp_data.py --api-key YOUR_KEY")
        print("  方式2: export FMP_API_KEY=YOUR_KEY")
        sys.exit(1)

    # ---- 预估 API 调用量 ----
    sp100_count = len(FMPConstituentFetcher.SP100_APPROXIMATE)
    estimate = estimate_api_calls(sp100_count, args.start_year)

    print("\n" + "=" * 60)
    print("FMP 数据下载计划")
    print("=" * 60)
    print(f"  数据范围:       {args.start_year} 年至今（约 {estimate['years_of_data']} 年）")
    print(f"  目标股票数:     ~{estimate['num_tickers']} 只（标普100）")
    print(f"  预计API调用:    ~{estimate['total_api_calls']} 次")
    print(f"  预计耗时（付费账户）: ~{estimate['estimated_time_paid_min']} 分钟")
    print(f"  预计耗时（免费账户）: ~{estimate['estimated_time_free_min']} 分钟")
    print(f"  预计磁盘占用:   ~{estimate['estimated_storage_mb']} MB")
    print(f"  缓存目录:       {args.cache_dir}")
    print(f"  强制重新下载:   {'是' if args.force_update else '否'}")
    print("=" * 60)

    if not args.yes:
        confirm = input("\n确认开始下载？[y/N] ").strip().lower()
        if confirm not in ('y', 'yes', '是'):
            print("已取消")
            sys.exit(0)

    # ---- 初始化管理器 ----
    # 根据用户账户类型设置限速
    calls_per_minute = args.calls_per_minute
    manager = FMPDataManager(
        api_key=api_key,
        cache_base_dir=args.cache_dir,
        calls_per_minute=calls_per_minute,
    )

    # ---- 进度追踪 ----
    tracker = ProgressTracker(
        total_tickers=sp100_count,
        use_tqdm=not args.no_progress,
    )

    print(f"\n开始下载... {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # ---- 执行下载 ----
    start_time = datetime.now()

    if args.only_constituents:
        # 仅下载成分股
        print("\n[仅下载成分股模式]")
        success = manager.constituent_fetcher.download_and_cache(
            start_year=args.start_year
        )
        summary = {'constituent_success': success, 'api_calls_used': 2}
    elif args.only_fundamentals:
        # 仅下载基本面（假设成分股已存在）
        print("\n[仅下载基本面模式]")
        tickers = manager._get_download_tickers()
        print(f"需下载 {len(tickers)} 只股票的基本面数据")

        def _progress(ticker, idx, total):
            tracker.update('fundamentals', idx, total,
                           f"[{idx+1}/{total}] 正在下载 {ticker} 基本面数据...")

        fund_results = manager.fundamental_fetcher.download_batch(
            tickers=tickers,
            start_year=args.start_year,
            force_update=args.force_update,
            progress_callback=_progress,
        )
        summary = {
            'constituent_success': True,
            'success_count': sum(1 for v in fund_results.values() if v),
            'fail_count': sum(1 for v in fund_results.values() if not v),
            'api_calls_used': manager.fundamental_fetcher.get_api_call_count(),
            'failed_tickers': [t for t, v in fund_results.items() if not v],
        }
    else:
        # 全量下载
        summary = manager.run_full_download(
            api_key=api_key,
            start_year=args.start_year,
            force_update=args.force_update,
            progress_callback=lambda phase, cur, tot, msg: tracker.update(phase, cur, tot, msg),
        )

    tracker.close()
    elapsed = (datetime.now() - start_time).total_seconds()

    # ---- 打印结果 ----
    print("\n" + "=" * 60)
    print(f"下载完成！耗时: {elapsed/60:.1f} 分钟")
    print("=" * 60)
    print(f"  成分股:         {'✓ 成功' if summary.get('constituent_success') else '✗ 失败'}")
    if 'success_count' in summary:
        print(f"  基本面成功:     {summary['success_count']} 只")
    if 'fail_count' in summary and summary['fail_count'] > 0:
        print(f"  基本面失败:     {summary['fail_count']} 只")
        if summary.get('failed_tickers'):
            print(f"  失败股票:       {summary['failed_tickers'][:10]}")
    print(f"  API调用次数:    {summary.get('api_calls_used', 'N/A')}")
    print(f"  清单文件:       {manager.manifest_file}")
    print("=" * 60)
    print("\n使用提示：")
    print("  from data.fmp_data_manager import FMPDataManager")
    print("  manager = FMPDataManager()")
    print("  tickers = manager.get_universe('2022-01-01')  # 获取标普100")
    print("  fund = manager.get_fundamentals('AAPL', '2022-01-01')  # 获取基本面")


def cmd_test_query(args):
    """测试数据查询（验证下载结果）"""
    api_key = args.api_key or os.environ.get("FMP_API_KEY", "")
    manager = FMPDataManager(api_key=api_key, cache_base_dir=args.cache_dir)

    test_dates = ['2015-01-02', '2018-06-15', '2020-03-20', '2022-09-30', '2024-01-02']

    print("\n" + "=" * 60)
    print("数据查询测试（验证点时间正确性）")
    print("=" * 60)

    for test_date in test_dates:
        print(f"\n测试日期: {test_date}")

        # 成分股查询
        try:
            universe = manager.get_universe(test_date)
            print(f"  标普100成分股: {len(universe)} 只")
            if universe:
                print(f"  样例: {universe[:5]}")

            # 基本面查询（取第一只股票）
            if universe:
                ticker = universe[0]
                fund = manager.get_fundamentals(ticker, test_date)
                if fund:
                    fd = fund.get('filing_date', 'N/A')
                    pd_date = fund.get('period_date', 'N/A')
                    print(f"  {ticker} 基本面（{test_date}）:")
                    print(f"    最新申报日期: {fd}")
                    print(f"    对应报告期:   {pd_date}")
                    print(f"    PE比率:       {fund.get('pe_ratio', 'N/A')}")
                    print(f"    ROE:          {fund.get('roe', 'N/A')}")

                    # 验证防前视偏差
                    if pd.notna(fd) and str(fd) != 'N/A':
                        filing_ts = pd.Timestamp(fd)
                        query_ts = pd.Timestamp(test_date)
                        if filing_ts <= query_ts:
                            print(f"    ✓ 点时间验证通过（申报日 {fd} <= 查询日 {test_date}）")
                        else:
                            print(f"    ✗ 点时间验证失败！申报日 {fd} > 查询日 {test_date}")
                else:
                    print(f"  {ticker}: 无可用基本面数据")
        except RuntimeError as e:
            print(f"  错误: {e}")
            print("  请先运行下载命令")
            break

    print("\n" + "=" * 60)


# ------------------------------------------------------------------ #
#  命令行参数解析
# ------------------------------------------------------------------ #

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="FMP 量化数据下载工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 首次下载所有数据
  python run_download_fmp_data.py --api-key YOUR_KEY --start-year 2010

  # 使用环境变量
  export FMP_API_KEY=YOUR_KEY
  python run_download_fmp_data.py

  # 查看缓存状态
  python run_download_fmp_data.py --status

  # 强制重新下载（忽略缓存）
  python run_download_fmp_data.py --force-update --yes

  # 免费账户（限速5 calls/min）
  python run_download_fmp_data.py --calls-per-minute 4

  # 测试数据查询
  python run_download_fmp_data.py --test-query
        """,
    )

    # 基本参数
    parser.add_argument(
        "--api-key", type=str, default=None,
        help="FMP API Key（也可通过环境变量 FMP_API_KEY 设置）",
    )
    parser.add_argument(
        "--start-year", type=int, default=2010,
        help="数据起始年份（默认 2010）",
    )
    parser.add_argument(
        "--cache-dir", type=str, default="./data/cache",
        help="本地缓存根目录（默认 ./data/cache）",
    )
    parser.add_argument(
        "--calls-per-minute", type=int, default=300,
        help="API 调用频率限制（付费 300，免费 5，默认 300）",
    )

    # 操作模式
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--status", action="store_true",
        help="查看当前缓存状态，不执行下载",
    )
    mode_group.add_argument(
        "--only-constituents", action="store_true",
        help="仅下载成分股数据",
    )
    mode_group.add_argument(
        "--only-fundamentals", action="store_true",
        help="仅下载基本面数据（需成分股缓存已存在）",
    )
    mode_group.add_argument(
        "--test-query", action="store_true",
        help="测试数据查询，验证点时间正确性",
    )

    # 其他选项
    parser.add_argument(
        "--force-update", action="store_true",
        help="强制重新下载（忽略已有缓存）",
    )
    parser.add_argument(
        "--yes", "-y", action="store_true",
        help="跳过确认提示，直接开始下载",
    )
    parser.add_argument(
        "--no-progress", action="store_true",
        help="不显示进度条（仅输出日志）",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="输出详细日志",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    # 调整日志级别
    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)
        logging.getLogger('data.fmp_constituent_fetcher').setLevel(logging.DEBUG)
        logging.getLogger('data.fmp_fundamental_fetcher').setLevel(logging.DEBUG)

    # 执行对应子命令
    if args.status:
        cmd_status(args)
    elif args.test_query:
        cmd_test_query(args)
    else:
        cmd_download(args)


if __name__ == "__main__":
    main()
