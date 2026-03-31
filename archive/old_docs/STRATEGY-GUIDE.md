# 袁翠花炒股系统 — 策略指南

## 策略版本一览

| 版本 | 核心改动 | 回测 Alpha | 状态 |
|------|---------|-----------|------|
| V1 | 技术指标（RSI/MACD/SMA）| 无法跑赢 SPY | 已废弃 |
| V2 | 基本面选股 + 动量过滤 | +2-3% | 已废弃 |
| V3 | V2 + SPY SMA Regime Filter + Trailing Stop | +3.3% | 基线版本 |
| V3.1 | V3 + Earnings Surprise (PEAD) | +3.5% | 已合并到 V5 |
| V4 | V3 + 跨资产 Regime Filter（收益率曲线/VIX/信用利差）| +3.9% | 已合并到 V5 |
| V5 | V4 + Short Interest 过滤 + Insider Trading 加分 | +4.0% | 当前主力 |
| V6 | V5 + 新闻情绪因子（关键词匹配）| +4.8% | 实验中 |

**结论：V3→V5 的核心三因子（基本面 + 动量 + Regime）贡献了 95% 的 Alpha。V5 之后加的因子边际效用很小。**

---

## 当前主力策略 (V5) 详解

### 选股层 — 每月执行一次

| 因子 | 权重/作用 | 数据来源 |
|------|----------|---------|
| 基本面评分 | 占综合分 50% | 历史季度财报（PE/PB/ROE/毛利率/营收增长） |
| 动量评分 | 占综合分 30% | 6 个月价格动量 + 200 日均线 |
| 分析师评分 | 占综合分 20% | yfinance 分析师目标价/评级 |
| Earnings Surprise | 调整基本面分（80%原分 + 20%惊喜分）| yfinance 历史 EPS |
| Short Interest | > 15% 直接排除 | yfinance shortPercentOfFloat |
| Insider Trading | 集群买入加 +1~8 分 | yfinance insider_transactions |

**选股规则：** 综合分 ≥ 55 且动量 ≥ 40，选 Top 10。

### 仓位层

| 机制 | 规则 |
|------|------|
| SPY 底仓 | 固定 20% |
| 个股等权 | 剩余 80% 平分 |
| 单只上限 | 不超过 12% |
| Regime Filter | 跨资产信号（SPY 均线 55% + 收益率曲线 15% + VIX 15% + 信用利差 15%）|
| BULL (≥55) | 满仓 |
| CAUTION (25-55) | 半仓 |
| BEAR (<25) | 25% 仓位 |

### 风控层

| 机制 | 规则 |
|------|------|
| Trailing Stop | 单只股票从最高点回撤 25% 卖出 |
| 月度再平衡 | 每月初重新选股，卖出不在新名单的 |

---

## 三种配置档位

所有档位用的是**同一套策略框架**，只是参数松紧不同：

| 参数 | Standard | Aggressive | Conservative |
|------|----------|------------|--------------|
| 持仓数量 | 10 只 | 15 只 | 8 只 |
| 综合分门槛 | ≥ 55 | ≥ 45 | ≥ 60 |
| 动量门槛 | ≥ 40 | ≥ 30 | ≥ 45 |
| 基本面权重 | 50% | 40% | 60% |
| 动量权重 | 30% | 40% | 20% |
| SPY 底仓 | 20% | 10% | 25% |
| 单只上限 | 12% | 10% | 12% |
| Trailing Stop | 25% | 30% | 20% |

### 怎么选

- **Standard** — 默认选择，攻守平衡
- **Aggressive** — 更多股票、更低门槛、更少 SPY 底仓、止损更宽。牛市赚更多，熊市亏更多。适合风险承受能力高的人
- **Conservative** — 更少股票、更高门槛、更多 SPY 底仓、止损更紧。回撤小但牛市少赚。适合求稳的人

### 三档回测对比 (2018-2020, V6)

| 配置 | 收益 | Alpha | 夏普 | 最大回撤 | 胜率 | 跑赢 SPY |
|------|------|-------|------|---------|------|---------|
| Standard | +33.7% | -3.6% | 0.46 | -28.1% | 61% | N |
| Aggressive | +52.2% | +1.3% | 0.63 | -29.5% | 62% | Y |
| Conservative | +32.9% | -3.8% | 0.48 | -23.7% | 66% | N |
| SPY | +47.1% | — | 0.59 | -33.7% | — | — |

---

## 回测结果 (2018-2025)

```
策略总收益:  +106.3%
SPY 总收益:  +87.7%
Alpha:       +18.6% (年化 ~+2.3%)
跑赢年份:    4/8 (50%)
```

### 逐年表现

| 年份 | 策略 | SPY | Alpha | 回撤 | 市场 |
|------|------|-----|-------|------|------|
| 2018 | +4.0% | -5.2% | +9.2% | -23.8% | 加息+贸易战 |
| 2019 | +16.4% | +31.1% | -14.6% | -11.0% | 降息反弹 |
| 2020 | +6.8% | +17.2% | -10.5% | -27.7% | COVID |
| 2021 | +36.2% | +30.5% | +5.7% | -8.9% | 大牛市 |
| 2022 | -25.3% | -18.6% | -6.7% | -26.3% | 加息熊市 |
| 2023 | +44.7% | +26.7% | +18.0% | -8.0% | AI 牛市 |
| 2024 | +30.8% | +25.6% | +5.3% | -14.7% | 大选年 |
| 2025 | +4.3% | +18.9% | -14.6% | -11.4% | 关税震荡 |

### 策略擅长什么

- 加息/贸易战等渐进式下跌（2018: +9.2% Alpha）
- AI/科技牛市（2023: +18.0% Alpha）
- 正常牛市（2021/2024: +5% Alpha）

### 策略不擅长什么

- V 型反弹：暴跌后快速反弹（2020 Q2 踏空 -16%）
- 全面牛市：所有股票都涨时动量集中于少数行业（2019: -14.6%）
- 长期熊市：BEAR 模式下剩余仓位仍是高 beta（2022: -6.7%）

---

## 已知问题和待优化

### 诊断出的 3 个核心问题

1. **Regime 退出太慢** — 进入 BEAR 和退出 BEAR 都用同一个 composite_score，反弹踏空
   - 修复方案：不对称 Regime（快出慢进，价格驱动回仓）— **已确认要做**

2. **BEAR 模式无真正防御** — 减仓后剩余持仓还是高 beta 科技股
   - 修复方案：BEAR 时加大 SPY 底仓到 50%（简单有效，不过拟合）

3. **行业过度集中** — 科技占 64%，等于对赌行业轮动
   - 修复方案：加行业上限 40%（结构性约束，不过拟合）

### 过拟合风险评估

每一版策略都是看着 2018-2025 回测结果调的，有过拟合风险。核心 Alpha 来自三个通用因子（基本面 + 动量 + Regime），后续加的因子（Insider/SI/新闻）贡献极小。

**建议：停止加因子，转向 Paper Trading 验证。**

---

## 可用命令

### 回测

```bash
# V3 基线回测 (2018-2025)
python3 run_portfolio_validation_v3.py

# V6 新闻因子回测 (2018-2020，新闻数据覆盖范围)
python3 run_portfolio_validation_v6.py

# 样本外测试 (2016-2018)
python3 run_oos_test.py
```

### 实盘信号

```bash
# 每日信号生成
python3 run_daily_signals.py

# Paper Trading（记录信号 → 月底对比）
python3 run_paper_trading.py signal   # 月初：记录本月信号
python3 run_paper_trading.py review   # 月底：回顾表现
```

### 数据

```bash
# 下载 S&P 100 新闻数据（HuggingFace，免费）
python3 run_download_fnspid.py
```

---

## 文件结构

```
stock-quant/
├── strategy/
│   ├── momentum.py              # 动量评分
│   ├── regime_filter.py         # 跨资产 Regime Filter (V4)
│   ├── portfolio_strategy.py    # 组合选股逻辑
│   ├── earnings_surprise.py     # Earnings Surprise (V3.1)
│   └── insider_signal.py        # Insider Trading 信号 (V5)
├── backtest/
│   └── portfolio_backtester.py  # 组合回测引擎
├── data/
│   ├── data_fetcher.py          # 价格数据（yfinance）
│   ├── fundamental_fetcher.py   # 基本面数据
│   ├── historical_fundamentals.py # 历史季度财报
│   └── historical_news.py       # 新闻情绪（HuggingFace 数据集）
├── run_daily_signals.py         # 实盘每日信号
├── run_paper_trading.py         # Paper Trading
├── run_portfolio_validation_v3.py  # V3 回测
├── run_portfolio_validation_v6.py  # V6 回测
├── run_oos_test.py              # 样本外测试
└── reports/                     # 回测报告输出
```

---

## 下一步路线图

1. **不对称 Regime** — 快出慢进，价格驱动回仓（已确认）
2. **行业上限 40%** — 防止科技过度集中（已确认）
3. **BEAR 加大 SPY 底仓** — 不确定的时候买指数（已确认）
4. **Paper Trading 3-6 个月** — 真正的样本外验证
5. **实盘 Haiku 新闻情绪** — 每天几分钱，替代关键词匹配
6. **Telegram 推送** — 每日信号自动发送

**原则：不再加新因子，专注验证和风控。**
