#!/usr/bin/env python3
"""
美股量化交易系统 - 回测运行脚本
执行完整的回测流程并生成报告
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from data.data_fetcher import DataFetcher
from strategy.strategies import SMACrossover, RSIStrategy, MACDStrategy, StrategyEnsemble
from backtest.backtester import BacktestEngine, MultiStrategyBacktest
from backtest.visualizer import BacktestVisualizer
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_single_ticker_backtest(ticker, strategies=None, output_dir='./reports'):
    """
    运行单只股票的多策略回测
    
    Args:
        ticker: 股票代码
        strategies: 策略列表
        output_dir: 输出目录
    
    Returns:
        dict: 回测结果
    """
    logger.info(f"开始回测 {ticker}...")
    
    if strategies is None:
        strategies = [
            SMACrossover(),
            RSIStrategy(),
            MACDStrategy()
        ]
    
    # 获取数据
    fetcher = DataFetcher()
    data = fetcher.fetch_historical_data(ticker, start_date='2024-01-01')
    
    if data is None or len(data) == 0:
        logger.error(f"{ticker}: 无法获取数据")
        return None
    
    logger.info(f"{ticker}: 获取 {len(data)} 行数据")
    
    # 多策略回测
    multi = MultiStrategyBacktest(initial_cash=10000, commission=10)
    results = multi.run(data, strategies)
    
    # 输出对比
    comparison = multi.compare()
    
    # 可视化
    visualizer = BacktestVisualizer(output_dir=output_dir)
    
    for strategy_name, result in results.items():
        # 绘制单策略结果
        plot_path = visualizer.plot_backtest_result(
            ticker, 
            result['result'], 
            result['report'],
            strategy_name
        )
        logger.info(f"图表已保存: {plot_path}")
        
        # 生成文本报告
        report_text = visualizer.generate_summary_report(
            f"{ticker} - {strategy_name}",
            result['report'],
            result['engine'].trades
        )
        
        # 保存文本报告
        report_file = Path(output_dir) / f"{ticker}_{strategy_name}_report.txt"
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report_text)
        
        logger.info(f"报告已保存: {report_file}")
    
    # 策略对比图表
    try:
        plot_path = visualizer.plot_strategy_comparison(comparison)
        logger.info(f"对比图表已保存: {plot_path}")
    except Exception as e:
        logger.warning(f"策略对比图表生成失败: {e}")
    
    return results


def run_batch_backtest(tickers, strategies=None, output_dir='./reports'):
    """
    批量回测多只股票
    
    Args:
        tickers: 股票代码列表
        strategies: 策略列表
        output_dir: 输出目录
    
    Returns:
        dict: 所有回测结果
    """
    all_results = {}
    
    for ticker in tickers:
        try:
            results = run_single_ticker_backtest(ticker, strategies, output_dir)
            if results:
                all_results[ticker] = results
        except Exception as e:
            logger.error(f"{ticker} 回测失败: {e}")
    
    return all_results


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='美股量化交易系统 - 回测运行',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例：
  # 回测单只股票
  python run_backtest.py --ticker AAPL
  
  # 批量回测多只股票
  python run_backtest.py --tickers AAPL MSFT GOOGL
  
  # 指定输出目录
  python run_backtest.py --ticker AAPL --output reports/backtest
        '''
    )
    
    parser.add_argument('--ticker', type=str, help='单只股票代码 (e.g., AAPL)')
    parser.add_argument('--tickers', nargs='+', help='多只股票代码 (e.g., AAPL MSFT GOOGL)')
    parser.add_argument('--output', type=str, default='./reports', help='输出目录')
    parser.add_argument('--strategies', nargs='+', 
                       choices=['sma', 'rsi', 'macd'],
                       help='要运行的策略')
    
    args = parser.parse_args()
    
    # 创建输出目录
    Path(args.output).mkdir(parents=True, exist_ok=True)
    
    # 确定策略
    strategy_map = {
        'sma': SMACrossover(),
        'rsi': RSIStrategy(),
        'macd': MACDStrategy(),
    }
    
    if args.strategies:
        strategies = [strategy_map[s] for s in args.strategies if s in strategy_map]
    else:
        strategies = [SMACrossover(), RSIStrategy(), MACDStrategy()]
    
    # 确定股票列表
    if args.ticker:
        tickers = [args.ticker]
    elif args.tickers:
        tickers = args.tickers
    else:
        # 默认股票列表
        tickers = ['AAPL', 'MSFT', 'GOOGL']
    
    logger.info("="*70)
    logger.info(f"开始回测: {', '.join(tickers)}")
    logger.info(f"策略: {', '.join([s.name for s in strategies])}")
    logger.info("="*70)
    
    # 运行回测
    results = run_batch_backtest(tickers, strategies, args.output)
    
    # 汇总
    logger.info("="*70)
    logger.info(f"回测完成！结果保存在: {args.output}")
    logger.info("="*70)


if __name__ == '__main__':
    main()
