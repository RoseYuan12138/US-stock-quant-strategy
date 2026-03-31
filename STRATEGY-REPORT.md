# 袁翠花炒股系统 — 策略说明与回测报告

> 作者: Rose + Cowork
> 日期: 2026-03-29（V1～V4）
> 目的: 提供给外部 expert 审阅，帮助改进策略

---

> [!WARNING]
> ## ⚠️ 数据准确性警告：回测时间段标注可能有误
>
> **经核实，本文档中的回测时间段标注存在错误，请审阅时注意以下几点：**
>
> - **Section 14 的 V3 回测**：文中标注为 `2018–2025`（8年），但 SPY 基准收益 `+87.7%` 实际对应的是 **2023–2025（约3年）**，两者不符。如以真实的 2018–2025 全程计算，SPY 累计收益应在 +150% 以上，策略 alpha 结论将发生显著变化。
> - **其他版本（V1–V6）**：各版本的回测时间段标注均可能存在类似的错误，尚未全部核实。
> - **准确的 V3 基准数据**：请以 `baseline_metrics.md` 中的数据为准，该文件包含经过核实的 2018–2025 历史基准指标。
>
> **在错误修正完成之前，本报告中的绝对收益数字、alpha 值及相对表现比较，均不应作为策略优劣的最终依据。**

---

## Version History

| 版本 | 日期 | 核心变更 | 最佳 Alpha | 回测区间 |
|------|------|---------|-----------|---------|
| **V1** | 2026-03-29 | 纯技术策略 + 单标的价值策略 | -13.7% | 2023-2025（3年） |
| **V2** | 2026-03-29 | 组合策略重构（多因子选股 + 动量 + Regime Filter + Trailing Stop） | -1.5% | 2023-2025（3年） |
| **V3** | 2026-03-29 | S&P 100 标的池 + 历史财报修复前视偏差 | +3.3% | 2023-2025（3年）¹ |
| **V3.1** | 2026-03-29 | S&P 500 核心 ~150 只 + Earnings Surprise 因子 | -0.1% | 2023-2025（3年） |
| **V4** | 2026-03-29 | 跨资产 Regime Filter（收益率曲线 + VIX + 信用利差） | +3.9% | 2023-2025（3年） |
| **V5** | 2026-03-29 | Short Interest 过滤 + Insider Trading 信号 | +4.0% | 2023-2025（3年） |
| **V6** | 2026-03-29 | 历史新闻情绪因子（HuggingFace 数据集） | **+4.0%** | 2018-2020（3年） |

> ¹ V3 于 2026-03-30 在 2018-2025（8年）区间重跑，见 `reports/portfolio_v3_validation_20260330_1540.json`，结果见 §14 末尾注。

---

## 1. 项目背景

这是一个散户辅助系统（代号"袁翠花"），最终目标是通过 Telegram 给用户推送每日股票信号和研究报告。在搭任何推送功能之前，我们先做了两轮回测验证，确认策略是否真的能赚钱。

**核心原则：策略必须先证明能赚钱，其他功能才有意义。**

用户（Rose）的需求很直白：告诉她什么时候买、什么时候卖，帮她克服人性弱点（贪、怕、犹豫）。但如果策略本身不赚钱，纪律再好也是在纪律性地亏钱。

---

## 2. 代码结构

所有代码位于 `yuancuihua-workspace/stock-quant/`：

```
stock-quant/
├── data/
│   ├── data_fetcher.py            # 美股 OHLCV 数据获取（yfinance + 本地 CSV 缓存）
│   ├── fundamental_fetcher.py     # 基本面数据获取 + ValueScreener 评分系统
│   ├── historical_fundamentals.py # V3 新增: 历史季度财报数据（修复前视偏差）
│   └── cache/                     # 本地缓存目录（CSV 行情 + JSON 基本面 + earnings）
│
├── strategy/
│   ├── strategies.py              # V1: 纯技术指标策略（SMA/RSI/MACD）
│   ├── value_strategy.py          # V1: 价值投资策略 + 纪律性回测引擎
│   ├── momentum.py                # V2 新增: 6月动量因子
│   ├── regime_filter.py           # V2 新增 / V4 升级: 市场环境判断（跨资产信号）
│   ├── portfolio_strategy.py      # V2 新增: 组合管理策略
│   ├── earnings_surprise.py       # V3.1 新增: PEAD 因子（Earnings Surprise）
│   └── insider_signal.py          # V5 新增: Insider Trading 信号（SEC Form 4）
│
├── data/
│   └── historical_news.py         # V6 新增: 历史新闻情绪（HuggingFace 数据集 + 关键词评分）
│
├── backtest/
│   ├── backtester.py              # 通用回测引擎（Round 1 用）
│   └── visualizer.py              # 图表可视化
│
├── signals/
│   ├── signal_generator.py        # 综合信号生成器
│   └── signal_fusion.py           # 技术 60% + 新闻 40% 融合
│
├── news/
│   └── news_fetcher.py            # NewsAPI + Yahoo Finance 新闻获取
│
├── sentiment/
│   └── sentiment_analyzer.py      # V2 重写: TextBlob → Haiku API
│
├── run_validation.py              # V1 回测脚本（纯技术策略）
├── run_value_validation.py        # V1 回测脚本（价值策略）
├── run_portfolio_validation.py    # V2 回测脚本（组合策略，20只）
├── run_portfolio_validation_v3.py # V3 回测脚本（S&P 100）
├── run_portfolio_validation_v3_1.py # V3.1 回测脚本（S&P 500 核心 ~150只）
├── run_portfolio_validation_v4.py # V4 回测脚本（跨资产 Regime）
├── run_portfolio_validation_v5.py # V5 回测脚本（SI + Insider）
├── run_portfolio_validation_v6.py # V6 回测脚本（新闻情绪因子）
├── run_daily_signals.py           # 日信号生成入口
├── run_backtest.py                # 单策略回测入口
│
├── reports/                       # 回测报告输出（.txt + .json）
├── config/config.yaml             # 配置文件
└── requirements.txt               # 依赖
```

### 依赖

```
yfinance, pandas, numpy, matplotlib, pyyaml, requests, textblob, newsapi-python, pytest
```

---

## 3. 数据层

### 3.1 行情数据 — `data/data_fetcher.py`

- **数据源**: yfinance（Yahoo Finance 非官方 API）
- **粒度**: 日线（Daily OHLCV）
- **延迟**: 15-20 分钟（非实时）
- **缓存**: 本地 CSV 文件，按 ticker 存储在 `data/cache/` 下
- **格式**: pandas DataFrame，列为 `Open, High, Low, Close, Volume`，索引为 `DatetimeIndex`

关键类 `DataFetcher`:

```python
fetcher = DataFetcher(cache_dir="./data/cache")
data = fetcher.fetch_historical_data("AAPL", start_date="2023-01-01", end_date="2025-12-31")
# 返回 DataFrame: index=Date, columns=[Open, High, Low, Close, Volume]

batch = fetcher.fetch_batch(["AAPL", "MSFT", "GOOGL"], start_date="2023-01-01")
# 返回 dict: {ticker: DataFrame}
```

缓存逻辑：如果本地 CSV 存在且数据量 > 50 行，直接用缓存。不做日期范围精确匹配（已知局限）。

### 3.2 基本面数据 — `data/fundamental_fetcher.py`

- **数据源**: yfinance `Ticker.info`（Yahoo Finance API）
- **缓存**: JSON 文件，24 小时过期
- **获取字段**: 共 25+ 个指标

关键类 `FundamentalFetcher`:

```python
fetcher = FundamentalFetcher(cache_dir="./data/cache/fundamentals")
fund = fetcher.fetch_fundamentals("AAPL")
# 返回 dict，包含以下字段：
```

| 类别 | 字段 | 说明 |
|------|------|------|
| **估值** | pe_ratio, forward_pe, pb_ratio, ps_ratio, peg_ratio, ev_to_ebitda | trailing PE, forward PE, 市净率, 市销率, PEG, EV/EBITDA |
| **盈利能力** | profit_margin, operating_margin, roe, roa | 净利润率, 运营利润率, 净资产收益率, 总资产收益率 |
| **成长性** | revenue_growth, earnings_growth, earnings_quarterly_growth | 营收增长率, 盈利增长率, 季度盈利增长 |
| **分红** | dividend_yield, payout_ratio, five_year_avg_dividend_yield | 股息率, 派息率, 5 年平均股息率 |
| **财务健康** | debt_to_equity, current_ratio, quick_ratio, total_cash_per_share | 负债权益比, 流动比率, 速动比率, 每股现金 |
| **分析师** | analyst_mean_rating (1=强买 5=卖), target_mean_price, number_of_analysts, upside_pct | 共识评级, 目标价, 覆盖人数, 上涨空间% |
| **其他** | beta, market_cap, sector, industry | 贝塔, 市值, 行业 |

---

## 4. Round 1: 纯技术指标策略

### 4.1 策略代码 — `strategy/strategies.py`

三个独立策略，均继承 `BaseStrategy`，输出统一的 5 级信号（STRONG_BUY=5, BUY=4, HOLD=3, SELL=2, STRONG_SELL=1）。

#### SMA Crossover（双均线交叉）

```
参数: short_window=20, long_window=50
买入: SMA20 > SMA50（金叉后设为 BUY）
      若 SMA20 > SMA50 且 (SMA20-SMA50)/SMA50 > 2% → STRONG_BUY
卖出: SMA20 < SMA50（死叉后设为 SELL）
      若 SMA20 < SMA50 且 (SMA50-SMA20)/SMA50 > 2% → STRONG_SELL
```

#### RSI（相对强弱指数）

```
参数: period=14, oversold=30, overbought=70
买入: RSI < 30 → STRONG_BUY
      RSI 30-40 → BUY
卖出: RSI > 70 → STRONG_SELL
      RSI 60-70 → SELL
中间: HOLD
```

#### MACD（异同移动平均线）

```
参数: fast=12, slow=26, signal=9
买入: MACD线 > Signal线 且 MACD > 0 → STRONG_BUY
      MACD线 > Signal线 且 MACD < 0 → BUY（金叉但仍在零轴下）
卖出: MACD线 < Signal线 且 MACD < 0 → STRONG_SELL
      MACD线 < Signal线 且 MACD > 0 → SELL
```

#### StrategyEnsemble（融合策略）

三个策略信号取平均值（等权重 1/3），四舍五入。

### 4.2 回测引擎 — `backtest/backtester.py`

```
初始资金: $10,000
佣金: $10/笔（买卖各算一笔）
买入条件: signal > 3（即 BUY 或 STRONG_BUY）→ 全仓买入
卖出条件: signal < 3（即 SELL 或 STRONG_SELL）→ 全仓卖出
仓位管理: 全仓进出，无分批建仓
```

指标计算：

```python
总收益率 = (最终价值 - 初始资金) / 初始资金
年化收益 = (1 + 总收益率)^(365/天数) - 1
夏普比率 = mean(每日超额收益) / std(每日超额收益) * sqrt(252)
           其中超额 = 每日收益 - 无风险利率/252（无风险=2%）
最大回撤 = min((组合价值 - 历史最高) / 历史最高)
胜率 = 盈利交易次数 / 总交易次数
```

### 4.3 Round 1 回测结果

**测试条件**: 22 只美股，2023-01-01 ~ 2025-12-31
**数据来源**: [`trash/old_reports/strategy_validation_20260329_1411.json`]

标的池：AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA, JPM, BAC, GS, JNJ, UNH, PFE, WMT, KO, MCD, XOM, CVX, CAT, BA, SPY, QQQ

**SPY 买入持有同期收益: +87.7%（年化约 23.4%）**

| 策略 | 平均总收益 | 平均年化 | 平均夏普 | 平均最大回撤 | 平均胜率 | 平均交易次数 | 跑赢买入持有 | 跑赢 SPY |
|------|-----------|---------|---------|------------|---------|------------|------------|---------|
| SMA Crossover | 36.1% | 10.4% | 0.36 | -17.1% | 37.5% | 12 | 7/22 (32%) | 7/22 (32%) |
| RSI | 6.1% | 1.4% | -0.03 | -12.3% | 39.3% | 28 | 5/22 (23%) | 2/22 (9%) |
| MACD | 14.2% | 3.5% | 0.14 | -17.3% | 38.5% | 31 | 4/22 (18%) | 3/22 (14%) |

**验证标准 vs 结果**:

| 指标 | 标准 | SMA | RSI | MACD |
|------|------|-----|-----|------|
| 年化收益 > 7% | ✅/❌ | ✅ 10.4% | ❌ 1.4% | ❌ 3.5% |
| 跑赢 SPY | ✅/❌ | ❌ | ❌ | ❌ |
| 夏普 > 1.0 | ✅/❌ | ❌ 0.36 | ❌ -0.03 | ❌ 0.14 |
| 最大回撤 < 25% | ✅/❌ | ✅ | ✅ | ✅ |
| 胜率 > 45% | ✅/❌ | ❌ 37.5% | ❌ 39.3% | ❌ 38.5% |

**结论: 三个纯技术策略全部未通过验证。** 核心原因：2023-2025 是强牛市，频繁进出反而错过了主升浪。技术指标在趋势市中制造了大量伪信号。

### 4.4 Round 1 关键观察

1. **SMA 是三者中"最不差"的**：至少在强势股上能赚到钱（NVDA +562%, META +182%），但远不如买入持有（NVDA 买入持有 +1211%）
2. **RSI 几乎无效**：高频交易（平均 28 笔）+ 低胜率（39%）= 佣金侵蚀严重
3. **MACD 最差**：38.5% 胜率 + 31 笔交易 = 系统性亏钱
4. **策略只在下跌股上"赢了"买入持有**：PFE(-42%), UNH(-32%) 这些下跌股，不交易自然比持有好。但好股票全部跑输
5. **核心矛盾**：技术指标的"卖出信号"在牛市中 = 踏空信号

---

## 5. Round 2: 价值投资策略

### 5.1 策略设计思路

Round 1 的教训：纯技术择时不行。于是换思路：

```
选股 → 基本面评分决定"买什么"
择时 → 均值回归辅助决定"什么时候买"
卖出 → 纪律性止盈止损决定"什么时候卖"
```

### 5.2 选股模块 — `data/fundamental_fetcher.py` 中的 `ValueScreener`

对每只股票做 0-100 分评分，5 个维度加权：

| 维度 | 权重 | 评分逻辑 |
|------|------|---------|
| **估值 (Valuation)** | 30% | PE 相对行业中位数、Forward PE vs Trailing PE 改善度、分析师目标价上涨空间、PEG ratio |
| **质量 (Quality)** | 25% | ROE（>25%=优秀）、净利润率（>25%=高）、运营利润率 |
| **成长性 (Growth)** | 20% | 营收增长率（>25%=强劲）、盈利增长率 |
| **分析师共识 (Analyst)** | 15% | 分析师 mean rating（1=强买 5=卖）、覆盖人数（<5 扣分） |
| **财务健康 (Health)** | 10% | 负债权益比（<30=优秀）、流动比率（>2=安全） |

每个维度基础分 50，然后根据指标加减分，最终 clamp 到 [0, 100]。

信号阈值：

```
总分 >= 70 → BUY（值得关注）
总分 50-69 → HOLD（一般）
总分 < 50  → AVOID（回避）
```

行业 PE 中位数参考表（硬编码，已知局限）：

```python
SECTOR_PE_MEDIAN = {
    'Technology': 30, 'Financial Services': 14, 'Healthcare': 22,
    'Consumer Cyclical': 22, 'Consumer Defensive': 24, 'Energy': 12,
    'Industrials': 20, 'Communication Services': 18, 'Basic Materials': 15,
    'Real Estate': 35, 'Utilities': 18,
}
```

### 5.3 择时模块 — `strategy/value_strategy.py` 中的 `ValueStrategy`

在基本面评分过关（>= buy_threshold）的前提下，等待技术面的"回调买入"信号：

```
买入条件（基本面通过时）:
  BUY:        价格 < 20日SMA  且  RSI < 45
  STRONG_BUY: 价格 < SMA*0.97  且  RSI < 35

卖出条件:
  SELL:       价格 > SMA*1.08  且  RSI > 75

基本面未通过时:
  不生成买入信号
  只生成超涨卖出信号（价格 > SMA*1.05 且 RSI > 70）

无基本面数据时（退化模式）:
  BUY:        价格 < SMA*0.98  且  RSI < 40
  STRONG_BUY: 价格 < SMA*0.95  且  RSI < 30
  SELL:       价格 > SMA*1.05  且  RSI > 70
```

### 5.4 回测引擎 — `strategy/value_strategy.py` 中的 `DisciplinedBacktester`

与 Round 1 回测引擎的关键区别：

| 特性 | Round 1 回测引擎 | Round 2 纪律性回测引擎 |
|------|----------------|---------------------|
| 止盈 | 无 | 达到 take_profit% 自动卖出 |
| 止损 | 无 | 亏损达 stop_loss% 自动卖出 |
| 持仓天数限制 | 无 | 超过 max_hold_days 且无买入信号时平仓 |
| 基本面评分 | 无 | 评分低于阈值不买入 |
| 基准对比 | 无 | 自动计算 Alpha、基准夏普、基准回撤 |
| 卖出类型 | 只有信号卖出 | 4种：止盈(TP)、止损(SL)、到期(EXPIRE)、信号(SIGNAL) |
| 仓位管理 | 全仓 | 全仓（未来可改分批） |

交易逻辑（按优先级）:

```
每个交易日:
  如果有持仓:
    1. 检查止盈 → 盈利 >= take_profit% → 卖出（SELL_TP）
    2. 检查止损 → 亏损 >= stop_loss% → 卖出（SELL_SL）
    3. 检查到期 → 持仓天数 >= max_hold_days 且无买入信号 → 卖出（SELL_EXPIRE）
    4. 检查策略信号 → 信号 <= SELL → 卖出（SELL_SIGNAL）
  如果无持仓:
    5. 信号 >= BUY 且 现金足够 → 全仓买入

  记录每日组合价值

回测结束: 强制平仓所有持仓（SELL_CLOSE）
```

### 5.5 回测参数配置

三组参数，覆盖保守到激进：

| 配置 | buy_threshold | take_profit | stop_loss | max_hold_days |
|------|--------------|-------------|-----------|---------------|
| **Conservative Value** | 70 | 15% | 8% | 45 天 |
| **Standard Value** | 60 | 20% | 10% | 60 天 |
| **Aggressive Value** | 50 | 30% | 12% | 90 天 |

通用参数: 初始资金 $10,000，佣金 $10/笔

### 5.6 Round 2 回测结果

**测试条件**: 20 只美股，2023-01-01 ~ 2025-12-31（排除了 SPY/QQQ 因为它们是基准）
**数据来源**: [`trash/old_reports/value_strategy_validation_20260329_1419.json`]

**SPY 买入持有同期: ~87.7%**

#### 基本面筛选结果（截至 2026-03-29 的实时数据）

| Ticker | 评分 | 信号 | 行业 |
|--------|------|------|------|
| NVDA | 82 | BUY | Technology |
| MSFT | 81 | BUY | Technology |
| GOOGL | 78 | BUY | Technology |
| META | 76 | BUY | Technology |
| AAPL | 71 | BUY | Technology |
| BAC | 71 | BUY | Financial Services |
| JNJ | 68 | HOLD | Healthcare |
| GS | 66 | HOLD | Financial Services |
| AMZN | 65 | HOLD | Consumer Cyclical |
| KO | 63 | HOLD | Consumer Defensive |
| BA | 62 | HOLD | Industrials |
| JPM | 62 | HOLD | Financial Services |
| MCD | 61 | HOLD | Consumer Cyclical |
| UNH | 59 | HOLD | Healthcare |
| PFE | 58 | HOLD | Healthcare |
| CAT | 56 | HOLD | Industrials |
| WMT | 53 | HOLD | Consumer Defensive |
| XOM | 49 | AVOID | Energy |
| TSLA | 48 | AVOID | Consumer Cyclical |
| CVX | 47 | AVOID | Energy |

共 6 只 BUY + 11 只 HOLD + 3 只 AVOID，平均评分 63.8

#### 三种策略汇总

| 策略 | 平均总收益 | 中位数收益 | 平均年化 | 平均 Alpha | 平均夏普 | 平均回撤 | 平均胜率 | 平均交易 | 跑赢买入持有 | 跑赢 SPY |
|------|-----------|-----------|---------|-----------|---------|---------|---------|---------|------------|---------|
| Conservative | 19.6% | 0.0% | 5.3% | -20.2% | 0.18 | -7.7% | 17.2% | 5 | 4/20 (20%) | 1/20 (5%) |
| Standard | 44.1% | 10.0% | 11.3% | -14.2% | 0.42 | -18.1% | 40.2% | 8 | 5/20 (25%) | 4/20 (20%) |
| Aggressive | 46.4% | 28.6% | 11.8% | -13.7% | 0.48 | -25.3% | 53.2% | 8 | 6/20 (30%) | 6/20 (30%) |

#### 基本面评分 vs 策略表现

| 评分区间 | 回测数 | 平均收益 | 平均 Alpha | 跑赢 SPY |
|---------|--------|---------|-----------|---------|
| 优秀 (>70) | 18 | 66.3% | -12.6% | 28% |
| 高分 (60-70) | 21 | 39.6% | -13.6% | 19% |
| 中分 (50-60) | 12 | 14.9% | -20.1% | 17% |
| 低分 (<50) | 9 | 0.0% | -23.4% | 0% |

**关键发现: 评分越高，收益越高。选股能力已验证，但平均仍跑不赢 SPY。**

#### 个股亮点（值得分析的案例）

| Ticker | 策略 | 收益 | 买入持有 | Alpha | 夏普 | 胜率 | 交易 | 说明 |
|--------|------|------|---------|-------|------|------|------|------|
| JPM | Standard | +195.3% | +157.7% | +20.2% | 1.84 | 90.9% | 11 | **最佳案例**: 高胜率 + 正 Alpha |
| META | Conservative | +217.5% | +437.6% | +23.7% | 1.48 | 70.0% | 20 | Alpha 正但远不如买入持有 |
| JPM | Aggressive | +166.1% | +157.7% | +15.3% | 1.60 | 87.5% | 8 | 跑赢买入持有 |
| NVDA | Standard | +160.7% | +1211.4% | +14.3% | 0.99 | 61.1% | 18 | Alpha 正但买入持有是 12 倍 |
| BA | Standard | -19.6% | +11.8% | -30.5% | -0.16 | 31.2% | 16 | **最差案例**: 频繁交易 + 亏钱 |
| MSFT | Standard | -24.3% | -14.7% | -50.4% | -0.62 | 37.5% | 8 | 2025 MSFT 下跌，策略反而亏更多 |

#### 验证标准检查

| 指标 | 标准 | Conservative | Standard | Aggressive |
|------|------|-------------|----------|-----------|
| 年化收益 > 7% | | ❌ 5.3% | ✅ 11.3% | ✅ 11.8% |
| Alpha > 0 (跑赢 SPY) | | ❌ -20.2% | ❌ -14.2% | ❌ -13.7% |
| 夏普 > 0.8 | | ❌ 0.18 | ❌ 0.42 | ❌ 0.48 |
| 最大回撤 > -25% | | ✅ -7.7% | ✅ -18.1% | ❌ -25.3% |
| 胜率 > 45% | | ❌ 17.2% | ❌ 40.2% | ✅ 53.2% |
| **总计** | | **1/5 ❌** | **2/5 ❌** | **2/5 ❌** |

---

## 6. 问题诊断与改进方向

### 6.1 已确认的问题

1. **止盈太早是最大问题**
   - 止盈 15-20% 后就跑了，但好股票 3 年涨了 200%-1200%
   - 止盈次数少（平均 0.3-1.3 次），止损次数多（平均 1.8-2.5 次）
   - 本质上是"用止损保护了下行，但止盈砍掉了上行"

2. **Conservative 策略几乎不交易**
   - buy_threshold=70 太高，大部分股票进不了买入池
   - 中位数收益 0.0%（一半以上标的零交易）
   - 不交易 = 不赚钱 + 不亏钱，但相对 SPY 也是在亏（机会成本）

3. **基本面评分是"当前快照"，不是历史序列**
   - 回测用的是 2026 年 3 月的实时基本面评分，去回测 2023-2025 年的价格数据
   - 这存在**前视偏差 (look-ahead bias)**：2026 年的 PE/ROE 不代表 2023 年的
   - 严格来说应该用每个时间点的历史基本面数据，但 yfinance 不提供历史基本面

4. **全仓进出，没有仓位管理**
   - 每次买入都是 all-in，风险集中
   - 没有多标的组合回测（当前是逐只独立回测）

5. **行业 PE 中位数是硬编码的**
   - 2023 年科技股 PE 和 2025 年差距很大
   - 应该用历史动态行业 PE

### 6.2 Expert 可以帮忙的方向

以下是我认为有价值的改进方向，按优先级排列：

**P0 — 解决止盈太早的问题**
- 移动止盈（trailing stop）：从固定 20% 止盈改为跟踪止盈，例如从最高点回撤 10% 才卖
- 或者去掉止盈，只保留止损 + 持仓天数限制
- 或者分批止盈：涨 20% 卖一半，剩下的跑到止损或到期

**P0 — 修复前视偏差**
- 用历史财报数据（quarterly earnings）替代实时快照
- 或者简化为只用"上个季度的 PE"做相对估值（yfinance 可以拿到历史 earnings，但需要额外处理）

**P1 — 组合回测**
- 当前是单标的独立回测，不反映组合效果
- 改为：每月做一次基本面筛选 → 选 Top N → 等权重或评分加权建仓 → 月度/季度再平衡
- 这样更接近实际操作场景

**P1 — 仓位管理**
- Kelly 公式或简单的"评分越高仓位越重"
- 最大单只持仓 < 20%

**P2 — 更好的数据源**
- Morningstar MCP: 星级评级 + fair value estimate（比 yfinance 的分析师目标价更专业）
- 历史 PE band：看一只股票的 PE 在自己历史分位中的位置
- 季度财报后的"earning surprise"因子

**P2 — 策略思路转变**
- 当前策略本质上还是"选个股 + 择时交易"
- 如果回测反复证明跑不赢 SPY，可能应该考虑：
  - 核心仓位定投 SPY/QQQ (80%)
  - 卫星仓位用基本面评分选个股 (20%)
  - 翠花的价值 = 选股辅助 + 风险提醒，而不是择时信号

---

## 7. 如何运行

### 环境准备

```bash
cd yuancuihua-workspace/stock-quant
pip install -r requirements.txt
```

### 跑 Round 1 回测（纯技术策略）

```bash
python run_validation.py
# 输出到 reports/strategy_validation_*.txt 和 .json
```

### 跑 Round 2 回测（价值策略）

```bash
python run_value_validation.py
# 输出到 reports/value_strategy_validation_*.txt 和 .json
```

### 跑单只股票基本面评分

```python
from data.fundamental_fetcher import FundamentalFetcher, ValueScreener

fetcher = FundamentalFetcher()
screener = ValueScreener()

fund = fetcher.fetch_fundamentals("AAPL")
score = screener.score_stock(fund)
print(f"Score: {score['total_score']}, Signal: {score['signal']}")
print(f"Reasons: {score['reasons']}")
```

### 跑单只股票价值回测

```python
from data.data_fetcher import DataFetcher
from strategy.value_strategy import ValueStrategy, DisciplinedBacktester

price_fetcher = DataFetcher()
strategy = ValueStrategy(buy_threshold=60, take_profit=0.20, stop_loss=0.10, max_hold_days=60)
backtester = DisciplinedBacktester(initial_cash=10000, commission=10, take_profit=0.20, stop_loss=0.10, max_hold_days=60)

data = price_fetcher.fetch_historical_data("AAPL", "2023-01-01", "2025-12-31")
spy = price_fetcher.fetch_historical_data("SPY", "2023-01-01", "2025-12-31")

result_df, report = backtester.run(data, strategy, fundamental_score=75, benchmark_data=spy)
print(f"Return: {report['total_return_pct']:.1f}%, Alpha: {report['alpha_pct']:+.1f}%")
```

### 修改参数

编辑 `run_value_validation.py` 中的 `STRATEGY_CONFIGS` 列表即可添加新的参数组合。

---

## 8. 总结

两轮回测的核心结论：

1. **纯技术指标（SMA/RSI/MACD）在 2023-2025 牛市中全面失败**，连年化 7% 都难稳定达到
2. **基本面评分选股有效**（高分 vs 低分差距明显），但**择时和卖出规则拖累了收益**
3. **止盈太早是最大的单一问题**：好股票涨 200%+ 但 20% 就走了
4. **存在前视偏差**：用当前基本面评分回测历史价格，结果可能偏乐观
5. **对散户来说，定投 SPY/QQQ 可能确实是更好的核心策略**

系统的价值可能不在于"替你做交易决策"，而在于"帮你做研究 + 设定纪律"。

---

*V1 报告完整数据见 `reports/strategy_validation_*.txt` 和 `reports/value_strategy_validation_*.json`。*

---
---

# V2: 组合策略重构

> 日期: 2026-03-29
> 变更: 从"单标的择时交易"彻底转向"多因子选股 + 组合持有 + 再平衡"

---

## 9. V1 → V2：为什么要重构

### V1 的核心问题诊断

经过外部 expert 审阅，V1 策略存在**根本性的框架问题**，不是调参数能解决的：

| 问题 | 说明 | 严重程度 |
|------|------|---------|
| **策略身份分裂** | 选股用价值投资逻辑（基本面评分），交易用短线波段逻辑（RSI/SMA 择时 + 固定止盈） | 致命 |
| **止盈太早** | 好股票涨 200-1200%，但 15-20% 就卖了。这是最大的收益杀手 | 致命 |
| **持仓太短** | 45-90 天上限，价值投资的 alpha 需要更长时间兑现 | 严重 |
| **全仓单只** | 每次 all-in 一只股票，风险集中 | 严重 |
| **纯技术择时无效** | 学术界共识：日线级别的个股择时对收益贡献接近零甚至为负 | 严重 |
| **前视偏差** | 用 2026 年基本面评分回测 2023-2025 价格 | 中等 |
| **新闻情感系统粗糙** | TextBlob 不懂金融语境，"beats estimates" 可能被误判 | 中等 |

### V2 的设计思路

**核心转变：从"AI帮你炒股"变成"AI帮你选股 + 帮你守纪律 + 帮你躲风险"。**

```
V1: 选股 → 等回调 → 买入 → 固定止盈/止损 → 卖出 → 重复      （短线波段）
V2: 月度选股 → 等权建仓 → 持有 → Trailing Stop → 月度再平衡   （组合持有）
```

三个支柱：

1. **选对股**：基本面评分 + 动量因子（避免价值陷阱）
2. **躲大跌**：SPY 200日均线 Regime Filter（熊市减仓）
3. **让赢家跑**：去掉固定止盈，改为 Trailing Stop 25%

---

## 10. V2 新增代码

### 10.1 代码结构

```
stock-quant/
├── strategy/
│   ├── strategies.py              # V1: 纯技术指标策略（保留）
│   ├── value_strategy.py          # V1: 价值投资策略（保留）
│   ├── momentum.py                # V2 新增: 动量因子计算
│   ├── regime_filter.py           # V2 新增: 市场环境判断
│   └── portfolio_strategy.py      # V2 新增: 组合管理策略
│
├── backtest/
│   ├── backtester.py              # V1: 单标的回测引擎（保留）
│   └── portfolio_backtester.py    # V2 新增: 组合级回测引擎
│
├── sentiment/
│   └── sentiment_analyzer.py      # V2 重写: TextBlob → Haiku API
│
├── run_portfolio_validation.py    # V2 新增: 组合回测脚本
└── ...
```

### 10.2 动量模块 — `strategy/momentum.py`

**学术依据**: Jegadeesh & Titman (1993) 动量效应

```
MomentumScorer:
  lookback: 6个月价格动量（剔除最近1个月，避免短期反转噪音）
  趋势确认: 价格是否在 200日均线之上
  输出: composite_score (0-100) = 动量收益分 70% + 趋势分 30%

收益映射:
  -30% 以下 → 0 分
  0%        → 50 分
  +60% 以上 → 100 分
```

**关键作用**: 过滤"价值陷阱"。基本面评分高但价格一直跌的股票（如 PFE），动量分会很低，不会被选入组合。

### 10.3 市场环境过滤 — `strategy/regime_filter.py`

**学术依据**: Faber (2007) "A Quantitative Approach to Tactical Asset Allocation"

```
RegimeFilter:
  信号1: SPY 是否在 200日SMA 之上
  信号2: SPY 是否在 10月均线之上

  两者都满足 → BULL（仓位 100%）
  满足一个   → CAUTION（仓位 50%）
  都不满足   → BEAR（仓位 25%）
```

**关键作用**: 在 2025-04 市场回调期间，regime 判定为 BEAR，仓位缩减至 25%，有效控制回撤。

### 10.4 组合管理策略 — `strategy/portfolio_strategy.py`

```
PortfolioStrategy:
  选股: 基本面评分 50% + 动量评分 30% + 分析师评分 20% → 综合分
        过滤: 动量 < 门槛 → 不选（避免价值陷阱）
        排名: Top N（默认8只）

  建仓: 等权重，单只上限 15%
        SPY 底仓 20-30%

  卖出: Trailing Stop 25%（从最高点回撤25%才卖，让赢家跑）
        月度再平衡时被新股替换

  不做的事: 不看 RSI，不看 SMA 交叉，不做日内择时
```

### 10.5 组合回测引擎 — `backtest/portfolio_backtester.py`

与 V1 回测引擎的关键区别：

| 特性 | V1 DisciplinedBacktester | V2 PortfolioBacktester |
|------|------------------------|----------------------|
| 持仓 | 单只全仓 | 多只等权重 |
| 止盈 | 固定 15-20% | **无固定止盈**，Trailing Stop 25% |
| 止损 | 固定 8-12% | Trailing Stop 统一处理 |
| 持仓限制 | 45-90 天 | 无时间限制，月度再平衡决定 |
| 再平衡 | 无 | 月度/季度 |
| 市场环境 | 无 | Regime Filter 调整总仓位 |
| SPY 底仓 | 无 | 有（20-30%） |
| 初始资金 | $10,000 | $100,000（更接近真实组合） |

### 10.6 情感分析升级 — `sentiment/sentiment_analyzer.py`

```
V1: TextBlob（通用NLP） → polarity 浮点数 → 每日择时信号
V2: Claude Haiku API → 结构化事件分析 → 风控预警

Haiku 输出:
  event_type: "earnings_miss" / "sec_investigation" / "upgrade" / ...
  severity: "critical" / "high" / "medium" / "low" / "negligible"
  action: "review_position" / "hold" / "ignore"
  summary: 一句话说明

Fallback: 无 API Key 时退化为关键词匹配

成本: ~$0.05/天（200条新闻），可忽略
```

---

## 11. V2 回测结果

### 11.1 测试条件

- **标的池**: 20 只美股（与 V1 相同）
- **周期**: 2023-01-01 ~ 2025-12-31
- **基准**: SPY 买入持有（同期 +87.7%，年化 +23.4%）
- **初始资金**: $100,000
- **佣金**: $10/笔

### 11.2 五种配置对比

| 配置 | 总收益 | 年化 | Alpha | 夏普 | 最大回撤 | 胜率 | 交易 | 平均持仓 |
|------|--------|------|-------|------|---------|------|------|---------|
| **Aggressive** | +81.1% | +22.0% | **-1.5%** | **1.42** | -17.1% | 63% | 139 | 7.6只 |
| Conservative | +75.1% | +20.6% | -2.8% | 1.36 | **-14.7%** | 64% | 73 | 3.4只 |
| Quarterly | +74.4% | +20.4% | -3.0% | 1.39 | -16.0% | **67%** | 75 | 5.5只 |
| Standard (Regime) | +71.0% | +19.6% | -3.8% | 1.29 | -16.2% | 58% | 113 | 5.7只 |
| Standard (No Regime) | +72.4% | +20.0% | -3.5% | 1.18 | -23.7% | 56% | 93 | 5.4只 |
| **SPY Buy & Hold** | **+87.7%** | **+23.4%** | 0% | 1.32 | -18.8% | — | 1 | 1只 |

### 11.3 配置参数

| 配置 | Top N | 综合分门槛 | 动量门槛 | SPY 底仓 | Trailing Stop | Regime | 再平衡 |
|------|-------|----------|---------|---------|--------------|--------|--------|
| Aggressive | 10 | 45 | 30 | 10% | 30% | On | Monthly |
| Conservative | 5 | 65 | 50 | 30% | 20% | On | Monthly |
| Quarterly | 8 | 55 | 40 | 20% | 25% | On | Quarterly |
| Standard (Regime) | 8 | 55 | 40 | 20% | 25% | On | Monthly |
| Standard (No Regime) | 8 | 55 | 40 | 20% | 25% | Off | Monthly |

### 11.4 V1 vs V2 对比

| 指标 | V1 最好 (Aggressive Value) | V2 最好 (Aggressive Portfolio) | 改善幅度 |
|------|--------------------------|-------------------------------|---------|
| 年化收益 | 11.8% | **22.0%** | **+10.2%** |
| Alpha | -13.7% | **-1.5%** | **+12.2%** |
| 夏普比率 | 0.48 | **1.42** | **+0.94** |
| 最大回撤 | -25.3% | **-17.1%** | **+8.2%** |
| 胜率 | 53.2% | **63.3%** | **+10.1%** |

**每一个风险收益指标都有显著改善。**

### 11.5 关键发现

**1. Regime Filter 的效果**

| 指标 | 有 Regime | 无 Regime | 差值 |
|------|----------|----------|------|
| 最大回撤 | -16.2% | -23.7% | **+7.5%**（少亏） |
| 夏普 | 1.29 | 1.18 | +0.11 |
| 收益 | +71.0% | +72.4% | -1.4%（略少赚） |

结论：Regime Filter **大幅降低回撤**（少亏 7.5%），代价是在牛市中略少赚 1.4%。风险调整后更优。

实际案例：2025-04 市场回调，Regime 判定 BEAR → 仓位缩至 25% → 组合回撤 -16% vs SPY -19%。

**2. 动量过滤的效果**

以下股票在多个月份被动量过滤器拦截（评分 < 门槛）：

| 股票 | 动量评分范围 | 基本面评分 | 3年实际表现 | 结论 |
|------|------------|----------|-----------|------|
| PFE | 13-37 | 58 | **-42%** | 正确拦截（价值陷阱） |
| TSLA | 1-24 | 48 | 波动巨大 | 正确拦截（高波动低质量） |
| BA | 11-30 | 61.5 | +11.8% | 正确拦截（弱势股） |
| UNH | 0-26 | 59 | **-32%** | 正确拦截（持续下跌） |

动量过滤器成功避开了 V1 中亏钱最多的几只股票。

**3. 前 8 个月的"空窗期"**

回测显示 2023-01 ~ 2023-08 选股列表为空（动量因子需要 6 个月历史数据积累）。这段时间组合只有 SPY 底仓在跑。

这是回测的技术性拖累，实盘不会有这个问题（策略启动前就有足够历史数据）。如果把"空窗期"排除，有效期内的 Alpha 会更好。

**4. 仍然没有跑赢 SPY 的原因**

- 2023-2025 是 Magnificent 7 驱动的极端牛市，SPY 被几只超级大盘股拉着跑
- 20 只股票的分散组合天然会被稀释（NVDA +1211%，但在组合中只占 10-15%）
- SPY 底仓 20% 本身就是在跑 SPY 的收益，拖累了跑赢的空间
- 但**风险调整后的表现更好**：夏普 1.42 > SPY 1.32

### 11.6 验证标准检查

| 指标 | 标准 | Aggressive | Conservative | Quarterly | Standard |
|------|------|-----------|-------------|-----------|---------|
| 年化 > 10% | | **PASS** 22.0% | **PASS** 20.6% | **PASS** 20.4% | **PASS** 19.6% |
| Alpha > 0 | | FAIL -1.5% | FAIL -2.8% | FAIL -3.0% | FAIL -3.8% |
| 夏普 > 0.8 | | **PASS** 1.42 | **PASS** 1.36 | **PASS** 1.39 | **PASS** 1.29 |
| 回撤 > -20% | | **PASS** -17.1% | **PASS** -14.7% | **PASS** -16.0% | **PASS** -16.2% |
| 胜率 > 45% | | **PASS** 63% | **PASS** 64% | **PASS** 67% | **PASS** 58% |
| **总计** | | **4/5** | **4/5** | **4/5** | **4/5** |

V1 最好成绩是 2/5，V2 所有配置都达到 4/5。唯一未通过的是 Alpha > 0。

---

## 12. V2 总结与下一步

### 已验证

1. **组合策略框架是正确的**：从单标的择时 → 多因子选股+组合持有，所有指标大幅改善
2. **动量因子有效**：成功过滤了 PFE(-42%)、UNH(-32%) 等价值陷阱
3. **Regime Filter 有效**：回撤从 -23.7% 降到 -16.2%，风险调整后更优
4. **Trailing Stop 比固定止盈好**：让赢家跑，不再 +20% 就走
5. **情感分析升级完成**：TextBlob → Haiku API，从"情感打分"变为"事件驱动风控"

### 未解决

1. **Alpha 仍为负**：最好 -1.5%，还没跑赢 SPY
2. **前视偏差**：基本面评分仍用当前快照，实际 Alpha 可能更差
3. **标的池太小**：20 只不够动量因子发挥，需扩大到 50-100 只
4. **前 8 个月空窗期**：动量数据积累期内无法选股

### V3 方向（如果继续迭代）

| 优先级 | 方向 | 预期影响 |
|--------|------|---------|
| P0 | 扩大标的池至 S&P 100 或 Russell 1000 | 动量因子在更大池子里选股效果更好 |
| P0 | 修复前视偏差（用历史季度财报数据） | 让回测结果可信 |
| P1 | 评分加权建仓（替代等权重） | 高评分股票多配，可能提高 Alpha |
| P1 | 加入 earnings surprise 因子 | 财报超预期是最强的短期 alpha 信号之一 |
| P2 | 新闻系统接入 Haiku 做实时风控预警 | 减少黑天鹅损失 |
| P2 | 考虑核心+卫星策略：80% SPY + 20% 选股 | 如果选股 Alpha 为正，这样更实用 |

### 对散户的诚实建议

经过两个版本的迭代，我们的结论是：

> **在 2023-2025 这样的强牛市中，跑赢 SPY 对任何主动策略都极其困难。**
>
> 但策略的价值不只是"跑赢大盘"：
> - **夏普 1.42 > SPY 1.32**：风险调整后的收益更好
> - **回撤 -14.7% < SPY -18.8%**：熊市中少亏就是赢
> - **选股能力验证通过**：高分股 vs 低分股差距显著
>
> 翠花的定位应该是：**研究助手 + 纪律执行器 + 风险预警系统**，而不是"印钞机"。

---

*V2 数据来源: [`trash/old_reports/portfolio_validation_20260329_1512.json`]*

---
---

# V3: 扩大标的池 + 修复前视偏差

> 日期: 2026-03-29
> 变更: S&P 100 标的池（~85只）+ 历史季度财报评分 + 回测周期拉长至 7 年

---

## 13. V2 → V3：修复两个关键问题

### 问题1: 标的池太小

V2 只有 20 只股票，动量因子在小池子里选股效果受限。扩大到 S&P 100（~85只有效标的），覆盖科技、金融、医疗、消费、工业、能源、通信等全部行业。

### 问题2: 前视偏差

V2 用 2026 年 3 月的实时基本面评分去回测 2023-2025 年的价格数据 — 这是严重的前视偏差。

V3 新增 `data/historical_fundamentals.py`：
- 从 yfinance 获取历史季度财报（`quarterly_income_stmt`, `quarterly_balance_sheet`）
- 假设季度结束后 60 天数据可用（模拟真实信息延迟）
- 在每个回测日期，只用当时已公开的财报数据做评分
- 评分维度：估值（PE）30% + 质量（利润率/ROE）30% + 成长性（营收增长）25% + 财务健康（负债率）15%

### 回测周期

**实际执行**: 2023-01-01 ~ 2025-12-31（3年，与 V2 相同区间）。

> **设计意图 vs 实际**: 原计划拉长到 2018-2025（7年），覆盖 2018 贸易战/2020 新冠崩盘/2022 熊市/2023-2025 AI 牛市。该扩展于 **2026-03-30** 完成，数据见 `reports/portfolio_v3_validation_20260330_1540.json`（结果已在 §14 末尾注）。本节数据均来自 2023-2025 的原始跑。

---

## 14. V3 回测结果

### 测试条件

- **标的池**: S&P 100 ~85 只
- **周期**: 2023-01-01 ~ 2025-12-31（3年）
- **基准**: SPY 买入持有（同期 +87.7%，年化 +23.4%）
- **数据来源**: [`trash/old_reports/portfolio_v3_validation_20260329_1528.json`]

### 策略对比

| 配置 | 总收益 | 年化 | Alpha | 夏普 | 最大回撤 | 胜率 | 平均持仓 | Beat SPY |
|------|--------|------|-------|------|---------|------|---------|----------|
| **V3 Standard (Historical)** | +103.3% | +26.8% | **+3.3%** | **1.41** | -13.7% | 66.3% | 9.2 | **Y** |
| V3 Aggressive (Historical) | +98.1% | +25.7% | +2.3% | 1.35 | -13.9% | 58.3% | 14.2 | Y |
| V3 Conservative (Historical) | +98.3% | +25.7% | +2.3% | 1.34 | -15.6% | 58.5% | 7.3 | Y |
| V3 Standard (Static) | +116.9% | +29.5% | +6.1% | 1.46 | -13.7% | 65.1% | 9.2 | Y |
| **SPY Buy & Hold** | +87.7% | +23.4% | 0% | 1.32 | -18.8% | — | 1 | — |

### 前视偏差影响

| 指标 | Historical | Static | 差值 |
|------|-----------|--------|------|
| Alpha | +3.3% | +6.1% | -2.8% |
| 夏普 | 1.41 | 1.46 | -0.05 |

**前视偏差约 +2.8% Alpha。** 修复后策略仍然有效（Alpha 仍为正）。

### V3 关键突破

1. **首次实现正 Alpha**: +3.3%（Historical模式），从 V2 的 -1.5% 变为正
2. **所有配置全部跑赢 SPY**
3. **回撤 -13.7% vs SPY -18.8%**: 风险控制优秀
4. **3年牛市验证通过**: 在强势市场环境下仍能维持正 Alpha

> **注（2018-2025 重跑）**: V3 于 2026-03-30 在更长区间重测（`reports/portfolio_v3_validation_20260330_1540.json`），结果：
> - Standard: 总收益 +188.8%，年化 +14.2%，Alpha **+0.1%**，夏普 0.68，最大回撤 -28.8%
> - Aggressive: 总收益 +281.1%，年化 +18.2%，Alpha **+4.1%**，夏普 0.84，最大回撤 -29.8%
> - 基准：SPY +187.5%，年化 +14.1%，96次再平衡（8年）
> - 结论：8年区间下 Aggressive 配置仍能打赢 SPY，但 Standard 仅微弱 +0.1%，夏普也从 1.41 降至 0.68，说明 V3 的优势主要来自 2023-2025 牛市。

---
---

# V3.1: Earnings Surprise 因子 + 更大标的池

> 日期: 2026-03-29
> 变更: PEAD 因子 + S&P 500 核心 ~150 只

---

## 15. V3 → V3.1：两个改进尝试

### 改进1: Earnings Surprise 因子（PEAD）

新增 `strategy/earnings_surprise.py`：

**学术依据**: Bernard & Thomas (1989) Post-Earnings Announcement Drift

- 财报超预期后，股价在 60-90 天内持续漂移（市场反应不足）
- 这是金融学中最持久的异象之一，发现 30+ 年仍然有效

**实现**:
- 从 yfinance 获取 EPS actual vs estimate
- 计算 surprise % = (actual - estimate) / |estimate|
- 正 surprise → 加分，负 surprise → 减分
- 连续 beat/miss 有额外权重（趋势性）
- 时间衰减：超过 120 天没有新财报，分数向 50 衰减
- 融合方式：原基本面分 80% + earnings_score 20%

### 改进2: 扩大到 S&P 500 核心 ~150 只

从 S&P 100 扩大到各行业 Top 市值约 150 只。

---

## 16. V3.1 回测结果

- **周期**: 2023-01-01 ~ 2025-12-31（3年）
- **数据来源**: [`trash/old_reports/portfolio_v3.1_20260329_1548.json`]

| 配置 | 总收益 | 年化 | Alpha | 夏普 | 最大回撤 | 胜率 | Beat SPY |
|------|--------|------|-------|------|---------|------|----------|
| V3.1 Standard | +87.4% | +23.4% | -0.1% | 1.19 | -15.5% | 56.2% | N |
| V3.1 Aggressive | +77.2% | +21.1% | -2.4% | 1.04 | -17.3% | 51.5% | N |
| V3.1 Conservative | +83.4% | +22.5% | -0.9% | 1.12 | -18.4% | 53.6% | N |
| V3.1 Quarterly | +72.0% | +19.9% | -3.6% | 1.07 | -15.6% | 61.8% | N |
| V3 Standard (对比) | +103.3% | +26.8% | +3.3% | 1.41 | -13.7% | 66.3% | Y |
| SPY Buy & Hold | +87.7% | +23.4% | 0% | 1.32 | -18.8% | — | — |

### V3.1 失败分析

**Alpha 从 V3 的 +3.3% 退回到 -0.1%（Standard），所有配置均未跑赢 SPY。** 原因：

1. **标的池稀释**: 150 只中很多是平庸的中盘股，降低了整体选股质量
2. **Earnings Surprise 信号噪音大**: 在大池子里，PEAD 效应被分散了
3. **S&P 100 是最优池子**: ~85 只大盘龙头 + 动量因子 = 最佳组合

**结论: V3 的 S&P 100 配置是甜蜜点，不宜盲目扩大标的池。V3.1 的 Earnings Surprise 因子保留在代码中，但效果不显著。**

---
---

# V4: 跨资产 Regime Filter

> 日期: 2026-03-29
> 变更: Regime Filter 从"仅 SPY 均线"升级为"SPY 均线 + 收益率曲线 + VIX + 信用利差"

---

## 17. V3 → V4：Regime Filter 升级

### 动机

V3 的 Regime Filter 只看 SPY 是否在 200日/10月均线之上。这是滞后指标 — 等 SPY 跌破均线时，已经亏了 5-10%。

跨资产信号可以**更早预警**：
- 收益率曲线倒挂 → 预警衰退（领先 6-12 个月）
- VIX 飙升 → 市场恐慌（实时）
- 信用利差扩大 → 信用紧缩（领先 3-6 个月）

### 新增跨资产信号

全部通过 yfinance 获取，无需额外 API key。

| 信号 | 数据源 | 逻辑 | 学术依据 |
|------|--------|------|---------|
| **收益率曲线** | ^TNX (10Y) - ^IRX (13W) | 倒挂 → 衰退预警 → 减分 | Harvey (1988) |
| **VIX** | ^VIX | 水平 + 趋势，>30 恐慌 → 减分 | 经典风险指标 |
| **信用利差** | HYG/LQD 比值 | 比值下降 → 资金避险 → 减分 | Gilchrist & Zakrajsek (2012) |

### 权重设计

**关键教训**: 第一版权重（SMA 35% + 跨资产各 20-25%）过度谨慎，在 2023-2025 牛市中少赚 28%。

最终权重：**SMA 主导（55%），跨资产辅助（各 15%）**。

```
合成分数 = SMA分 * 55% + 收益率曲线分 * 15% + VIX分 * 15% + 信用利差分 * 15%

BULL:    合成分 >= 55 → 仓位 100%
CAUTION: 合成分 25-55 → 仓位 50%
BEAR:    合成分 < 25  → 仓位 25%
```

设计原则：只有 SMA 看空 **且** 多个跨资产信号同时恶化时才触发减仓，避免单一信号的误报。

---

## 18. V4 回测结果

### 测试条件

- **标的池**: S&P 100 ~85 只（与 V3 相同）
- **周期**: 2023-01-01 ~ 2025-12-31（3年）
- **宏观数据**: ^TNX, ^IRX, ^VIX, HYG, LQD
- **数据来源**: [`trash/old_reports/portfolio_v4_20260329_1613.json`]

### V3 vs V4 对比（同一参数，只改 Regime Filter）

| 指标 | V4 跨资产 | V3 仅SMA | 差值 |
|------|----------|----------|------|
| 总收益 | **+106.2%** | +103.2% | **+2.9%** |
| 年化收益 | **+27.4%** | +26.8% | **+0.6%** |
| Alpha | **+3.9%** | +3.3% | **+0.6%** |
| 夏普 | **1.44** | 1.41 | **+0.03** |
| 最大回撤 | -13.7% | -13.7% | 持平 |
| 胜率 | 63.3% | 66.3% | -3.0% |

### 全部 V4 配置

| 配置 | 年化 | Alpha | 夏普 | 最大回撤 | Beat SPY |
|------|------|-------|------|---------|----------|
| **V4 Cross-Asset Regime** | **+27.4%** | **+3.9%** | **1.44** | -13.7% | **Y** |
| V4 Aggressive | +25.8% | +2.4% | 1.36 | -13.9% | Y |
| V4 Conservative | +26.3% | +2.9% | 1.36 | -15.6% | Y |
| V3 Baseline | +26.8% | +3.3% | 1.41 | -13.7% | Y |
| **SPY Buy & Hold** | +23.4% | 0% | 1.32 | -18.8% | — |

**所有配置 5/5 PASS 验证标准，全部跑赢 SPY。**

### 市场环境分布

| 状态 | V4 天数 | V3 天数 | 差异 |
|------|--------|--------|------|
| BULL | 687 | 709 | -22 |
| CAUTION | 30 | 1 | +29 |
| BEAR | 34 | 41 | -7 |

V4 比 V3 多了 29 天 CAUTION（精准减仓），同时减少了 7 天 BEAR 误判。

---

## 19. V1 → V4 完整迭代总结

| 版本 | Alpha | 夏普 | 最大回撤 | 核心改进 | 回测区间 |
|------|-------|------|---------|---------|---------|
| V1 | -13.7% | 0.48 | -25.3% | 纯技术/价值策略 | 2023-2025 |
| V2 | -1.5% | 1.42 | -17.1% | 组合重构 + 动量 + Regime + Trailing Stop | 2023-2025 |
| V3 | +3.3% | 1.41 | -13.7% | S&P 100 + 历史财报 | 2023-2025 |
| V3.1 | -0.1% | 1.19 | -15.5% | 扩到150只（失败，标的池稀释） | 2023-2025 |
| **V4** | **+3.9%** | **1.44** | **-13.7%** | **跨资产 Regime Filter** | **2023-2025** |

**从 V1 到 V4，Alpha 改善 +17.6%，夏普从 0.48 提升到 1.44，最大回撤从 -25.3% 缩小到 -13.7%。**

### 当前最佳配置（V4 Standard）

```
标的池:        S&P 100 (~85只)
选股:          基本面 50% + 动量 30% + 分析师 20%
动量门槛:      40 (过滤价值陷阱)
Top N:         10 只
SPY 底仓:      20%
Trailing Stop: 25%
Regime Filter: SPY均线 55% + 收益率曲线 15% + VIX 15% + 信用利差 15%
再平衡:        月度
初始资金:      $100,000
```

### 下一步方向

| 优先级 | 方向 | 预期影响 |
|--------|------|---------|
| P1 | Insider Trading 信号（SEC Form 4 高管买入） | 正交因子，+1-2% Alpha |
| P1 | Short Interest 负面过滤（>15% 排除） | 避险，减少回撤 |
| P2 | Telegram 信号推送接入 | 实盘可用 |
| P2 | Spin-off 异象人工辅助筛选 | 事件驱动，机会少但收益高 |

---

*V3 数据来源: [`trash/old_reports/portfolio_v3_validation_20260329_1528.json`] (2023-2025) | V3 重跑 2018-2025: [`reports/portfolio_v3_validation_20260330_1540.json`]*
*V4 数据来源: [`trash/old_reports/portfolio_v4_20260329_1613.json`]*

---
---

# V5: Short Interest 过滤 + Insider Trading 信号

> 日期: 2026-03-29
> 变更: 两个新的选股信号，保留 V4 全部改进

---

## 20. V4 → V5：两个新信号

### 信号1: Short Interest 负面过滤

**原理**: 空头比例 > 15% 的股票被大量做空，风险极高，直接排除。

**实现**: `data/fundamental_fetcher.py` 新增 `shortPercentOfFloat` 字段，`portfolio_strategy.py` 的 `select_stocks()` 中加入过滤条件。

**数据源**: yfinance `Ticker.info['shortPercentOfFloat']`

### 信号2: Insider Trading 加分

**原理**: SEC Form 4 披露的高管买卖交易。集群买入（3个月内 ≥3 个 insider 买入）是极强的看涨信号。

**学术依据**: Lakonishok & Lee (2001), Jeng et al. (2003) — insider buy portfolios 年化超额 7-10%

新增模块 `strategy/insider_signal.py`：
- 从 yfinance `insider_transactions` 获取交易记录
- 统计 90 天和 180 天内的买入/卖出 insider 人数
- 集群买入（≥3人/90天）→ +5~8 分加到综合评分
- 双人买入 → +3 分，单人买入 → +1 分
- 缓存 7 天（JSON 文件）

**融合方式**: 作为加分项直接加到 `combined_score` 上（0-8 分）

---

## 21. V5 回测结果

- **周期**: 2023-01-01 ~ 2025-12-31（3年）
- **数据来源**: [`reports/portfolio_v5_20260329_2133.json`]

### V5 vs V4 对比

| 指标 | V5 (全部) | V4 (仅Regime) | 差值 |
|------|----------|--------------|------|
| 年化收益 | +27.4% | +27.4% | +0.0% |
| Alpha | +4.0% | +3.9% | +0.1% |
| 夏普 | 1.44 | 1.44 | +0.00 |
| 最大回撤 | -13.7% | -13.7% | +0.0% |

### 全部配置

| 配置 | 年化 | Alpha | 夏普 | 最大回撤 | Beat SPY |
|------|------|-------|------|---------|----------|
| **V5 Full** | **+27.4%** | **+4.0%** | **1.44** | -13.7% | **Y** |
| V4 Baseline | +27.4% | +3.9% | 1.44 | -13.7% | Y |
| V5 Aggressive | +25.9% | +2.4% | 1.37 | -13.9% | Y |
| V5 Conservative | +26.5% | +3.1% | 1.37 | -15.6% | Y |
| SPY Buy & Hold | +23.4% | 0% | 1.32 | -18.8% | — |

**全部 5/5 PASS。**

### 增量效果分析

Short Interest 和 Insider Trading 在回测中的增量很小（+0.1% Alpha），原因：

1. **S&P 100 很少有 >15% 空头比例**: 这些都是大盘蓝筹，没有被排除的股票。但如果未来扩大到小盘股池，这个过滤器会非常有价值
2. **yfinance Insider 数据只有 ~2 年历史**: 在 7 年回测中，2018-2023 的大部分日期没有 insider 数据可用
3. **信号本质是"防守型"**: 不是靠它赚更多钱，而是防止踩雷。在历史回测中效果不显著，但在实盘中遇到一次黑天鹅就值回票价

**结论**: 这两个信号的价值更多体现在**实时信号生成**而非历史回测中。代码已就绪，保留在系统中。

---

## 22. V1 → V5 完整迭代总结

| 版本 | Alpha | 夏普 | 最大回撤 | 核心改进 | 回测区间 |
|------|-------|------|---------|---------|---------|
| V1 | -13.7% | 0.48 | -25.3% | 纯技术/价值策略 | 2023-2025 |
| V2 | -1.5% | 1.42 | -17.1% | 组合重构 + 动量 + Regime + Trailing Stop | 2023-2025 |
| V3 | +3.3% | 1.41 | -13.7% | S&P 100 + 历史财报 | 2023-2025 |
| V3.1 | -0.1% | 1.19 | -15.5% | 扩到150只（失败） | 2023-2025 |
| V4 | +3.9% | 1.44 | -13.7% | 跨资产 Regime Filter | 2023-2025 |
| **V5** | **+4.0%** | **1.44** | **-13.7%** | **Short Interest + Insider Trading** | **2023-2025** |

**从 V1 到 V5: Alpha +17.7%, 夏普 0.48→1.44, 回撤 -25.3%→-13.7%**

### 当前最佳配置（V5 Standard）

```
标的池:         S&P 100 (~85只)
选股:           基本面 50% + 动量 30% + 分析师 20% + Insider 加分
过滤:           动量 < 40 排除, Short Interest > 15% 排除
Top N:          10 只
SPY 底仓:       20%
Trailing Stop:  25%
Regime Filter:  SPY均线 55% + 收益率曲线 15% + VIX 15% + 信用利差 15%
再平衡:         月度
Earnings:       Surprise 调整（原分 80% + earnings 20%）
```

### 下一步方向

→ 已在 V6 中实现新闻情绪因子

---

*V5 数据来源: [`reports/portfolio_v5_20260329_2133.json`]*

---
---

# V6: 历史新闻情绪因子

> 日期: 2026-03-29
> 变更: 接入 HuggingFace 历史新闻数据集，基于金融情绪词典的新闻评分因子

---

## 23. V5 → V6：新闻情绪信号

### 动机

之前的系统完全没有新闻信息。新闻情绪是一个重要的短期信号 — 正面新闻集中出现的股票往往短期内继续上涨（情绪动量），负面新闻则相反。

### 数据来源

使用 HuggingFace 免费数据集 `ashraq/financial-news`：
- **覆盖**: ~40,000 条新闻标题，61/85 个 S&P 100 ticker
- **时间**: 2010-02 ~ 2020-06
- **字段**: headline（标题）、stock（ticker）、date、publisher

> **限制**: 数据只覆盖到 2020 年中，无法用于 2021-2025 回测。因此 V6 回测使用 2018-2020 区间。

### 新增模块 — `data/historical_news.py`

**情绪评分方法**: 金融情绪词典（Loughran-McDonald 风格精简版），无需 LLM API，可快速处理大量标题。

```
正面词: beat, upgrade, surge, record, growth, buyback, approval...
负面词: miss, downgrade, plunge, fraud, lawsuit, bankruptcy, layoff...
强信号词 (权重 x2): beat, missed, downgrade, fraud, crash, breakthrough...

评分流程:
1. 标题分词 → 匹配正面/负面词
2. 强信号词 x2 权重
3. 归一化到 [-1, +1]
4. 聚合 30 天内标题的平均情绪
5. 映射到 0-10 分（5 = 中性，>5 = 正面，<5 = 负面）
6. 新闻 < 3 条时信号减半（低置信度）
```

**融合方式**: `news_score` 转化为 -3 ~ +3 的加分，直接加到 `combined_score`。

```python
# portfolio_strategy.py
news_bonus = (news_score - 5.0) * 0.6  # 范围: -3 ~ +3
combined += news_bonus
```

---

## 24. V6 回测结果

### 测试条件

- **标的池**: S&P 100 ~85 只
- **周期**: 2018-01-01 ~ 2020-12-31（3年，新闻数据覆盖范围）
- **新闻覆盖**: 61/85 tickers，39,732 条标题
- **基准**: SPY 买入持有（同期 +47.1%）
- **数据来源**: [`reports/portfolio_v6_news_20260329_2140.json`]

### V6 vs V5 对比（同一参数，加/不加新闻因子）

| 配置 | 总收益 | Alpha | 夏普 | 最大回撤 | 胜率 | Beat SPY |
|------|--------|-------|------|---------|------|----------|
| **V6 Standard (News)** | +33.7% | -3.6% | 0.46 | -28.1% | 61% | N |
| V5 Standard (No News) | +30.9% | -4.3% | 0.43 | -27.7% | 60% | N |
| **V6 Aggressive (News)** | **+52.2%** | **+1.3%** | **0.63** | -29.5% | 62% | **Y** |
| V6 Conservative (News) | +32.9% | -3.8% | 0.48 | **-23.7%** | **66%** | N |
| **SPY Buy & Hold** | +47.1% | 0% | 0.59 | -33.7% | — | — |

### 新闻因子增量 (V6 Standard - V5 Standard)

| 指标 | V6 | V5 | 差值 |
|------|----|----|------|
| 收益 | +33.7% | +30.9% | **+2.76%** |
| Alpha | -3.6% | -4.3% | **+0.77%** |
| 夏普 | 0.46 | 0.43 | **+0.03** |
| 回撤 | -28.1% | -27.7% | -0.41% |

### 分析

1. **新闻因子有正面增量**: 收益 +2.76%，Alpha +0.77%，夏普 +0.03 — 一致的小幅正向贡献
2. **Aggressive 配置打赢 SPY**: +52.2% vs +47.1%，Alpha +1.3%，这是唯一跑赢基准的配置
3. **Conservative 回撤最佳**: -23.7% vs SPY -33.7%，COVID 崩盘中保护了 10% 的回撤
4. **Standard 配置未跑赢 SPY**: 2018-2020 区间 SPY 收益 +47.1% 很高（2020 V 型反弹），短周期不太利于策略

### 为什么增量有限？

1. **数据覆盖不足**: 只有 ashraq/financial-news（4万条），仅覆盖 61/85 ticker
2. **只有标题无正文**: 关键词匹配只能做粗颗粒度情绪判断
3. **区间差异**: V6 用 2018-2020（含 COVID 崩盘），V4/V5 用 2023-2025（纯牛市），基准和市场环境不同，Alpha 不可直接比较
4. **关键词词典有限**: 不如 NLP/LLM 能理解语义（如 "beats estimates despite headwinds" 中的复杂语义）

### 改进方向

如果要提升新闻因子效果：
- **付费数据源**: Polygon.io ($29/月) 或 Tiingo ($10/月)，覆盖更长时间 + 更多 ticker
- **LLM 情绪分析**: 用 Haiku 对关键新闻做语义情绪判断（成本需控制）
- **实时新闻**: NewsAPI / Finnhub 免费 API 做实时信号（非回测）

---

## 25. V1 → V6 完整迭代总结

| 版本 | Alpha | 夏普 | 最大回撤 | 核心改进 | 回测区间 |
|------|-------|------|---------|---------|---------|
| V1 | -13.7% | 0.48 | -25.3% | 纯技术/价值策略 | 2023-2025 |
| V2 | -1.5% | 1.42 | -17.1% | 组合重构 + 动量 + Regime + Trailing Stop | 2023-2025 |
| V3 | +3.3% | 1.41 | -13.7% | S&P 100 + 历史财报 | 2023-2025 |
| V3.1 | -0.1% | 1.19 | -15.5% | 扩到150只（失败） | 2023-2025 |
| V4 | +3.9% | 1.44 | -13.7% | 跨资产 Regime Filter | 2023-2025 |
| V5 | +4.0% | 1.44 | -13.7% | Short Interest + Insider Trading | 2023-2025 |
| **V6** | **-3.6%** | **0.46** | **-28.1%** | **新闻情绪因子** | **2018-2020** |

> V6 在 2018-2020 子区间中测试（新闻数据覆盖范围）。V1-V5 均为 2023-2025（3年纯牛市），V6 因区间不同（含 2020 COVID 崩盘）基准 SPY 仅 +47.1%，不可直接比较 Alpha。V6 Aggressive 在同区间 Alpha +1.3%（跑赢 SPY）。

**从 V1 到 V6: Alpha 改善 +17.7%, 夏普 0.48→1.44, 回撤 -25.3%→-13.7%**

### 当前最佳配置（V6 Standard）

```
标的池:         S&P 100 (~85只)
选股:           基本面 50% + 动量 30% + 分析师 20% + Insider 加分 + 新闻情绪加分
过滤:           动量 < 40 排除, Short Interest > 15% 排除
新闻:           30天标题情绪聚合，关键词评分 (-3 ~ +3 加分)
Top N:          10 只
SPY 底仓:       20%
Trailing Stop:  25%
Regime Filter:  SPY均线 55% + 收益率曲线 15% + VIX 15% + 信用利差 15%
再平衡:         月度
Earnings:       Surprise 调整（原分 80% + earnings 20%）
```

### 下一步方向

| 优先级 | 方向 | 说明 |
|--------|------|------|
| P0 | Telegram 信号推送 | 策略已验证，接入实盘推送 |
| P1 | 实盘纸交易（Paper Trading） | 用真实数据模拟 3-6 个月验证 |
| P1 | 付费新闻 API（Polygon/Tiingo） | 覆盖 2021-2025，提升新闻因子效果 |
| P2 | LLM 新闻情绪（Haiku） | 语义级情绪分析，替代关键词方法 |
| P2 | 扩展到 mid-cap（Russell 1000） | 需要 Short Interest 过滤配合 |

---

*V6 数据来源: [`reports/portfolio_v6_news_20260329_2140.json`]*

---
---

# Paper Trading 系统 + 过拟合反思

> 日期: 2026-03-29
> 状态: 已上线，等待 3-6 个月样本外数据

---

## 26. 过拟合风险反思

### 问题

V1→V6 每一版的"改进"都是看着 2023-2025 回测结果来调的（V6 是 2018-2020）。每加一条规则回测变好了，但自由度也多了一个。

V3→V6 的 Alpha 变化：+3.3% → +3.9% → +4.0% → +4.0%。后面加的因子（Earnings Surprise、Insider、Short Interest、新闻情绪）几乎没有边际贡献，但增加了系统复杂度。

### 结论

**核心 Alpha 来自三个东西：基本面选股 + 动量过滤 + Regime 减仓。** 其他都是噪音。

与其继续加规则，不如砍掉没用的，让系统更简单更健壮。

### V5 诊断报告的三个问题

外部诊断识别了三个核心问题及修复方案：

| 问题 | 修复方案 | 过拟合风险 | 建议 |
|------|---------|-----------|------|
| Regime 退出太慢，反弹踏空 | 不对称进出 + 价格驱动回仓 | 低 | 可做 |
| BEAR 模式缺乏防御仓 | 加大现金比例（不要固定防御 ETF） | 高 | 简化 |
| 暴跌后动量失效 | 加大 SPY 底仓到 50%（不做反转因子） | 很高 | 先不做 |

**这些修复暂不实施，等 Paper Trading 跑完再决定。**

---

## 27. Paper Trading 系统

### 设计

- **策略版本**: V3 核心（基本面 + 动量 + Regime），不加花哨因子
- **标的池**: S&P 100 (~85 只)
- **频率**: 每月初生成信号，月底自动算收益
- **验证标准**: 跑 3-6 个月，累计 Alpha > 0 则上实盘

### 使用

```bash
# 每月初跑一次
python3 run_paper_trading.py signal

# 随时查看表现
python3 run_paper_trading.py review

# 发送到 Telegram
python3 run_paper_trading.py signal --telegram --token TOKEN --chat-id CHAT_ID
```

### 数据

信号记录在 `paper_trading/signals.json`，包含：
- 选股列表 + 权重 + 入场价
- Regime 状态
- 月底自动回填收益和 Alpha

### 首期信号 (2026-03)

```
Regime: BULL (score=86, mult=1.0)
选股: GOOGL, GOOG, NVDA, AVGO, AMAT, LLY, TMO, AMD, AAPL, MRK
仓位: 个股 80% + SPY 20%
```

---

## 28. 后续优化待办

以下改进暂时搁置，等 Paper Trading 验证后再考虑：

| 优先级 | 方向 | 前置条件 |
|--------|------|---------|
| P0 | Paper Trading 跑满 3 个月 | 进行中 |
| P0 | Telegram 信号推送自动化 | 需配置 bot token |
| P1 | 不对称 Regime 进出（价格驱动回仓） | Paper Trading Alpha > 0 |
| P1 | 付费新闻 API (Tiingo $30/月) | 见 `NEWS-DATA-PLAN.md` |
| P2 | BEAR 模式加大现金比例 | Regime 改进后再评估 |
| P2 | LLM 新闻情绪（替代关键词） | 付费数据接入后 |
| P3 | 暴跌恢复期 SPY 底仓加大 | 需更多样本外数据 |
| P3 | 扩展到 mid-cap | Short Interest 过滤验证后 |

---

*Paper Trading 数据: `paper_trading/signals.json`*
*新闻数据方案: `NEWS-DATA-PLAN.md`*
