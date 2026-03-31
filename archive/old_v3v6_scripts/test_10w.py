#!/usr/bin/env python3
"""
Rose 的 10 万美金测试：2026-01-01 到 2026-03-29
"""

import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from data.data_fetcher import DataFetcher
from strategy.strategies import SMACrossover, RSIStrategy, MACDStrategy
from backtest.backtester import MultiStrategyBacktest
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_10w_from_Jan():
    """测试 10 万美金从 2026-01-01 到现在"""
    
    logger.info("="*70)
    logger.info("Rose 的 10 万美金回测")
    logger.info("时间：2026-01-01 ~ 2026-03-29")
    logger.info("初始资金：$100,000")
    logger.info("="*70)
    
    # 获取数据
    fetcher = DataFetcher()
    
    # 测试多只股票
    tickers = ['AAPL', 'MSFT', 'GOOGL']
    all_summary = []
    
    for ticker in tickers:
        logger.info(f"\n{'='*70}")
        logger.info(f"开始回测 {ticker}")
        logger.info(f"{'='*70}")
        
        # 获取从 2024-01-01 开始的数据（保险起见）
        data = fetcher.fetch_historical_data(ticker, start_date='2024-01-01')
        
        if data is None or len(data) == 0:
            logger.error(f"{ticker}: 无法获取数据")
            continue
        
        # 筛选时间范围：2026-01-01 ~ 2026-03-29
        data = data[(data.index >= '2026-01-01') & (data.index <= '2026-03-29')]
        
        if len(data) == 0:
            logger.error(f"{ticker}: 指定时间范围内无数据")
            continue
        
        logger.info(f"{ticker}: 数据范围 {data.index[0].date()} ~ {data.index[-1].date()}, 共 {len(data)} 条")
        
        # 策略列表
        strategies = [
            SMACrossover(),
            RSIStrategy(),
            MACDStrategy()
        ]
        
        # 运行回测（$100,000 初始资金）
        multi = MultiStrategyBacktest(initial_cash=100000, commission=10)
        results = multi.run(data, strategies)
        
        # 打印结果
        logger.info(f"\n{ticker} 回测结果：")
        logger.info("-"*70)
        
        best_strategy = None
        best_return = -999
        
        for strategy_name, result in results.items():
            report = result['report']
            initial = 100000
            final = report['final_value']
            profit = final - initial
            profit_pct = (profit / initial) * 100
            
            logger.info(f"\n【{strategy_name}】")
            logger.info(f"  初始资金：${initial:,.2f}")
            logger.info(f"  最终资产：${final:,.2f}")
            logger.info(f"  利润：${profit:,.2f} ({profit_pct:+.2f}%)")
            logger.info(f"  最大回撤：{report['max_drawdown']*100:.2f}%")
            logger.info(f"  夏普比率：{report['sharpe_ratio']:.2f}")
            logger.info(f"  胜率：{report['win_rate']*100:.2f}%")
            logger.info(f"  交易次数：{report['total_trades']}")
            
            all_summary.append({
                'Ticker': ticker,
                'Strategy': strategy_name,
                'Initial': initial,
                'Final': final,
                'Profit': profit,
                'Return%': profit_pct
            })
            
            if profit_pct > best_return:
                best_return = profit_pct
                best_strategy = strategy_name
        
        logger.info(f"\n{ticker} 最佳策略：{best_strategy} ({best_return:+.2f}%)")

    # 总结
    logger.info(f"\n{'='*70}")
    logger.info("整体总结")
    logger.info(f"{'='*70}")
    
    df_summary = pd.DataFrame(all_summary)
    
    logger.info("\n所有结果对比：")
    logger.info(df_summary.to_string(index=False))
    
    # 计算组合收益
    total_initial = df_summary['Initial'].sum()
    total_final = df_summary['Final'].sum()
    total_profit = total_final - total_initial
    total_return = (total_profit / total_initial) * 100
    
    logger.info(f"\n组合统计（各策略各买1个，均匀分配）：")
    logger.info(f"  总初始资金：${total_initial:,.2f}")
    logger.info(f"  总最终资产：${total_final:,.2f}")
    logger.info(f"  总利润：${total_profit:,.2f}")
    logger.info(f"  总收益率：{total_return:+.2f}%")
    
    # 最佳单一交易
    best_trade = df_summary.loc[df_summary['Return%'].idxmax()]
    logger.info(f"\n最佳单一交易：{best_trade['Ticker']} - {best_trade['Strategy']}")
    logger.info(f"  收益率：{best_trade['Return%']:+.2f}%")
    logger.info(f"  利润：${best_trade['Profit']:,.2f}")

if __name__ == '__main__':
    test_10w_from_Jan()
