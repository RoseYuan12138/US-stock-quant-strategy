# Stock Quant - 多策略量化回测系统

S&P 500 多因子量化选股系统。支持多策略切换，双周再平衡。

> **⚠️ 结论：经过严格统计检验，本策略未能产生显著 Alpha。详见下方回测结果。**

## 架构

> 完整 Mermaid 图见 [`architecture.mmd`](architecture.mmd)

```
                    ┌─────────────────┐
                    │  run_backtest.py │  --strategy v7 --start ... --end ...
                    │    (CLI 入口)    │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  backtest/      │
                    │  engine.py      │  通用回测引擎（策略无关）
                    │  Backtester     │  逐日循环 → trailing stop → rebalance → P&L
                    └────────┬────────┘
                             │
              ┌──────────────▼──────────────┐
              │   strategy/base.py          │
              │   StrategyBase (ABC)        │
              │   .on_rebalance() → weights │
              └──────────────┬──────────────┘
                             │
              ┌──────────────▼──────────────┐
              │  strategy/sector_neutral.py │  V7: 14因子 + IC加权 + sector-neutral
              │  SectorNeutralStrategy      │
              │    ├── factors.py           │  14 因子引擎
              │    ├── ic_tracker.py        │  滚动 IC → 动态权重
              │    ├── portfolio.py         │  sector-neutral 组合构建
              │    └── regime.py            │  BULL / CAUTION / BEAR
              └──────────────┬──────────────┘
                             │
              ┌──────────────▼──────────────┐
              │   data/fmp_loader.py        │  FMP parquet 加载器
              │   FMPDataLoader             │  fundamentals, earnings, insider, macro...
              └──────────────┬──────────────┘
                             │
              ┌──────────────▼──────────────┐
              │   fmp-datasource/cache/     │  本地 parquet 缓存
              └─────────────────────────────┘
```

## 项目结构

```
stock-quant/
├── config.py                  # V7Config 配置
├── run_backtest.py            # CLI 入口（--strategy v7/...）
│
├── strategy/                  # 策略层
│   ├── base.py                # StrategyBase 抽象基类
│   ├── sector_neutral.py      # V7 Sector-Neutral 策略
│   ├── factors.py             # 14 因子引擎（sector-neutral z-score）
│   ├── ic_tracker.py          # IC 动态加权
│   ├── portfolio.py           # Sector-neutral 组合构建
│   └── regime.py              # 市场环境过滤（SMA + 利差）
│
├── backtest/
│   └── engine.py              # 通用回测引擎（策略无关）
│
├── data/
│   └── fmp_loader.py          # FMP parquet 数据加载器
│
├── live/                      # 实盘模块（开发中）
├── fmp-datasource/            # FMP 数据下载工具 + parquet 缓存
├── reports/                   # 回测报告输出
└── archive/                   # 历史 V3-V6 代码和文档
```

## 当前策略：V7 Sector-Neutral Multi-Factor

### 因子（14 个，sector-neutral z-scored）

| 类别 | 因子 | 数据来源 |
|------|------|----------|
| **价值** | Earnings Yield, Book Yield, FCF Yield | FMP 季度财报 |
| **质量** | ROE, Gross Margin, Operating Margin | FMP 季度财报 |
| **会计** | Accruals（现金 vs 会计利润差异） | FMP 季度财报 |
| **动量** | 6M 动量, 1M 反转, 12M skip-1M | FMP 日线价格 |
| **盈利** | SUE（标准化意外盈利） | FMP earnings |
| **分析师** | 分析师修正动量 | FMP analyst grades |
| **内部人** | 内部人净买入 | FMP insider trades |
| **政治** | 国会议员净买入 | FMP congressional |

### 关键设计

- **Sector-neutral**：板块内 z-score，每板块选 top N，匹配基准板块权重
- **IC 动态加权**：根据滚动 Information Coefficient 调整因子权重
- **Point-in-time**：使用 filingDate 避免前视偏差
- **双周再平衡**：14 天周期 + 20% trailing stop

### 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| Top N per sector | 2 | 每板块选股数 |
| Max holdings | 25 | 最大持仓数 |
| Max single weight | 8% | 单股上限 |
| Trailing stop | 20% | 止损线 |
| Slippage | 10 bps | 单边滑点 |
| Rebalance | 14 天 | 再平衡周期 |

### Regime 仓位管理

| Regime | 仓位倍数 | 触发条件 |
|--------|---------|---------|
| BULL | 100% | SPY > 200 SMA，正向利差 |
| CAUTION | 70% | 混合信号 |
| BEAR | 40% | SPY < 200 SMA，倒挂利差 |

## 回测结果与结论

### V7 长期回测（2015-01 ~ 2025-12，11年）

| 指标 | V7 | SPY | 判定 |
|------|-----|-----|------|
| **总收益** | +175.80% | +231.95% | ❌ 跑输 SPY |
| **年化收益** | +9.66% | +11.52% | ❌ 跑输 SPY |
| **Alpha（年化）** | **-2.04%** | — | ❌ 负 alpha |
| **Alpha t-stat** | **-0.740** | — | ❌ 不显著（需 >1.96） |
| **Sharpe** | 0.412 | 0.478 | ❌ 低于 SPY |
| **Information Ratio** | -0.224 | — | ❌ 负 |
| **最大回撤** | -32.28% | — | |
| **波动率** | 15.75% | — | |
| **Tracking Error** | 9.13% | — | |
| **交易次数** | 2728 | — | 286 次再平衡 |
| **胜率** | 54.4% | — | |

### Factor IC（选股能力评估）

| 因子 | IC | IC-IR | Hit Rate | 判断 |
|------|-----|-------|----------|------|
| sue | +0.010 | +0.185 | 58% | 最好的因子，但仍然很弱 |
| mom_1m_rev | +0.010 | +0.086 | 51% | |
| mom_6m | +0.009 | +0.058 | 54% | |
| composite | +0.008 | +0.091 | 54% | 综合因子 IC 接近随机 |
| book_yield | -0.012 | -0.241 | 40% | ❌ 价值因子反向 |
| earnings_yield | -0.010 | -0.194 | 43% | ❌ 价值因子反向 |

> 14 个因子中 IC 最高的才 0.01，综合 composite IC 仅 0.008，基本等于随机选股。

### V5/V6 回测（历史版本，已废弃）

V5/V6 曾报告 +18.6% 累计 alpha，但经统计检验：
- Alpha t-stat 仅 **0.24**（远不到 1.96 的显著性门槛）
- 加入 10bps 滑点后 alpha 降至 +0.6%，t-stat 0.07
- 表面上的"alpha"实际来自 **64% 科技股权重**（beta 暴露），不是选股能力

### 最终结论

**本策略不具备统计显著的 Alpha。**

- V5/V6 的超额收益来自科技股行业暴露（2015-2025 科技大牛市），不是真正的选股能力
- V7 做了 sector-neutral 去除行业偏露后，alpha 直接变为负数，暴露了选股因子的无效性
- 14 个公开因子（价值/质量/动量/盈利/内部人/国会交易）的 IC 接近于零
- **直接持有 SPY/VOO 是更好的选择**

这不是代码的问题，而是散户量化的结构性困境：公开因子已被机构充分套利，用公开数据很难获得持续的信息优势。

### 这个项目的价值

虽然策略本身不赚钱，但搭建过程中积累了完整的量化研究框架：
- 统计检验意识（t-stat, IC, IR）— 不被回测曲线欺骗
- 过拟合 / 前视偏差 / survivorship bias 的识别与规避
- Beta 暴露 vs Alpha 的区分
- 完整的因子研究 + sector-neutral 回测系统

> 完整报告：[`reports/v7_latest_report.json`](reports/v7_latest_report.json)
> 历史版本对比：[`archive/old_docs/fmp_vs_yfinance_comparison.md`](archive/old_docs/fmp_vs_yfinance_comparison.md)

## 使用

```bash
# 下载 FMP 数据（需 FMP_API_KEY 环境变量）
cd fmp-datasource && python3 run_all.py

# 默认回测（2015-2025）
python3 run_backtest.py

# 指定时间段
python3 run_backtest.py --start 2025-01-01 --end 2026-03-30

# 自定义参数
python3 run_backtest.py --slippage 15 --top-n 3 --rebalance-days 21
```

## 添加新策略

1. 创建 `strategy/my_strategy.py`，继承 `StrategyBase`
2. 实现 `initialize()`, `on_rebalance()`, `get_regime()`, `get_diagnostics()`
3. 在 `run_backtest.py` 的 `STRATEGIES` dict 中注册
4. `python3 run_backtest.py --strategy my_strat`

详见 `.claude/skills/create-strategy.md`

## 数据源

所有数据来自 [FMP (Financial Modeling Prep)](https://financialmodelingprep.com/) API，本地缓存为 parquet 文件：

- **价格**：日线 OHLCV（拆股复权，不含股息）
- **基本面**：季度财报 + filingDate
- **盈利**：EPS actual vs estimated
- **分析师**：共识评级历史
- **内部人**：SEC Form 4
- **国会**：国会议员交易
- **宏观**：Treasury spread 等
- **成分股**：S&P 500 Point-in-Time 历史成分

## 依赖

```bash
pip3 install pandas numpy pyarrow
```
