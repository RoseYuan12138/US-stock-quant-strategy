"""
回测结果可视化
生成图表保存为 PNG
"""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # 使用非交互式后端
import matplotlib.pyplot as plt
from datetime import datetime
from pathlib import Path

class BacktestVisualizer:
    """回测结果可视化"""
    
    def __init__(self, output_dir='./reports'):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def plot_backtest_result(self, ticker, result_df, report, strategy_name):
        """
        绘制回测结果
        
        Args:
            ticker: 股票代码
            result_df: 回测结果 DataFrame
            report: 回测报告字典
            strategy_name: 策略名称
        
        Returns:
            str: 保存的图表文件路径
        """
        fig, axes = plt.subplots(3, 1, figsize=(12, 10))
        fig.suptitle(f'{ticker} - {strategy_name} 回测结果', fontsize=14, fontweight='bold')
        
        # 第一子图：投资组合价值
        ax1 = axes[0]
        ax1.plot(result_df.index, result_df['Portfolio_Value'], 'b-', linewidth=2, label='Portfolio Value')
        ax1.axhline(y=report['initial_value'], color='r', linestyle='--', label='Initial Capital')
        ax1.set_ylabel('Portfolio Value ($)', fontsize=10)
        ax1.set_title('Portfolio Value Over Time', fontsize=11)
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))
        
        # 第二子图：收益曲线
        ax2 = axes[1]
        returns = (result_df['Portfolio_Value'] / report['initial_value'] - 1) * 100
        ax2.fill_between(result_df.index, returns, 0, alpha=0.3, color='g', label='Returns')
        ax2.plot(result_df.index, returns, 'g-', linewidth=2)
        ax2.axhline(y=0, color='k', linestyle='-', linewidth=0.5)
        ax2.set_ylabel('Return (%)', fontsize=10)
        ax2.set_title('Cumulative Return', fontsize=11)
        ax2.legend()
        ax2.grid(True, alpha=0.3)
        
        # 第三子图：价格和移动平均线
        ax3 = axes[2]
        ax3.plot(result_df.index, result_df['Close'], 'b-', linewidth=1.5, label='Close Price')
        if 'SMA_short' in result_df.columns:
            ax3.plot(result_df.index, result_df['SMA_short'], 'r--', linewidth=1, alpha=0.7, label='SMA 20')
        if 'SMA_long' in result_df.columns:
            ax3.plot(result_df.index, result_df['SMA_long'], 'orange', linestyle='--', linewidth=1, alpha=0.7, label='SMA 50')
        ax3.set_ylabel('Price ($)', fontsize=10)
        ax3.set_xlabel('Date', fontsize=10)
        ax3.set_title('Price with Moving Averages', fontsize=11)
        ax3.legend()
        ax3.grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        # 保存图表
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'{ticker}_{strategy_name}_{timestamp}.png'
        filepath = self.output_dir / filename
        
        plt.savefig(filepath, dpi=100, bbox_inches='tight')
        plt.close()
        
        return str(filepath)
    
    def plot_strategy_comparison(self, comparison_df):
        """
        绘制策略对比
        
        Args:
            comparison_df: 策略对比 DataFrame
        
        Returns:
            str: 保存的图表文件路径
        """
        fig, axes = plt.subplots(2, 2, figsize=(12, 8))
        fig.suptitle('Strategy Comparison', fontsize=14, fontweight='bold')
        
        # 收益率对比
        ax1 = axes[0, 0]
        colors = ['green' if x > 0 else 'red' for x in comparison_df['Total Return %']]
        ax1.barh(comparison_df['Strategy'], comparison_df['Total Return %'], color=colors)
        ax1.set_xlabel('Total Return (%)', fontsize=10)
        ax1.set_title('Returns Comparison', fontsize=11)
        ax1.grid(True, alpha=0.3, axis='x')
        
        # 夏普比率
        ax2 = axes[0, 1]
        colors = ['green' if x > 0 else 'red' for x in comparison_df['Sharpe Ratio']]
        ax2.barh(comparison_df['Strategy'], comparison_df['Sharpe Ratio'], color=colors)
        ax2.set_xlabel('Sharpe Ratio', fontsize=10)
        ax2.set_title('Risk-Adjusted Returns', fontsize=11)
        ax2.grid(True, alpha=0.3, axis='x')
        
        # 最大回撤
        ax3 = axes[1, 0]
        ax3.barh(comparison_df['Strategy'], comparison_df['Max Drawdown %'], color='orange')
        ax3.set_xlabel('Max Drawdown (%)', fontsize=10)
        ax3.set_title('Maximum Drawdown', fontsize=11)
        ax3.grid(True, alpha=0.3, axis='x')
        
        # 胜率
        ax4 = axes[1, 1]
        ax4.barh(comparison_df['Strategy'], comparison_df['Win Rate %'], color='blue')
        ax4.set_xlabel('Win Rate (%)', fontsize=10)
        ax4.set_title('Win Rate', fontsize=11)
        ax4.grid(True, alpha=0.3, axis='x')
        
        plt.tight_layout()
        
        # 保存图表
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'strategy_comparison_{timestamp}.png'
        filepath = self.output_dir / filename
        
        plt.savefig(filepath, dpi=100, bbox_inches='tight')
        plt.close()
        
        return str(filepath)
    
    def generate_summary_report(self, ticker, report, trades=None):
        """
        生成总结报告（文本格式）
        
        Args:
            ticker: 股票代码
            report: 回测报告字典
            trades: 交易列表
        
        Returns:
            str: 报告文本
        """
        lines = [
            "=" * 70,
            f"回测总结报告 - {ticker}",
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "=" * 70,
            "",
            "【性能指标】",
            f"初始资金: ${report['initial_value']:,.2f}",
            f"最终资金: ${report['final_value']:,.2f}",
            f"总收益率: {report['total_return_pct']:+.2f}%",
            f"最大回撤: {report['max_drawdown']*100:.2f}%",
            f"夏普比率: {report['sharpe_ratio']:.2f}",
            "",
            "【交易统计】",
            f"总交易数: {report['total_trades']}",
            f"胜率: {report['win_rate']:.1f}%",
            f"平均赢利: ${report['avg_win']:,.2f}",
            f"平均亏损: ${report['avg_loss']:,.2f}",
            f"总佣金: ${report['total_commissions']:,.2f}",
            "",
        ]
        
        if trades:
            lines.extend([
                "【交易列表】(最近10笔)",
                "-" * 70,
            ])
            for trade in trades[-10:]:
                lines.append(
                    f"{trade['date']} | {trade['action']:4} | "
                    f"${trade['price']:7.2f} | {trade['shares']:5.2f} 股 | "
                    f"${trade['value']:8.2f}"
                )
            lines.append("")
        
        lines.append("=" * 70)
        
        return "\n".join(lines)


if __name__ == "__main__":
    # 测试
    print("Visualizer 模块已加载")
