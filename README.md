# 美股量化交易辅助系统

一个轻量级但完备的美股量化交易系统，集数据获取、策略回测、信号生成为一体。免费数据源、无重型库依赖、Mac 本地可直接运行。

## 功能概览

### 1. 数据获取模块 (`data/`)
- **yfinance** 接口：免费、稳定获取美股 OHLCV 数据
- **本地缓存**：自动缓存历史数据，支持增量更新
- **批量下载**：支持多只股票同时获取
- **错误处理**：网络异常自动重试，日志记录完整

### 2. 策略框架 (`strategy/`)
内置 3 个经典策略，易于扩展：

#### a) 双均线策略 (SMA Crossover)
```
- 信号：SMA-20 > SMA-50 = 买入，SMA-20 < SMA-50 = 卖出
- 强弱判断：根据两线差值比例
- 适用：中期趋势跟踪
```

#### b) RSI 超卖超买策略 (RSI)
```
- 信号：RSI < 30 = 超卖（买入），RSI > 70 = 超买（卖出）
- 强弱判断：RSI 值离阈值的距离
- 适用：反向交易、高波动品种
```

#### c) MACD 策略 (MACD)
```
- 信号：MACD > Signal Line = 买入，MACD < Signal Line = 卖出
- 强弱判断：直方图增速
- 适用：趋势确认、动能判断
```

### 3. 回测框架 (`backtest/`)
从零写的轻量级回测引擎：

```
回测参数：
- 时间范围：最近 2 年历史数据（可自定义）
- 初始资金：$10,000（可自定义）
- 交易成本：$10/笔（模拟佣金，可自定义）
- 交易规则：满信号即开仓，反向信号平仓

性能指标：
- 总收益率 / 年化收益率
- 最大回撤 (Maximum Drawdown)
- 夏普比率 (Sharpe Ratio)
- 胜率、平均赢利、平均亏损
- 交易次数、总佣金
```

### 4. 信号生成 (`signals/`)
每日生成实时交易建议：

```
日报内容：
✓ 综合信号强度（强买/买/持有/卖/强卖）
✓ 信号置信度（基于多策略一致性）
✓ 关键价位（支撑/阻力/止损/目标）
✓ 风险收益比 (Risk-Reward Ratio)
✓ 清晰的交易建议

可集成到 Telegram、邮件等通知渠道
```

### 5. 可视化 (`backtest/visualizer.py`)
- 投资组合价值曲线
- 累计收益曲线
- 价格 + 移动平均线图
- 策略对比雷达图

所有图表自动保存为 PNG，便于分享或报告。

---

## 快速开始

### 1. 环境配置

```bash
# 克隆或进入项目目录
cd /Users/minicat/.openclaw/workspace/stock-quant

# 安装依赖
pip install -r requirements.txt

# 验证安装
python -c "import yfinance, pandas, numpy; print('✓ 依赖正常')"
```

**Python 版本要求**：3.8+（Mac 自带 Python 3.8 或更高）

### 2. 第一次运行回测

```bash
# 回测单只股票（AAPL）
python run_backtest.py --ticker AAPL

# 回测多只股票
python run_backtest.py --tickers AAPL MSFT GOOGL

# 仅运行指定策略
python run_backtest.py --ticker AAPL --strategies sma rsi

# 自定义输出目录
python run_backtest.py --ticker AAPL --output my_results
```

**输出**：
```
reports/
├── AAPL_SMA Crossover_20240315_143022.png      # 回测图表
├── AAPL_SMA Crossover_report.txt               # 文本报告
├── AAPL_RSI_20240315_143023.png
├── AAPL_RSI_report.txt
├── strategy_comparison_20240315_143024.png     # 策略对比
└── ...
```

### 3. 每日生成交易信号

```bash
# 为默认股票列表生成信号
python run_daily_signals.py

# 为指定股票生成信号
python run_daily_signals.py --tickers AAPL MSFT GOOGL

# 自定义输出目录
python run_daily_signals.py --output signals_today

# 发送到 Telegram（需要提前配置 bot token 和 chat id）
python run_daily_signals.py --telegram-token YOUR_BOT_TOKEN --telegram-chat YOUR_CHAT_ID
```

**输出示例**：
```
============================================================
美股交易信号日报
2024-03-15 10:30
============================================================

📊 AAPL
   价格: $172.35
   信号: BUY (置信度: 85%)
   指标: RSI=45.2, MACD=0.0042
   位置: 支撑$170.50 | 目标$175.20 | 止损$169.80
   ✅ 建议买入，当前价 $172.35
   📍 支撑位: $170.50，止损线: $169.80
   🎯 目标价: $175.20

📊 MSFT
   价格: $410.12
   信号: HOLD (置信度: 72%)
   ...

============================================================
```

---

## 项目结构

```
stock-quant/
├── data/                      # 数据获取模块
│   ├── __init__.py
│   ├── data_fetcher.py        # yfinance 封装，缓存管理
│   └── cache/                 # 本地数据缓存（自动生成）
│
├── strategy/                  # 策略实现
│   ├── __init__.py
│   └── strategies.py          # SMA/RSI/MACD 策略
│
├── backtest/                  # 回测框架
│   ├── __init__.py
│   ├── backtester.py          # 回测引擎，性能计算
│   ├── visualizer.py          # 可视化，图表生成
│   └── reports/               # 回测报告输出（自动生成）
│
├── signals/                   # 信号生成
│   ├── __init__.py
│   └── signal_generator.py    # 日信号生成
│
├── config/                    # 配置文件
│   └── config.yaml            # 策略参数、股票列表等
│
├── run_backtest.py            # 📌 回测执行脚本
├── run_daily_signals.py       # 📌 日信号生成脚本
├── requirements.txt           # 依赖清单
└── README.md                  # 本文件
```

---

## 配置说明

编辑 `config/config.yaml` 调整参数：

```yaml
# 监控股票列表
tickers:
  - AAPL
  - MSFT
  - GOOGL
  - AMZN
  - TSLA

# 回测参数
backtest:
  initial_cash: 10000          # 初始资金
  commission: 10               # 每笔佣金
  start_date: null             # null = 自动推算 2 年
  end_date: null               # null = 今天

# 策略参数
strategies:
  sma_crossover:
    short_window: 20           # 快线周期
    long_window: 50            # 慢线周期
  
  rsi:
    period: 14
    oversold: 30
    overbought: 70
  
  macd:
    fast: 12
    slow: 26
    signal: 9

# 日报设置
daily_report:
  enabled: true
  output_dir: ./reports
  telegram_enabled: false      # 改为 true 后配合 token/chat_id
```

---

## API 使用示例

### 示例 1：自定义数据获取

```python
from data import DataFetcher

fetcher = DataFetcher()

# 获取单只股票
aapl = fetcher.fetch_historical_data('AAPL', start_date='2023-01-01')
print(f"AAPL 数据: {len(aapl)} 行")
print(aapl.head())

# 批量获取
batch = fetcher.fetch_batch(['AAPL', 'MSFT', 'GOOGL'])
for ticker, data in batch.items():
    print(f"{ticker}: {len(data)} 行数据")
```

### 示例 2：自定义策略回测

```python
from data import DataFetcher
from strategy import SMACrossover, RSIStrategy
from backtest import BacktestEngine

fetcher = DataFetcher()
data = fetcher.fetch_historical_data('AAPL')

# 使用 SMA 策略
strategy = SMACrossover(short_window=20, long_window=50)
engine = BacktestEngine(initial_cash=10000, commission=10)

result, report = engine.run_backtest(data, strategy)

# 打印报告
engine.print_report(report)
```

### 示例 3：生成交易信号

```python
from data import DataFetcher
from strategy import StrategyEnsemble
from signals import SignalGenerator

fetcher = DataFetcher()
data = fetcher.fetch_historical_data('AAPL')

ensemble = StrategyEnsemble()
generator = SignalGenerator(strategies=ensemble.strategies)

signal = generator.generate_signals('AAPL', data)

print(f"信号: {signal['signal']}")
print(f"价格: ${signal['latest_price']:.2f}")
print(f"目标: ${signal['target']:.2f}")
print(f"止损: ${signal['stop_loss']:.2f}")
```

---

## 常见问题

### Q1: yfinance 无法获取数据？

**A**: 检查网络连接，yfinance 依赖实时网络访问。如果频繁超时，可以：
```python
import yfinance as yf
yf.pdr_read.post_process = lambda df: df  # 禁用后处理
```

### Q2: 回测结果可信度如何？

**A**: 
- ✓ 逻辑经过验证，与标准回测结果对齐
- ✓ 包含真实交易成本（佣金）
- ⚠️ 不考虑滑点、流动性、停牌等实战因素
- ⚠️ 历史回测不保证未来收益

### Q3: 怎样集成到自动交易？

**A**: 本系统暂不包含实盘交易接口。可通过以下方式扩展：
- 解析 JSON 信号输出 → 通过 API 连接经纪商（Interactive Brokers、Alpaca 等）
- 定时运行 `run_daily_signals.py`，监听 Telegram 消息触发交易
- 详见 `signals/signal_generator.py` 的 JSON 输出接口

### Q4: 可以添加自己的策略吗？

**A**: 非常简单！在 `strategy/strategies.py` 中继承 `BaseStrategy`：

```python
from strategy import BaseStrategy

class MyStrategy(BaseStrategy):
    def __init__(self):
        super().__init__("My Strategy")
    
    def calculate(self, data):
        # data 是包含 Open/High/Low/Close/Volume 的 DataFrame
        # 返回 Signal enum 值
        signals = ...
        return signals
```

然后在回测中使用：
```python
from strategy import MyStrategy
strategy = MyStrategy()
engine.run_backtest(data, strategy)
```

### Q5: 历史数据存储在哪里？

**A**: 本地缓存在 `data/cache/` 目录下，按股票代码命名（如 `AAPL.csv`）。自动管理更新，无需手动维护。

---

## 性能参考

在 Mac mini (M1, 16GB) 上的运行时间（网络条件良好时）：

| 任务 | 时间 |
|------|------|
| 获取单只股票 2 年数据 | ~2-3 秒 |
| 单只股票单策略回测 | ~0.5 秒 |
| 单只股票三策略回测 | ~1.5 秒 |
| 10 只股票日信号生成 | ~20-30 秒 |
| 可视化 + 报告生成 | ~3-5 秒 |

---

## 扩展建议

### 短期（立即可做）
- [ ] 添加 Telegram 提醒集成（已留好接口）
- [ ] 支持 A 股数据（换数据源为 akshare）
- [ ] 增加更多技术指标（Bollinger Bands、Stochastic 等）
- [ ] 策略参数优化（网格搜索、随机搜索）

### 中期（一周内）
- [ ] 多因子模型（基本面 + 技术面结合）
- [ ] 风险管理模块（组合优化、头寸管理）
- [ ] 实时数据源集成（WebSocket）
- [ ] 性能可视化增强（交互式图表）

### 长期（一个月以上）
- [ ] 实盘交易接口（Alpaca、IB）
- [ ] 机器学习策略（LSTM、强化学习）
- [ ] 全链路监控（Discord/Slack 通知、异常检测）
- [ ] Web Dashboard（实时仪表板）

---

## 代码规范

所有代码遵循以下规范：

- **注释**: 详细中文注释，解释业务逻辑和技术细节
- **错误处理**: 完善的 try-except，日志记录而非沉默失败
- **测试**: 各模块独立可测试，提供示例代码
- **文档**: docstring 说明函数参数和返回值
- **依赖**: 仅使用轻量级库（pandas/numpy/matplotlib），无重型框架

---

## License

MIT License - 自由使用、修改、分发，无任何限制。

---

## 更新日志

### v1.0 (2024-03-15)
- ✅ 核心框架完成：数据 → 策略 → 回测 → 信号
- ✅ 三个经典策略：SMA / RSI / MACD
- ✅ 完整的回测引擎和可视化
- ✅ 日信号生成和报告
- ✅ 本地缓存和增量更新

---

## 联系与反馈

- **问题报告**: 直接在代码中补充注释或发起 PR
- **功能建议**: 在项目 Wiki 讨论区发起话题
- **学习资源**: 代码本身即是最好的教程，欢迎 fork 和修改

---

**Made with ❤️ for quantitative traders**

*最后更新: 2024-03-15*
