#!/usr/bin/env python3
"""
演示脚本：新闻 + 技术信号融合系统
展示如何使用整个升级后的系统
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
import json

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from news.news_fetcher import NewsFetcher
from sentiment.sentiment_analyzer import SentimentAnalyzer
from signals.signal_fusion import SignalFusion


def demo_news_and_sentiment():
    """演示新闻获取和情感分析"""
    print("\n" + "="*70)
    print("【演示 1】新闻获取和情感分析")
    print("="*70)
    
    # 创建爬虫和分析器
    fetcher = NewsFetcher()
    analyzer = SentimentAnalyzer()
    
    # 获取 AAPL 的新闻
    print("\n📰 正在获取 AAPL 的新闻...")
    news = fetcher.fetch_news_for_ticker('AAPL', days=1, limit=5)
    
    if not news:
        print("⚠️ 未获取到新闻，使用模拟数据进行演示...")
        # 使用模拟数据
        news = [
            {
                'title': 'Apple beats Q1 earnings expectations with record revenue',
                'description': 'Apple exceeded analyst expectations in Q1 with strong iPhone sales and growing services revenue.',
                'source': 'Reuters',
                'published_at': (datetime.utcnow() - timedelta(hours=2)).isoformat(),
                'url': 'https://example.com/news1'
            },
            {
                'title': 'Apple announces new AI features for iPhone',
                'description': 'The tech giant unveils innovative AI capabilities integrated into the latest iPhone models.',
                'source': 'TechCrunch',
                'published_at': (datetime.utcnow() - timedelta(hours=12)).isoformat(),
                'url': 'https://example.com/news2'
            },
            {
                'title': 'Supply chain concerns impact Apple production',
                'description': 'Recent geopolitical tensions may affect Apple manufacturing capacity in coming quarters.',
                'source': 'Bloomberg',
                'published_at': (datetime.utcnow() - timedelta(hours=18)).isoformat(),
                'url': 'https://example.com/news3'
            },
        ]
    
    print(f"\n📍 获取了 {len(news)} 条新闻：")
    
    # 分析情感
    analyzed_news = analyzer.analyze_batch_news(news)
    
    for i, article in enumerate(analyzed_news, 1):
        sentiment = article.get('sentiment', {})
        print(f"\n  {i}. {article['title']}")
        print(f"     来源: {article['source']}")
        print(f"     情感: {sentiment['label']} | 极性: {sentiment['polarity']:+.2f} | 置信度: {sentiment['confidence']:.0%}")
    
    # 聚合
    aggregated = analyzer.aggregate_sentiment(analyzed_news, hours=24)
    
    print(f"\n📊 情感聚合结果 (24h 窗口):")
    print(f"   正面新闻: {aggregated['positive_count']} 条")
    print(f"   负面新闻: {aggregated['negative_count']} 条")
    print(f"   中立新闻: {aggregated['neutral_count']} 条")
    print(f"   平均极性: {aggregated['average_sentiment']:+.2f}")
    print(f"   情感评分 (0-100): {aggregated['sentiment_score_0_100']}")
    print(f"   趋势: {aggregated['trend']}")
    
    return aggregated


def demo_signal_fusion(sentiment_data):
    """演示技术和新闻信号融合"""
    print("\n" + "="*70)
    print("【演示 2】技术信号和新闻情感融合")
    print("="*70)
    
    fusion = SignalFusion(technical_weight=0.6, news_weight=0.4)
    
    # 模拟技术指标
    indicators = {
        'rsi': 28,              # 超卖（看好）
        'sma_20': 195.5,
        'sma_50': 192.0,        # SMA20 > SMA50（看好）
        'macd': 2.8,
        'macd_signal': 2.1,     # MACD > Signal（金叉，看好）
    }
    
    print("\n📊 技术指标输入:")
    print(f"   RSI: {indicators['rsi']:.0f} (超卖区间)")
    print(f"   SMA 20/50: {indicators['sma_20']:.1f} / {indicators['sma_50']:.1f} (看好)")
    print(f"   MACD/Signal: {indicators['macd']:.2f} / {indicators['macd_signal']:.2f} (金叉)")
    
    # 计算技术评分
    tech_score = fusion.calculate_technical_score(indicators)
    print(f"\n   → 技术信号评分: {tech_score:.0f}/100")
    
    # 使用新闻情感数据
    news_score = fusion.calculate_news_score(sentiment_data)
    print(f"\n📰 新闻情感输入:")
    print(f"   情感评分: {news_score:.0f}/100")
    
    # 融合
    result = fusion.fuse_signals(tech_score, news_score, sentiment_data, indicators)
    
    print(f"\n🎯 融合结果:")
    print(f"   综合信心度: {result['confidence']:.0f}%")
    print(f"   信号: {result['signal']}")
    print(f"   分歧类型: {result['divergence']}")
    print(f"   推理: {result['reasoning']}")


def demo_full_pipeline():
    """演示完整流程"""
    print("\n" + "="*70)
    print("【演示 3】完整流程 - 一只股票的全信号生成")
    print("="*70)
    
    try:
        from data.data_fetcher import DataFetcher
        from signals.signal_generator import SignalGenerator
        from strategy.strategies import StrategyEnsemble
        
        fetcher = DataFetcher()
        ensemble = StrategyEnsemble()
        generator = SignalGenerator(strategies=ensemble.strategies)
        news_fetcher = NewsFetcher()
        sentiment_analyzer = SentimentAnalyzer()
        
        ticker = 'AAPL'
        print(f"\n获取 {ticker} 的历史数据...")
        
        # 获取价格数据
        data = fetcher.fetch_historical_data(ticker)
        
        if data is not None and len(data) >= 50:
            # 获取新闻
            print(f"获取 {ticker} 的新闻...")
            news = news_fetcher.fetch_news_for_ticker(ticker, days=1, limit=10)
            
            sentiment_data = None
            if news:
                analyzed_news = sentiment_analyzer.analyze_batch_news(news)
                sentiment_data = sentiment_analyzer.aggregate_sentiment(analyzed_news, hours=24)
                print(f"✓ 获取 {len(news)} 条新闻，情感评分 {sentiment_data['sentiment_score_0_100']}")
            else:
                print("⚠️ 未获取到新闻，仅使用技术信号")
            
            # 生成信号
            print(f"\n生成 {ticker} 的综合信号...")
            signal = generator.generate_signals(ticker, data, sentiment_data)
            
            if signal['status'] == 'OK':
                print(f"✓ 信号生成成功")
                print(f"\n  当前价: ${signal['latest_price']:.2f}")
                
                fusion = signal.get('fusion', {})
                print(f"  综合信心度: {fusion.get('confidence', 0):.0f}%")
                print(f"  融合信号: {fusion.get('signal', 'UNKNOWN')}")
                print(f"  技术分: {fusion.get('technical_score', 0):.0f}% | 新闻分: {fusion.get('news_score', 0):.0f}%")
                print(f"  分歧: {fusion.get('divergence', 'unknown')}")
                
                if signal.get('indicators'):
                    ind = signal['indicators']
                    print(f"\n  技术指标:")
                    print(f"    RSI: {ind.get('rsi', 0):.0f}")
                    print(f"    MACD: {ind.get('macd', 0):.4f} vs Signal: {ind.get('macd_signal', 0):.4f}")
                
                print(f"\n  建议:")
                for advice in signal.get('advice', []):
                    print(f"    {advice}")
            else:
                print(f"✗ 生成失败: {signal.get('message')}")
        else:
            print(f"✗ 无法获取 {ticker} 的足够数据")
    
    except Exception as e:
        print(f"✗ 演示流程出错: {e}")
        import traceback
        traceback.print_exc()


def main():
    """主演示"""
    print("\n" + "🐱" * 35)
    print("美股量化系统升级演示 - 新闻驱动的信号融合")
    print("🐱" * 35)
    
    # 演示 1: 新闻和情感分析
    sentiment_data = demo_news_and_sentiment()
    
    # 演示 2: 信号融合
    demo_signal_fusion(sentiment_data)
    
    # 演示 3: 完整流程
    demo_full_pipeline()
    
    print("\n" + "="*70)
    print("演示完成！")
    print("="*70)
    print("\n下一步:")
    print("1. 配置 NewsAPI 密钥:")
    print("   export NEWSAPI_KEY='your_api_key_here'")
    print("\n2. 生成每日信号:")
    print("   python3 run_daily_signals.py --tickers AAPL MSFT GOOGL")
    print("\n3. 查看增强的日报格式")
    print("="*70 + "\n")


if __name__ == '__main__':
    main()
