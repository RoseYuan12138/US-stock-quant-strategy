#!/usr/bin/env python3
"""
对比回测：纯技术策略 vs 技术+新闻融合策略
同一时间段，看新闻有没有真的帮助
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from data.data_fetcher import DataFetcher
from strategy.strategies import SMACrossover, RSIStrategy, MACDStrategy
from backtest.backtester import MultiStrategyBacktest
from news.news_fetcher import NewsFetcher
from sentiment.sentiment_analyzer import SentimentAnalyzer
from signals.signal_fusion import SignalFusion
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_comparison():
    """对比测试：技术策略 vs 新闻融合策略"""
    
    logger.info("="*80)
    logger.info("对比回测：技术策略 vs 技术+新闻融合")
    logger.info("时间：2026-01-01 ~ 2026-03-29 | 初始资金：$100,000")
    logger.info("="*80)
    
    fetcher = DataFetcher()
    tickers = ['AAPL', 'MSFT', 'GOOGL']
    
    results_comparison = []
    
    for ticker in tickers:
        logger.info(f"\n{'='*80}")
        logger.info(f"测试 {ticker}")
        logger.info(f"{'='*80}")
        
        # 获取数据
        data = fetcher.fetch_historical_data(ticker, start_date='2024-01-01')
        if data is None or len(data) == 0:
            logger.error(f"{ticker}: 无法获取数据")
            continue
        
        # 筛选时间范围
        data = data[(data.index >= '2026-01-01') & (data.index <= '2026-03-29')]
        if len(data) == 0:
            logger.error(f"{ticker}: 时间范围内无数据")
            continue
        
        logger.info(f"数据范围：{data.index[0].date()} ~ {data.index[-1].date()}, {len(data)} 条")
        
        # ============ 方案 A: 纯技术策略 ============
        logger.info(f"\n【方案 A】纯技术策略")
        logger.info("-"*80)
        
        strategies_tech = [
            SMACrossover(),
            RSIStrategy(),
            MACDStrategy()
        ]
        
        multi_tech = MultiStrategyBacktest(initial_cash=100000, commission=10)
        results_tech = multi_tech.run(data, strategies_tech)
        
        best_tech_strategy = None
        best_tech_return = -999
        
        for strat_name, result in results_tech.items():
            report = result['report']
            ret = report['total_return_pct']
            logger.info(f"{strat_name:15s}: {ret:+7.2f}% | 夏普: {report['sharpe_ratio']:6.2f} | 回撤: {report['max_drawdown']*100:6.2f}%")
            
            if ret > best_tech_return:
                best_tech_return = ret
                best_tech_strategy = strat_name
        
        logger.info(f"最佳技术策略：{best_tech_strategy} ({best_tech_return:+.2f}%)")
        
        # ============ 方案 B: 技术+新闻融合 ============
        logger.info(f"\n【方案 B】技术+新闻融合策略")
        logger.info("-"*80)
        
        try:
            # 尝试获取新闻
            news_fetcher = NewsFetcher()
            news = news_fetcher.fetch_news(ticker, days=90)
            
            if news and len(news) > 0:
                logger.info(f"获取新闻 {len(news)} 条")
                
                # 情感分析
                analyzer = SentimentAnalyzer()
                sentiment_score = analyzer.analyze_sentiment(news)
                logger.info(f"新闻情感分数：{sentiment_score['average_sentiment']:.2f} (范围 0-100)")
                
                # 信号融合
                fusion = SignalFusion()
                
                # 计算技术信号和新闻信号，融合后生成新信号
                tech_score = (
                    result['report']['total_return_pct'] * 10 / 100 + 50  # 转换为 0-100
                )
                news_signal = sentiment_score['average_sentiment']
                
                fused_score = 0.6 * max(0, min(100, tech_score)) + 0.4 * news_signal
                fused_return = (fused_score - 50) / 10 * 100  # 转换回百分比
                
                logger.info(f"技术评分：{tech_score:.1f}/100")
                logger.info(f"新闻评分：{news_signal:.1f}/100")
                logger.info(f"融合信心度：{fused_score:.1f}/100")
                logger.info(f"预期收益（融合）：{fused_return:+.2f}%")
                
                # 记录对比
                results_comparison.append({
                    'Ticker': ticker,
                    '技术策略': best_tech_return,
                    '新闻评分': news_signal,
                    '融合信心度': fused_score,
                    '技术+新闻预期': fused_return,
                    '新闻是否帮助': '✅ 是' if fused_return > best_tech_return else '❌ 否'
                })
            else:
                logger.warning(f"{ticker}: 无法获取新闻数据")
                results_comparison.append({
                    'Ticker': ticker,
                    '技术策略': best_tech_return,
                    '新闻评分': 0,
                    '融合信心度': 0,
                    '技术+新闻预期': 0,
                    '新闻是否帮助': '⚠️ 无数据'
                })
        except Exception as e:
            logger.warning(f"{ticker}: 新闻融合失败 - {e}")
            results_comparison.append({
                'Ticker': ticker,
                '技术策略': best_tech_return,
                '新闻评分': 0,
                '融合信心度': 0,
                '技术+新闻预期': 0,
                '新闻是否帮助': '❌ 失败'
            })
    
    # 打印总结对比
    logger.info(f"\n{'='*80}")
    logger.info("📊 对比总结")
    logger.info(f"{'='*80}\n")
    
    if results_comparison:
        df = pd.DataFrame(results_comparison)
        logger.info(df.to_string(index=False))
        
        # 统计
        avg_tech = df['技术策略'].mean()
        avg_fused = df['技术+新闻预期'].mean()
        improvement = avg_fused - avg_tech
        
        logger.info(f"\n平均收益率对比：")
        logger.info(f"  纯技术策略：{avg_tech:+.2f}%")
        logger.info(f"  技术+新闻：{avg_fused:+.2f}%")
        logger.info(f"  提升：{improvement:+.2f}%")
        
        if improvement > 0:
            logger.info(f"\n✅ 新闻融合有帮助！提升约 {improvement:.2f}%")
        elif improvement < -2:
            logger.info(f"\n❌ 新闻融合反而变差，降低约 {abs(improvement):.2f}%")
        else:
            logger.info(f"\n⏸️ 新闻融合影响有限（±{abs(improvement):.2f}%）")

if __name__ == '__main__':
    run_comparison()
