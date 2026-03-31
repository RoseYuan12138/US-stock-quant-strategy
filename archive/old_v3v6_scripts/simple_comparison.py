#!/usr/bin/env python3
"""
简单对比：目前的技术策略回测结果
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 之前测试过的技术策略结果（纯技术，无新闻）
results = {
    'AAPL': {
        'RSI': 2.36,
        'SMA': -1.60,
        'MACD': -4.54,
        'best': 'RSI (+2.36%)'
    },
    'MSFT': {
        'RSI': -15.05,
        'SMA': 0.00,
        'MACD': -10.79,
        'best': 'SMA (0.00%)'
    },
    'GOOGL': {
        'RSI': -11.72,
        'SMA': 0.00,
        'MACD': -8.64,
        'best': 'SMA (0.00%)'
    }
}

logger.info("="*80)
logger.info("📊 技术策略回测结果 (2026-01-01 ~ 2026-03-29)")
logger.info("="*80)

# 统计
data = []
for ticker, strategies in results.items():
    best = strategies['best']
    best_return = float(best.split('(')[1].split('%')[0].replace('+', ''))
    
    logger.info(f"\n{ticker}")
    logger.info(f"  RSI:   {strategies['RSI']:+7.2f}%")
    logger.info(f"  SMA:   {strategies['SMA']:+7.2f}%")
    logger.info(f"  MACD:  {strategies['MACD']:+7.2f}%")
    logger.info(f"  最佳:  {best}")
    
    data.append({
        'Ticker': ticker,
        'RSI': strategies['RSI'],
        'SMA': strategies['SMA'],
        'MACD': strategies['MACD'],
        'Best': best_return
    })

df = pd.DataFrame(data)

# 整体统计
avg_all = (df['RSI'].sum() + df['SMA'].sum() + df['MACD'].sum()) / 9
avg_best = df['Best'].mean()
total_if_best = df['Best'].sum() / 3 * 100000

logger.info(f"\n{'='*80}")
logger.info(f"📈 整体统计")
logger.info(f"{'='*80}")
logger.info(f"所有交易的平均收益：{avg_all:+.2f}%")
logger.info(f"每只股票选最佳策略的平均收益：{avg_best:+.2f}%")
logger.info(f"如果每只股票 $100k 都选最佳策略：总收益 ${total_if_best:+,.2f}")

logger.info(f"\n【关键发现】")
logger.info(f"✅ 虽然大多数策略亏钱，但如果「挑对策略」可以保本甚至微利")
logger.info(f"❌ 问题是：你事先不知道哪个策略对哪只股票最好")
logger.info(f"💡 这就是「新闻+技术融合」的价值所在：")
logger.info(f"   • 用新闻过滤掉「明显有问题」的信号")
logger.info(f"   • 增强「信号质量」而不是改变策略本身")

logger.info(f"\n【新闻融合的预期效果】")
logger.info(f"如果新闻融合能把错误信号拦住 20-30%：")
logger.info(f"  • MSFT RSI -15% → 可能变成 -5% (避免最坏的亏损)")
logger.info(f"  • GOOGL RSI -11.72% → 可能变成 -3% (减少损失)")
logger.info(f"  • 从 -5.55% → 可能变成 -1% ~ 0%（已经很不错）")

