#!/usr/bin/env python3
"""
美股量化交易系统 - 日信号生成脚本
每日生成最新的交易信号和建议
"""

import sys
import argparse
import json
from pathlib import Path
from datetime import datetime

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent))

from data.data_fetcher import DataFetcher
from strategy.strategies import StrategyEnsemble
from signals.signal_generator import SignalGenerator
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_tickers_from_config(config_path='./config/config.yaml'):
    """从配置文件加载股票列表"""
    try:
        import yaml
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
            return config.get('tickers', [])
    except ImportError:
        logger.warning("PyYAML 未安装，使用默认股票列表")
        return ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA']
    except FileNotFoundError:
        logger.warning(f"配置文件 {config_path} 不存在，使用默认股票列表")
        return ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA']


def generate_signals_for_tickers(tickers, output_dir='./reports'):
    """
    为多只股票生成交易信号
    
    Args:
        tickers: 股票代码列表
        output_dir: 输出目录
    
    Returns:
        dict: 所有股票的信号
    """
    # 初始化
    fetcher = DataFetcher()
    ensemble = StrategyEnsemble()
    generator = SignalGenerator(strategies=ensemble.strategies)
    
    logger.info(f"为 {len(tickers)} 只股票生成信号...")
    
    all_signals = {}
    successful = 0
    
    for ticker in tickers:
        try:
            # 获取数据
            data = fetcher.fetch_historical_data(ticker)
            
            if data is None or len(data) < 50:
                logger.warning(f"{ticker}: 数据不足或获取失败")
                continue
            
            # 生成信号
            signal = generator.generate_signals(ticker, data)
            all_signals[ticker] = signal
            
            if signal['status'] == 'OK':
                successful += 1
                logger.info(f"✓ {ticker}: {signal['signal']} (置信度 {signal['signal_confidence']:.0f}%)")
            else:
                logger.warning(f"✗ {ticker}: {signal.get('message', 'Unknown error')}")
        
        except Exception as e:
            logger.error(f"{ticker}: {e}")
    
    logger.info(f"成功生成 {successful}/{len(tickers)} 只股票的信号")
    
    # 生成日报
    report_text = generator.generate_daily_report(all_signals)
    
    # 保存报告
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # 文本报告
    report_file = Path(output_dir) / f"daily_signals_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report_text)
    logger.info(f"日报已保存: {report_file}")
    
    # JSON 报告（便于后续处理和 Telegram 集成）
    json_file = Path(output_dir) / f"daily_signals_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(all_signals, f, indent=2, default=str)
    logger.info(f"JSON 信号已保存: {json_file}")
    
    return all_signals, report_text


def print_console_report(report_text):
    """在控制台打印报告"""
    print("\n" + report_text)


def send_telegram_report(report_text, token=None, chat_id=None):
    """
    发送报告到 Telegram（可选功能）
    
    Args:
        report_text: 报告文本
        token: Telegram bot token
        chat_id: 聊天 ID
    """
    if not token or not chat_id:
        logger.info("Telegram 未配置，跳过发送")
        return False
    
    try:
        import requests
        
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = {
            'chat_id': chat_id,
            'text': report_text,
            'parse_mode': 'HTML'
        }
        
        response = requests.post(url, json=data)
        if response.status_code == 200:
            logger.info("报告已发送到 Telegram")
            return True
        else:
            logger.error(f"Telegram 发送失败: {response.status_code}")
            return False
    
    except ImportError:
        logger.warning("requests 库未安装，无法发送 Telegram 消息")
        return False
    except Exception as e:
        logger.error(f"Telegram 发送错误: {e}")
        return False


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='美股量化交易系统 - 日信号生成',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例：
  # 为默认股票列表生成信号
  python run_daily_signals.py
  
  # 为指定股票生成信号
  python run_daily_signals.py --tickers AAPL MSFT GOOGL
  
  # 指定输出目录
  python run_daily_signals.py --output reports/signals
  
  # 发送到 Telegram
  python run_daily_signals.py --telegram-token YOUR_BOT_TOKEN --telegram-chat YOUR_CHAT_ID
        '''
    )
    
    parser.add_argument('--tickers', nargs='+', help='股票代码列表')
    parser.add_argument('--output', type=str, default='./reports', help='输出目录')
    parser.add_argument('--telegram-token', type=str, help='Telegram Bot Token')
    parser.add_argument('--telegram-chat', type=str, help='Telegram Chat ID')
    parser.add_argument('--no-print', action='store_true', help='不在控制台打印报告')
    
    args = parser.parse_args()
    
    # 确定股票列表
    if args.tickers:
        tickers = args.tickers
    else:
        tickers = load_tickers_from_config()
    
    logger.info("="*70)
    logger.info(f"美股交易信号生成")
    logger.info(f"股票: {', '.join(tickers)}")
    logger.info("="*70)
    
    # 生成信号
    signals, report_text = generate_signals_for_tickers(tickers, args.output)
    
    # 在控制台打印
    if not args.no_print:
        print_console_report(report_text)
    
    # 发送 Telegram（可选）
    if args.telegram_token and args.telegram_chat:
        send_telegram_report(report_text, args.telegram_token, args.telegram_chat)
    
    logger.info("="*70)
    logger.info("信号生成完成")
    logger.info("="*70)


if __name__ == '__main__':
    main()
