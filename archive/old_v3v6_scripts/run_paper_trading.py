#!/usr/bin/env python3
"""
Paper Trading 系统 — 样本外验证 (V6 完整版)

包含所有因子：基本面 + 动量 + Regime + Earnings + Insider + Short Interest + 新闻情绪(Haiku)

用法:
    # 生成本月信号（每月初跑一次）
    python3 run_paper_trading.py signal

    # 查看历史表现（随时跑）
    python3 run_paper_trading.py review

    # 发送信号到 Telegram
    python3 run_paper_trading.py signal --telegram

    # 不用 Haiku（关键词方法代替）
    python3 run_paper_trading.py signal --no-haiku

工作流:
    每月1号（或第一个交易日）跑 signal → 记录选股 + 权重
    月底跑 review → 对比实际涨跌 → 累计 P&L
    3-6个月后看总 Alpha，决定是否上实盘
"""

import sys
import json
import argparse
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))

from data.data_fetcher import DataFetcher
from data.fundamental_fetcher import FundamentalFetcher, ValueScreener
from strategy.momentum import MomentumScorer
from strategy.regime_filter import RegimeFilter
from strategy.portfolio_strategy import PortfolioConfig, PortfolioStrategy
from strategy.earnings_surprise import EarningsSurpriseScorer
from strategy.insider_signal import InsiderSignalScorer

# ---- 配置 ----

SP100_TICKERS = [
    'AAPL', 'MSFT', 'GOOGL', 'GOOG', 'AMZN', 'NVDA', 'META', 'TSLA',
    'AVGO', 'ORCL', 'CRM', 'AMD', 'ADBE', 'INTC', 'CSCO', 'QCOM',
    'TXN', 'IBM', 'INTU', 'AMAT',
    'JPM', 'BAC', 'GS', 'MS', 'WFC', 'C', 'BLK', 'SCHW', 'AXP', 'BK',
    'USB', 'COF',
    'UNH', 'JNJ', 'LLY', 'ABBV', 'MRK', 'PFE', 'TMO', 'ABT', 'DHR',
    'BMY', 'AMGN', 'GILD', 'MDT',
    'WMT', 'HD', 'PG', 'KO', 'PEP', 'COST', 'MCD', 'NKE', 'SBUX',
    'TGT', 'LOW',
    'CAT', 'BA', 'HON', 'GE', 'RTX', 'UPS', 'DE', 'LMT', 'MMM',
    'XOM', 'CVX', 'COP', 'SLB',
    'DIS', 'CMCSA', 'NFLX', 'T', 'VZ', 'TMUS',
    'NEE', 'DUK', 'SO',
    'V', 'MA', 'PYPL', 'ACN', 'LIN', 'UNP', 'PM',
]

MACRO_TICKERS = {
    'tnx': '^TNX', 'irx': '^IRX', 'vix': '^VIX', 'hyg': 'HYG', 'lqd': 'LQD',
}

# V6 完整配置
CONFIG = PortfolioConfig(
    top_n=10,
    min_combined_score=55,
    min_momentum_score=40,
    weight_fundamental=0.5,
    weight_momentum=0.3,
    weight_analyst=0.2,
    max_single_weight=0.12,
    spy_base_weight=0.20,
    trailing_stop_pct=0.25,
    use_regime_filter=True,
    rebalance_freq='monthly',
    initial_cash=100000,
    commission=5,
)

PAPER_DIR = Path('./paper_trading')
SIGNALS_FILE = PAPER_DIR / 'signals.json'


def load_signals():
    """加载历史信号记录"""
    if SIGNALS_FILE.exists():
        with open(SIGNALS_FILE) as f:
            return json.load(f)
    return []


def save_signals(signals):
    """保存信号记录"""
    PAPER_DIR.mkdir(parents=True, exist_ok=True)
    with open(SIGNALS_FILE, 'w') as f:
        json.dump(signals, f, indent=2, default=str)


def generate_signal(use_haiku=True):
    """生成本月选股信号（V6 完整版）"""
    today = datetime.now().strftime('%Y-%m-%d')
    data_start = (datetime.now() - timedelta(days=400)).strftime('%Y-%m-%d')

    print(f"{'='*60}")
    print(f"Paper Trading 信号生成 — {today}")
    print(f"策略: V6 完整版 (基本面+动量+Regime+Earnings+Insider+News)")
    print(f"{'='*60}")

    # 检查本月是否已生成
    signals = load_signals()
    current_month = datetime.now().strftime('%Y-%m')
    for s in signals:
        if s['month'] == current_month:
            print(f"\n本月 ({current_month}) 已有信号，跳过。")
            print(f"如需重新生成，请先删除 {SIGNALS_FILE} 中对应记录。")
            print_signal(s)
            return s

    # 1. 数据
    print(f"\n[1] 获取价格数据...")
    price_fetcher = DataFetcher(cache_dir='./data/cache')
    fund_fetcher = FundamentalFetcher(cache_dir='./data/cache/fundamentals')
    screener = ValueScreener()
    momentum_scorer = MomentumScorer()
    regime_filter = RegimeFilter()
    strategy = PortfolioStrategy(CONFIG)
    earnings_scorer = EarningsSurpriseScorer()
    insider_scorer = InsiderSignalScorer()

    # 价格
    price_data = {}
    for ticker in SP100_TICKERS:
        data = price_fetcher.fetch_historical_data(ticker, start_date=data_start)
        if data is not None and len(data) > 50:
            price_data[ticker] = data

    # SPY
    spy_data = price_fetcher.fetch_historical_data('SPY', start_date=data_start)

    # 宏观
    macro_data = {}
    for key, ticker in MACRO_TICKERS.items():
        data = price_fetcher.fetch_historical_data(ticker, start_date=data_start)
        if data is not None and len(data) > 50:
            macro_data[key] = data

    print(f"  标的: {len(price_data)}/{len(SP100_TICKERS)}")

    # 2. 基本面 + Short Interest
    print(f"\n[2] 基本面评分...")
    fund_data = fund_fetcher.fetch_batch(list(price_data.keys()))
    screening_df = screener.screen_universe(fund_data)
    fundamental_scores = {}
    short_interest = {}
    for _, row in screening_df.iterrows():
        fundamental_scores[row['ticker']] = {
            'total_score': row['total_score'],
            'analyst_score': row.get('analyst_score', row['total_score']),
        }
    for tk, fd in fund_data.items():
        si = fd.get('short_percent_of_float')
        if si is not None:
            short_interest[tk] = si

    si_count = sum(1 for v in short_interest.values() if v is not None)
    print(f"  基本面: {len(fundamental_scores)} | Short Interest: {si_count}")

    # 3. 动量
    print(f"\n[3] 动量评分...")
    momentum_scores = {}
    for ticker, data in price_data.items():
        mom = momentum_scorer.calculate_momentum(data)
        if mom is not None:
            momentum_scores[ticker] = mom

    # 4. Regime
    print(f"\n[4] 市场环境...")
    regime = regime_filter.get_regime(spy_data, macro_data=macro_data)
    regime_label = regime.get('regime', 'UNKNOWN')
    regime_score = regime.get('composite_score', 0)
    position_mult = regime.get('position_multiplier', 1.0)
    print(f"  Regime: {regime_label} (score={regime_score:.0f}, mult={position_mult})")

    # 5. Earnings Surprise
    print(f"\n[5] Earnings Surprise...")
    for ticker in fundamental_scores:
        es = earnings_scorer.score_at_date(ticker, datetime.now().strftime('%Y-%m-%d'))
        if es.get('data_available'):
            orig = fundamental_scores[ticker]['total_score']
            adjusted = orig * 0.8 + es['earnings_score'] * 0.2
            fundamental_scores[ticker]['total_score'] = adjusted

    # 6. Insider Trading
    print(f"\n[6] Insider Trading...")
    insider_scores = insider_scorer.score_universe(
        list(fundamental_scores.keys()), datetime.now().strftime('%Y-%m-%d')
    )
    insider_active = sum(1 for v in insider_scores.values() if v.get('insider_bonus', 0) > 0)
    print(f"  有 insider 加分: {insider_active}")

    # 7. 新闻情绪（Haiku 或关键词）
    print(f"\n[7] 新闻情绪...")
    news_scores = None
    news_details = {}  # 保存新闻明细供 Telegram 推送

    try:
        from data.live_news_sentiment import LiveNewsScorer

        if use_haiku:
            news_scorer = LiveNewsScorer()  # 从环境变量读 ANTHROPIC_API_KEY
            print(f"  使用 Haiku 分析新闻情绪")
        else:
            news_scorer = LiveNewsScorer(api_key='')  # 空 key → fallback 到关键词
            print(f"  使用关键词方法（无 Haiku）")

        news_scores = {}
        for ticker in list(fundamental_scores.keys()):
            result = news_scorer.score_ticker(ticker)
            if result['data_available']:
                news_scores[ticker] = result
                news_details[ticker] = result.get('headlines', [])[:3]

        news_with_data = sum(1 for v in news_scores.values() if v.get('news_count', 0) > 0)
        print(f"  有新闻数据: {news_with_data}/{len(fundamental_scores)}")
    except Exception as e:
        print(f"  新闻模块加载失败: {e}")
        news_scores = None

    # 8. 选股
    print(f"\n[8] 选股...")
    selected = strategy.select_stocks(
        fundamental_scores, momentum_scores,
        short_interest=short_interest,
        insider_scores=insider_scores,
        news_scores=news_scores,
    )

    # 9. 记录价格快照
    entry_prices = {}
    for s in selected:
        ticker = s['ticker']
        if ticker in price_data:
            entry_prices[ticker] = round(float(price_data[ticker].iloc[-1]['Close']), 2)

    spy_price = round(float(spy_data.iloc[-1]['Close']), 2) if spy_data is not None else None

    # 组装信号
    signal = {
        'date': today,
        'month': current_month,
        'version': 'V6',
        'regime': regime_label,
        'regime_score': round(regime_score, 1),
        'position_multiplier': position_mult,
        'spy_price': spy_price,
        'stocks': [
            {
                'ticker': s['ticker'],
                'combined_score': s['combined_score'],
                'fundamental_score': s['fundamental_score'],
                'momentum_score': s['momentum_score'],
                'insider_bonus': s.get('insider_bonus', 0),
                'news_bonus': s.get('news_bonus', 0),
                'weight': s['weight'] * position_mult,
                'entry_price': entry_prices.get(s['ticker']),
            }
            for s in selected
        ],
        'news_highlights': {
            ticker: details[:2] for ticker, details in news_details.items()
            if ticker in {s['ticker'] for s in selected}
        },
        # 月底填入
        'end_prices': None,
        'spy_end_price': None,
        'portfolio_return': None,
        'spy_return': None,
        'alpha': None,
    }

    signals.append(signal)
    save_signals(signals)

    print_signal(signal)
    return signal


def print_signal(signal):
    """打印信号详情"""
    version = signal.get('version', 'V3')
    print(f"\n{'='*70}")
    print(f"本月信号 — {signal['date']} ({version})")
    print(f"Regime: {signal['regime']} (score={signal['regime_score']}, mult={signal['position_multiplier']})")
    print(f"SPY: ${signal['spy_price']}")
    print(f"{'='*70}")

    print(f"\n{'Rank':>4} {'Ticker':>7} {'Score':>6} {'Fund':>5} {'Mom':>5} "
          f"{'Ins':>4} {'News':>5} {'Weight':>7} {'Price':>8}")
    print(f"{'-'*65}")
    for i, s in enumerate(signal['stocks'], 1):
        ins = s.get('insider_bonus', 0)
        news = s.get('news_bonus', 0)
        print(f"{i:4d} {s['ticker']:>7} {s['combined_score']:6.1f} "
              f"{s['fundamental_score']:5.1f} {s['momentum_score']:5.1f} "
              f"{ins:+4.0f} {news:+5.1f} "
              f"{s['weight']:6.1%} ${s['entry_price']:>7.2f}")

    total_stock_weight = sum(s['weight'] for s in signal['stocks'])
    spy_weight = CONFIG.spy_base_weight * signal['position_multiplier']
    cash_weight = 1.0 - total_stock_weight - spy_weight

    print(f"\n仓位分配:")
    print(f"  个股: {total_stock_weight:.1%}")
    print(f"  SPY:  {spy_weight:.1%}")
    print(f"  现金: {cash_weight:.1%}")

    # 新闻亮点
    highlights = signal.get('news_highlights', {})
    if highlights:
        print(f"\n新闻情绪亮点:")
        for ticker, items in highlights.items():
            for item in items[:1]:  # 每只股只显示最重要的 1 条
                sent = item.get('sentiment', 0)
                emoji = "📈" if sent > 0.1 else ("📉" if sent < -0.1 else "➡️")
                title = item.get('title', '')[:55]
                print(f"  {emoji} {ticker}: {title}")


def review_performance():
    """回顾历史信号表现"""
    signals = load_signals()
    if not signals:
        print("没有历史信号记录。先跑 'signal' 生成信号。")
        return

    price_fetcher = DataFetcher(cache_dir='./data/cache')
    updated = False

    print(f"{'='*70}")
    print(f"Paper Trading 表现回顾")
    print(f"{'='*70}")

    cumulative_portfolio = 0.0
    cumulative_spy = 0.0
    months_with_data = 0

    for signal in signals:
        month = signal['month']

        # 尝试填入月底价格
        if signal.get('portfolio_return') is None:
            year, mon = map(int, month.split('-'))
            if mon == 12:
                next_month_start = f"{year+1}-01-01"
            else:
                next_month_start = f"{year}-{mon+1:02d}-01"

            if datetime.now().strftime('%Y-%m-%d') < next_month_start:
                print(f"\n{month}: 本月尚未结束，暂无收益数据")
                continue

            end_prices = {}
            for s in signal['stocks']:
                ticker = s['ticker']
                data = price_fetcher.fetch_historical_data(
                    ticker, start_date=signal['date'],
                    end_date=next_month_start
                )
                if data is not None and len(data) > 0:
                    end_prices[ticker] = round(float(data.iloc[-1]['Close']), 2)

            spy_data = price_fetcher.fetch_historical_data(
                'SPY', start_date=signal['date'],
                end_date=next_month_start
            )
            spy_end = round(float(spy_data.iloc[-1]['Close']), 2) if spy_data is not None and len(spy_data) > 0 else None

            if end_prices and spy_end:
                portfolio_ret = 0.0
                for s in signal['stocks']:
                    ticker = s['ticker']
                    if ticker in end_prices and s['entry_price']:
                        stock_ret = (end_prices[ticker] - s['entry_price']) / s['entry_price']
                        portfolio_ret += stock_ret * s['weight']

                if signal['spy_price']:
                    spy_ret = (spy_end - signal['spy_price']) / signal['spy_price']
                    spy_weight = CONFIG.spy_base_weight * signal['position_multiplier']
                    portfolio_ret += spy_ret * spy_weight
                else:
                    spy_ret = 0

                signal['end_prices'] = end_prices
                signal['spy_end_price'] = spy_end
                signal['portfolio_return'] = round(portfolio_ret * 100, 2)
                signal['spy_return'] = round(spy_ret * 100, 2)
                signal['alpha'] = round((portfolio_ret - spy_ret) * 100, 2)
                updated = True

        if signal.get('portfolio_return') is not None:
            months_with_data += 1
            cumulative_portfolio += signal['portfolio_return']
            cumulative_spy += signal['spy_return']

            alpha = signal['alpha']
            beat = "BEAT" if alpha > 0 else "MISS"
            version = signal.get('version', 'V3')
            print(f"\n{month} ({version}): Regime={signal['regime']}")
            print(f"  策略: {signal['portfolio_return']:+.2f}%  |  "
                  f"SPY: {signal['spy_return']:+.2f}%  |  "
                  f"Alpha: {alpha:+.2f}%  |  {beat}")

            for s in signal['stocks']:
                ticker = s['ticker']
                end_p = signal['end_prices'].get(ticker)
                if end_p and s['entry_price']:
                    ret = (end_p - s['entry_price']) / s['entry_price'] * 100
                    print(f"    {ticker:>6} ${s['entry_price']:>7.2f} → ${end_p:>7.2f}  {ret:+.1f}%")

    if updated:
        save_signals(signals)

    if months_with_data > 0:
        print(f"\n{'='*70}")
        print(f"累计表现 ({months_with_data} 个月)")
        print(f"{'='*70}")
        print(f"  策略累计: {cumulative_portfolio:+.2f}%")
        print(f"  SPY累计:  {cumulative_spy:+.2f}%")
        print(f"  累计Alpha: {cumulative_portfolio - cumulative_spy:+.2f}%")
        print(f"  月均Alpha: {(cumulative_portfolio - cumulative_spy) / months_with_data:+.2f}%")

        beat_months = sum(1 for s in signals if s.get('alpha') is not None and s['alpha'] > 0)
        print(f"  月度胜率:  {beat_months}/{months_with_data} ({beat_months/months_with_data*100:.0f}%)")


def format_telegram(signal):
    """格式化 Telegram 消息"""
    version = signal.get('version', 'V3')
    lines = []
    lines.append(f"<b>📊 Paper Trading 信号 — {signal['date']} ({version})</b>")
    lines.append(f"Regime: <b>{signal['regime']}</b> (score={signal['regime_score']})")
    lines.append(f"SPY: ${signal['spy_price']}")
    lines.append("")

    for i, s in enumerate(signal['stocks'], 1):
        ins = s.get('insider_bonus', 0)
        news = s.get('news_bonus', 0)
        extras = []
        if ins > 0:
            extras.append(f"Ins+{ins:.0f}")
        if abs(news) > 0.1:
            extras.append(f"News{news:+.1f}")
        extra_str = f" ({', '.join(extras)})" if extras else ""

        lines.append(
            f"{i}. <b>{s['ticker']}</b>  "
            f"Score={s['combined_score']:.0f}  "
            f"W={s['weight']:.0%}  "
            f"${s['entry_price']}{extra_str}"
        )

    total_weight = sum(s['weight'] for s in signal['stocks'])
    spy_w = CONFIG.spy_base_weight * signal['position_multiplier']
    lines.append("")
    lines.append(f"个股 {total_weight:.0%} | SPY {spy_w:.0%} | 现金 {1-total_weight-spy_w:.0%}")

    # 新闻亮点
    highlights = signal.get('news_highlights', {})
    if highlights:
        lines.append("")
        lines.append("<b>新闻情绪:</b>")
        for ticker, items in highlights.items():
            for item in items[:1]:
                sent = item.get('sentiment', 0)
                emoji = "📈" if sent > 0.1 else ("📉" if sent < -0.1 else "➡️")
                title = item.get('title', '')[:50]
                lines.append(f"  {emoji} {ticker}: {title}")

    return "\n".join(lines)


def send_telegram(signal, token, chat_id):
    """发送到 Telegram"""
    try:
        import requests
    except ImportError:
        print("需要 requests: pip install requests")
        return False

    text = format_telegram(signal)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, json={
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML',
    })

    if resp.ok:
        print(f"Telegram 发送成功!")
        return True
    else:
        print(f"Telegram 发送失败: {resp.text}")
        return False


def main():
    parser = argparse.ArgumentParser(description='Paper Trading 系统 (V6)')
    parser.add_argument('command', choices=['signal', 'review'],
                        help='signal=生成本月信号, review=回顾表现')
    parser.add_argument('--telegram', action='store_true', help='发送到 Telegram')
    parser.add_argument('--token', default=None, help='Telegram bot token')
    parser.add_argument('--chat-id', default=None, help='Telegram chat ID')
    parser.add_argument('--no-haiku', action='store_true',
                        help='不用 Haiku，改用关键词方法分析新闻')
    args = parser.parse_args()

    if args.command == 'signal':
        signal = generate_signal(use_haiku=not args.no_haiku)

        if args.telegram and signal:
            token = args.token or input("Telegram Bot Token: ").strip()
            chat_id = args.chat_id or input("Telegram Chat ID: ").strip()
            if token and chat_id:
                send_telegram(signal, token, chat_id)

    elif args.command == 'review':
        review_performance()


if __name__ == '__main__':
    main()
