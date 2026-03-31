# FMP Datasource

从 Financial Modeling Prep（Premium 套餐）+ FRED（免费）下载回测所需的全量历史数据。

---

## 快速开始

```bash
cd fmp-datasource
export FMP_API_KEY=你的key

# 全量下载（首次运行，约 40-60 分钟）
python3 run_all.py

# 只下载某一步
python3 run_all.py --step constituents   # Step 1: S&P500 成分股
python3 run_all.py --step fundamentals   # Step 2: 季度基本面
python3 run_all.py --step factors        # Step 3: 因子信号
python3 run_all.py --step macro          # Step 4: 宏观数据
python3 run_all.py --step prices         # Step 5: 历史价格

# 强制重新下载（忽略缓存）
python3 run_all.py --force
python3 run_all.py --step prices --force
```

---

## 文件结构

```
fmp-datasource/
├── fmp_client.py               # 共用 API 客户端（限速、线程锁、重试）
├── download_constituents.py    # Step 1: S&P500 成分股
├── download_fundamentals.py    # Step 2: 季度基本面
├── download_factors.py         # Step 3: 因子信号
├── download_macro.py           # Step 4: 宏观数据
├── download_prices.py          # Step 5: 历史日线价格
├── run_all.py                  # 一键运行全部
└── cache/                      # 本地缓存（全部 parquet 格式）
    ├── sp500_current.parquet
    ├── sp500_historical_changes.parquet
    ├── sp500_pit_index.parquet
    ├── fundamentals_merged.parquet
    ├── factors_merged.parquet
    ├── macro_merged.parquet
    ├── prices_monthly.parquet       ← 月末复权价 + 月度收益率（回测主用）
    ├── prices_merged.parquet        ← 日线全量（备用）
    ├── fundamentals/           # 每只股票一个文件
    ├── earnings/
    ├── analyst_grades/
    ├── insider_trades/
    ├── congressional_trades/
    ├── prices/                 # 每只股票日线一个文件
    └── macro/
```

---

## 下载目标一览

| Step | 数据类型 | 目标数量 | 预计 API 调用 | 预计耗时 |
|------|---------|---------|-------------|---------|
| 1 | S&P500 成分股 | 2 次请求 | ~2 | <1 分钟 |
| 2 | 季度基本面（5类财报） | 1612 只 × 5 端点 | ~8,060 | ~12 分钟 |
| 3 | 因子数据（4类） | 1612 只 × 4 端点 | ~6,448 | ~10 分钟 |
| 4 | 宏观数据 | 8 个序列 | ~20 | ~2 分钟 |
| 5 | 历史日线价格 | 1612 只 × 3 段 | ~4,836 | ~8 分钟 |
| **合计** | | | **~19,366** | **~35 分钟** |

> Premium 上限 750 calls/min，脚本保守用 700。多线程并发，加线程锁防超速。

---

## 数据详情

### Step 1：S&P500 成分股
**目的：修复生存者偏差**

| 文件 | 内容 | 关键用途 |
|------|------|---------|
| `sp500_current.parquet` | 当前 503 只成分股 | 股票池参考 |
| `sp500_historical_changes.parquet` | 1517 条历史变动记录 | 还原任意日期的成分股 |
| `sp500_pit_index.parquet` | 月末成分股表 (date, symbol, in_index) | 回测动态股票池 |

生存者偏差是回测最严重的问题之一。若只用当前成分股，所有被踢出的"失败"公司都不会出现，导致收益虚高。

---

### Step 2：季度基本面
**目的：构建基本面因子，防前视偏差**

每只股票存为独立 parquet，包含以下合并数据（共约 128 列）：

| 来源端点 | 字段（节选） |
|---------|------------|
| income-statement | revenue, netIncome, eps, ebitda, grossProfit |
| balance-sheet-statement | totalDebt, stockholdersEquity, netDebt, cash |
| cash-flow-statement | freeCashFlow, operatingCashFlow, capex |
| key-metrics | peRatio, evToEbitda, returnOnEquity, priceToBookRatio |
| ratios | grossProfitMargin, debtEquityRatio, currentRatio |

**重要**：所有数据以 `filingDate`（SEC 提交日）为时间戳，而非 `date`（季末日）。
季报通常在季末后 30-90 天才提交，用错时间戳会引入严重前视偏差。

---

### Step 3：因子信号
**目的：多因子选股信号**

| 数据 | 端点 | 信号含义 |
|------|------|---------|
| 盈利惊喜 | `earnings` | epsActual vs epsEstimated，捕捉 PEAD 效应 |
| 分析师评级 | `grades-historical` | Buy/Hold/Sell 历史，分析师情绪 |
| 内部人交易 | `insider-trading/search` | CEO/CFO 净买入，Form 4 信号 |
| 国会议员交易 | `senate-trading` / `house-trading` | 参/众两院议员净买卖 |

合并后的 `factors_merged.parquet` 已处理为月度信号：
- `earnings_surprise`：最近季报盈利惊喜幅度
- `analyst_positive_pct`：过去 90 天内正面评级占比
- `analyst_count`：过去 90 天评级数量
- `insider_net_buy_shares`：过去 90 天净买入股数
- `insider_buy_count`：过去 90 天买入笔数
- `congress_net_buy`：过去 180 天净买入次数（国会有 45 天披露延迟）

---

### Step 4：宏观数据
**目的：构建 regime_filter，市场环境判断**

| 数据 | 来源 | 字段 |
|------|------|------|
| 国债收益率曲线 | FMP Premium | year2, year10, year30, spread_10y2y, yield_curve_inverted |
| GDP | FRED（免费） | 季度 GDP，同比增速 |
| CPI | FRED（免费） | 月度通胀率 |
| 联邦基金利率 | FRED（免费） | 货币政策松紧 |
| 失业率 | FRED（免费） | 经济周期判断 |
| 非农就业 | FRED（免费） | 月度就业变化 |
| 消费者信心 | FRED（免费） | 密歇根大学指数 |
| 工业生产指数 | FRED（免费） | 经济活动强度 |

合并后的 `macro_merged.parquet` 已计算同比变化率，关键衍生字段：
- `treasury_yield_curve_inverted`：收益率曲线是否倒挂（10y-2y < 0）
- `macro_FEDFUNDS_yoy`：利率同比变化（加息/降息周期）
- `macro_UNRATE_yoy`：失业率变化趋势

---

### Step 5：历史日线价格
**目的：计算动量因子、月度收益，防生存者偏差**

| 文件 | 内容 |
|------|------|
| `prices/{TICKER}.parquet` | 每只股票日线 OHLCV + adjClose（复权价） |
| `prices_monthly.parquet` | 月末复权价 + 月度收益率，回测直接读取 |
| `prices_merged.parquet` | 日线全量合并（备用，约 600 万行） |

覆盖范围：1612 只历史 S&P500 成分股（含已退市）+ SPY benchmark，2010 至今。

**为什么不用 yfinance**：yfinance 无法获取已退市股票数据，会导致生存者偏差重新引入。

**`prices_monthly.parquet` 字段**：
- `date`：月末日期
- `symbol`：股票代码
- `adj_close`：复权收盘价
- `monthly_return`：当月收益率（用上月末价格计算，point-in-time）

---

## 设计原则

### Point-in-Time 防前视偏差
- **成分股**：用 `dateAdded` 还原历史成分，确保回测日只看到当时已知的股票
- **财务数据**：用 `filingDate` 而非 `date`，确保只使用公开后的数据
- **国会交易**：用 `disclosureDate` 而非 `transactionDate`，反映信息实际可用时间
- **价格数据**：月度收益用上月末价格计算，无未来数据泄漏

### 本地缓存与断点续传
- 所有数据下载后存为 parquet，后续回测全离线运行
- 每个 ticker 独立文件：中断后重跑自动跳过已完成的
- 无数据的 ticker 写空占位文件，避免重复请求浪费 API 调用
- 已完成的 Step 自动跳过（Step 1/4 检查文件存在；Step 2/3/5 检查各子目录）

### 速率控制
- Premium 上限 750 calls/min，脚本保守用 700（可通过 `FMP_RATE_LIMIT` 环境变量调整）
- 多线程下载，threading.Lock 保证限速器线程安全
- 遇到 429 自动指数退避重试

---

## 数据来源说明

| 数据类型 | 来源 | 费用 | 备注 |
|---------|------|------|------|
| 财务报表、成分股、因子、价格 | FMP Premium | $69/月（月付） | 一次下完即可取消 |
| 宏观指标（GDP/CPI等） | FRED | 免费 | 美联储官方数据 |

> FMP Premium 不含 bulk 端点和 13F 机构持仓，需 Ultimate（$139/月）。
> 当前方案用多线程逐 ticker 下载解决 bulk 限制，13F 暂缺。
