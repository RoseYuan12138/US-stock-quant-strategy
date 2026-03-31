# 数据源切换分析报告：yfinance → FMP

> 生成日期：2026-03-30
> 项目路径：`/Users/minicat/.openclaw/yuancuihua-workspace/stock-quant`

---

## 一、yfinance 使用全景

### 1.1 依赖文件汇总

| 文件 | import 行 | 使用的 API |
|------|-----------|------------|
| `data/data_fetcher.py` | L12 | `yf.download()` |
| `data/fundamental_fetcher.py` | L11 | `yf.Ticker().info` |
| `data/historical_fundamentals.py` | L18 | `yf.Ticker().quarterly_income_stmt` / `.quarterly_balance_sheet` / `.history()` / `.info` |
| `strategy/earnings_surprise.py` | L16 | `yf.Ticker().earnings_dates` |
| `strategy/insider_signal.py` | L17 | `yf.Ticker().insider_transactions` |
| `strategy/regime_filter.py` | （间接） | 通过 `DataFetcher` 拉取 `^TNX, ^IRX, ^VIX, HYG, LQD` |
| `run_oos_test.py` | L13 | 直接调用 `yf.download()` |

**结论：系统 100% 依赖 yfinance，没有任何 FMP 代码。**
项目里的 `.parquet` 文件是 **HuggingFace FNSPID 新闻数据集**（1500万条财经新闻），与 FMP 无关。

---

### 1.2 各模块具体用法

#### `data/data_fetcher.py` — 日线价格

```python
# L95-96
data = yf.download(ticker, start=start_date, end=end_date,
                   progress=False, interval='1d')
# 保留列：['Open', 'High', 'Low', 'Close', 'Volume']
# 缓存：./data/cache/{TICKER}.csv
```

#### `data/fundamental_fetcher.py` — 基本面快照（40+ 字段）

```python
# L59-60
stock = yf.Ticker(ticker)
info  = stock.info   # 返回大字典
```

提取字段（按评分维度分组）：

| 维度（权重） | 字段 |
|-------------|------|
| 估值（30%） | `trailingPE, forwardPE, priceToBook, priceToSalesTrailing12Months, pegRatio, enterpriseToEbitda` |
| 质量（25%） | `profitMargins, operatingMargins, returnOnEquity, returnOnAssets` |
| 成长（20%） | `revenueGrowth, earningsGrowth, earningsQuarterlyGrowth` |
| 分析师（15%） | `recommendationKey, recommendationMean, targetMeanPrice, targetLowPrice, targetHighPrice, numberOfAnalystOpinions` |
| 财务健康（10%） | `debtToEquity, currentRatio, quickRatio, totalCashPerShare, beta, shortPercentOfFloat` |
| 元数据 | `currentPrice, marketCap, sector, industry, dividendYield, payoutRatio` |

缓存：`./data/cache/fundamentals/{TICKER}.json`，TTL 24小时

#### `data/historical_fundamentals.py` — 历史季报（回测核心）

```python
# L127-141
stock = yf.Ticker(ticker)
income_stmt   = stock.quarterly_income_stmt    # 季度损益表
balance_sheet = stock.quarterly_balance_sheet  # 季度资产负债表
price_hist    = stock.history(period="max", interval="1d")
sector        = stock.info.get("sector")
```

提取字段：

| 报表 | 字段 |
|------|------|
| 损益表 | `Net Income, Total Revenue, Operating Income, Diluted Average Shares` |
| 资产负债表 | `Stockholders Equity, Total Debt, Total Assets` |
| 价格 | `Close`（用于计算当季 PE） |

计算得出：`pe_ratio, profit_margin, operating_margin, roe, debt_to_equity, revenue_growth`
缓存：`./data/cache/hist_fundamentals/{TICKER}.json`，TTL 7天
**重要**：内置 60 天滞后防止前视偏差

#### `strategy/earnings_surprise.py` — 财报惊喜因子

```python
# 通过 yf.Ticker().earnings_dates 获取
# 字段：date, eps_actual, eps_estimate, surprise_pct, beat(bool)
# 评分：连续超预期 → +8 分加成
# 缓存：./data/cache/earnings/{TICKER}.json，TTL 7天
```

#### `strategy/insider_signal.py` — 内部人信号因子

```python
# 通过 yf.Ticker().insider_transactions 获取
# 字段：date, relation, shares, value, transaction_type
# 评分：90天内3+人集中买入 → +8 分；单人买入 → +3~5 分
# 缓存：./data/cache/insider/{TICKER}.json，TTL 7天
```

#### `strategy/regime_filter.py` — 宏观市场状态

通过 `DataFetcher`（即 yfinance）拉取 5 个宏观 ticker 的日线数据：

| Ticker | 含义 | 用途 |
|--------|------|------|
| `^TNX` | 10年期国债收益率 | 收益率曲线 |
| `^IRX` | 13周国债收益率 | 收益率曲线 |
| `^VIX` | 波动率指数 | 风险信号 |
| `HYG` | 高收益债 ETF | 信用利差 |
| `LQD` | 投资级债 ETF | 信用利差 |

输出市场状态：`BULL / CAUTION / BEAR / RECOVERY`

---

## 二、数据流全链路

```
yfinance
  ├── yf.download(OHLCV)         ──→ DataFetcher
  │                                    ├──→ MomentumScorer (6个月动量, 200日均线)
  │                                    └──→ RegimeFilter (^VIX, ^TNX 等宏观)
  │
  ├── yf.Ticker().info            ──→ FundamentalFetcher → ValueScreener (评分0-100)
  │
  ├── yf.Ticker().quarterly_*     ──→ HistoricalFundamentalFetcher
  │   + .history()                      └──→ 历史季报评分（回测专用，防前视）
  │
  ├── yf.Ticker().earnings_dates  ──→ EarningsSurpriseScorer (财报惊喜加分)
  │
  └── yf.Ticker().insider_*       ──→ InsiderSignalScorer (内部人信号加分)
                                              ↓
                                   PortfolioStrategy.select_stocks()
                                   combined = fundamental×50% + momentum×30%
                                            + analyst×20% + earnings_bonus
                                            + insider_bonus + news_bonus
                                              ↓
                                   PortfolioBacktester.run()
                                   每月再平衡 + 每日追踪止损
```

---

## 三、FMP 替代可行性分析

### 3.1 逐模块对比

| 模块 | 当前 yfinance API | FMP 对应端点 | 可替代性 | 改动量 |
|------|------------------|-------------|---------|--------|
| `data_fetcher.py` | `yf.download()` OHLCV | `/historical-price-full/{ticker}` | ✅ 完全替代 | **小** |
| `historical_fundamentals.py` | `.quarterly_income_stmt` | `/income-statement?period=quarter` | ✅ 完全替代 | **小-中** |
| `historical_fundamentals.py` | `.quarterly_balance_sheet` | `/balance-sheet-statement?period=quarter` | ✅ 完全替代 | **小-中** |
| `earnings_surprise.py` | `.earnings_dates` | `/earnings-surprises/{ticker}` | ✅ 完全替代 | **小** |
| `insider_signal.py` | `.insider_transactions` | `/insider-trading?symbol={ticker}` | ✅ 完全替代，且数据更深 | **小** |
| `fundamental_fetcher.py` | `.info`（40+字段单次返回） | 需合并 `/key-metrics` + `/financial-ratios` + `/analyst-estimates` | ⚠️ 需组合多端点 | **中-大** |
| `regime_filter.py` | `^VIX, ^TNX, HYG, LQD` | FMP 有经济指标，但 VIX/ETF 价格覆盖不确定 | ❓ 需核实 | **中** |

### 3.2 风险点详细说明

**风险1：`fundamental_fetcher.py` 字段映射复杂**

yfinance `.info` 一次调用返回所有字段。FMP 需要：
- `/key-metrics` → PE、PB、ROE、ROA 等
- `/financial-ratios` → profit margin、D/E、current ratio 等
- `/analyst-estimates` → 分析师目标价、评级
- `/profile` → sector、industry、beta

当前代码的 `ValueScreener.screen_universe()` 直接消费这个字典结构，字段名也不同（FMP 用 `priceEarningsRatio` vs yfinance 的 `trailingPE`）。

**风险2：`regime_filter.py` 的宏观 ticker**

`^VIX` 是 CBOE 指数，`HYG/LQD` 是 ETF。FMP 主要覆盖股票和加密货币，这几个 ticker 的可用性需要验证。最坏情况是这个模块保留 yfinance 或换用 FRED API（Federal Reserve，免费、稳定）。

**风险3：`historical_fundamentals.py` 的 DataFrame 结构**

yfinance 返回的季报是以**财务项目为行、日期为列**的 DataFrame：

```
                        2024-09-30  2024-06-30  ...
Net Income              12,345,678   9,876,543
Total Revenue           89,012,345  78,901,234
```

FMP 返回的是**每季度一条记录的 JSON 列表**，结构完全不同，需要重写解析逻辑（但评分计算逻辑不变）。

---

## 四、具体切换方案

### 总体策略：适配器模式，分步替换

在每个 fetcher 类内部做数据源切换，对外接口（方法签名、返回字段名）保持不变，**strategy/ 和 backtest/ 层零改动**。

---

### Step 1：价格数据（`data/data_fetcher.py`）— 改动最小

只替换 `_fetch_from_api()` 私有方法，缓存逻辑、批量拉取全部保留。

```python
# data/data_fetcher.py

import requests

FMP_API_KEY = os.getenv("FMP_API_KEY")

class DataFetcher:
    def _fetch_from_api(self, ticker, start_date, end_date):
        url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{ticker}"
        resp = requests.get(url, params={
            "from": start_date, "to": end_date, "apikey": FMP_API_KEY
        })
        raw = resp.json().get("historical", [])
        df = pd.DataFrame(raw)
        df = df.rename(columns={
            "date": "Date", "open": "Open", "high": "High",
            "low": "Low",   "close": "Close", "volume": "Volume"
        })
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date").sort_index()
        return df[["Open", "High", "Low", "Close", "Volume"]]
```

---

### Step 2：历史季报（`data/historical_fundamentals.py`）— 重写解析逻辑

替换 `load_ticker()` 中的数据获取部分，`get_score_at_date()` / `get_scores_timeseries()` / 60天滞后逻辑全部不变。

```python
# data/historical_fundamentals.py

def _fetch_quarterly_data(self, ticker: str) -> dict:
    """替换 yfinance 季报拉取，改用 FMP"""
    base = "https://financialmodelingprep.com/api/v3"
    key  = {"apikey": FMP_API_KEY, "period": "quarter", "limit": 20}

    income  = requests.get(f"{base}/income-statement/{ticker}",        params=key).json()
    balance = requests.get(f"{base}/balance-sheet-statement/{ticker}", params=key).json()
    prices  = requests.get(
        f"{base}/historical-price-full/{ticker}",
        params={"apikey": FMP_API_KEY}
    ).json().get("historical", [])

    quarters = []
    for inc, bal in zip(income, balance):
        quarters.append({
            "date":             inc["date"],
            "net_income":       inc["netIncome"],
            "revenue":          inc["revenue"],
            "operating_income": inc["operatingIncome"],
            "shares":           inc.get("weightedAverageShsOutDil", 1),
            "equity":           bal["totalStockholdersEquity"],
            "total_debt":       bal.get("totalDebt", 0),
            "total_assets":     bal["totalAssets"],
        })

    price_map = {p["date"]: p["close"] for p in prices}
    return {"quarters": quarters, "price_map": price_map}
```

---

### Step 3：财报惊喜（`strategy/earnings_surprise.py`）— 改动最小

```python
# strategy/earnings_surprise.py

def _fetch_earnings_fmp(self, ticker: str) -> list:
    url = f"https://financialmodelingprep.com/api/v3/earnings-surprises/{ticker}"
    data = requests.get(url, params={"apikey": FMP_API_KEY}).json()
    results = []
    for item in data:
        actual   = item.get("actualEarningResult")
        estimate = item.get("estimatedEarning")
        if actual is None or estimate is None or estimate == 0:
            continue
        surprise_pct = (actual - estimate) / abs(estimate) * 100
        results.append({
            "date":         item["date"],
            "eps_actual":   actual,
            "eps_estimate": estimate,
            "surprise_pct": surprise_pct,
            "beat":         actual > estimate,
        })
    return results
```

评分逻辑（连续超预期、时间衰减）完全不变。

---

### Step 4：内部人信号（`strategy/insider_signal.py`）— 字段映射

```python
# strategy/insider_signal.py

def _fetch_insider_fmp(self, ticker: str) -> pd.DataFrame:
    url = "https://financialmodelingprep.com/api/v4/insider-trading"
    data = requests.get(url, params={
        "symbol": ticker, "apikey": FMP_API_KEY
    }).json()

    rows = []
    for item in data:
        tx_type = item.get("transactionType", "")
        is_buy  = tx_type in ("P-Purchase", "A-Award")
        rows.append({
            "date":             item["transactionDate"],
            "relation":         item.get("reportingName", ""),
            "shares":           abs(item.get("securitiesTransacted", 0)),
            "value":            abs(item.get("securitiesTransacted", 0))
                                * item.get("price", 0),
            "transaction_type": "buy" if is_buy else "sell",
        })
    return pd.DataFrame(rows)
```

评分逻辑完全不变。FMP 内部人数据历史深度优于 yfinance，此处是净收益。

---

### Step 5：基本面快照（`data/fundamental_fetcher.py`）— 改动最大

需合并 FMP 多个端点，并映射字段名到现有代码期望的格式：

```python
# data/fundamental_fetcher.py

def _fetch_from_fmp(self, ticker: str) -> dict:
    base = "https://financialmodelingprep.com/api/v3"
    p    = {"apikey": FMP_API_KEY}

    metrics = requests.get(f"{base}/key-metrics/{ticker}",                    params={**p, "limit": 1}).json()
    ratios  = requests.get(f"{base}/ratios/{ticker}",                         params={**p, "limit": 1}).json()
    profile = requests.get(f"{base}/profile/{ticker}",                        params=p).json()
    outlook = requests.get(f"{base}/analyst-stock-recommendations/{ticker}",  params=p).json()

    m  = metrics[0] if metrics else {}
    r  = ratios[0]  if ratios  else {}
    pr = profile[0] if profile else {}

    # 映射到现有代码期望的字段名
    return {
        # 估值
        "trailingPE":                   m.get("peRatioTTM"),
        "forwardPE":                    m.get("forwardPE"),           # FMP 可能没有，置 None
        "priceToBook":                  m.get("pbRatioTTM"),
        "priceToSalesTrailing12Months": m.get("priceToSalesRatioTTM"),
        "pegRatio":                     m.get("pegRatioTTM"),
        "enterpriseToEbitda":           m.get("evToEbitda"),
        # 质量
        "profitMargins":                r.get("netProfitMarginTTM"),
        "operatingMargins":             r.get("operatingProfitMarginTTM"),
        "returnOnEquity":               m.get("roeTTM"),
        "returnOnAssets":               m.get("returnOnTangibleAssetsTTM"),
        # 成长
        "revenueGrowth":                m.get("revenueGrowth"),
        "earningsGrowth":               m.get("netIncomeGrowth"),
        "earningsQuarterlyGrowth":      None,                          # FMP 无直接对应
        # 财务健康
        "debtToEquity":                 r.get("debtEquityRatioTTM"),
        "currentRatio":                 r.get("currentRatioTTM"),
        "quickRatio":                   r.get("quickRatioTTM"),
        "totalCashPerShare":            m.get("cashPerShareTTM"),
        "beta":                         pr.get("beta"),
        "shortPercentOfFloat":          None,                          # FMP 无直接对应
        # 分析师
        "recommendationMean":           _parse_fmp_analyst_rating(outlook),
        "targetMeanPrice":              pr.get("dcf"),                 # DCF 估值近似替代
        "targetLowPrice":               None,
        "targetHighPrice":              None,
        "numberOfAnalystOpinions":      len(outlook) if outlook else 0,
        # 元数据
        "currentPrice":                 pr.get("price"),
        "marketCap":                    pr.get("mktCap"),
        "sector":                       pr.get("sector"),
        "industry":                     pr.get("industry"),
        "dividendYield":                pr.get("lastDiv"),             # 需除以当前价
        "payoutRatio":                  r.get("payoutRatioTTM"),
    }


def _parse_fmp_analyst_rating(outlook: list) -> float:
    """将 FMP 分析师推荐转换为 1-5 评分（对齐 yfinance recommendationMean）"""
    if not outlook:
        return 3.0
    latest = outlook[0]
    buy    = latest.get("analystRatingsbuy", 0)
    hold   = latest.get("analystRatingsHold", 0)
    sell   = latest.get("analystRatingsSell", 0) + latest.get("analystRatingsStrongSell", 0)
    total  = buy + hold + sell
    if total == 0:
        return 3.0
    # 1=strong buy, 5=strong sell，与 yfinance 对齐
    return (buy * 1.5 + hold * 3.0 + sell * 4.5) / total
```

**注意**：`ValueScreener` 对 `None` 字段已有容错处理，但需验证 `earningsQuarterlyGrowth` 和 `shortPercentOfFloat` 缺失时的评分影响。

---

### Step 6：宏观指标（`strategy/regime_filter.py`）— 建议换用 FRED API

FMP 对 `^VIX`、`^TNX`、`HYG`、`LQD` 的覆盖不确定，建议替换为 FRED API（免费、官方、稳定）：

| 当前 yfinance Ticker | FRED 系列代码 | 含义 |
|---------------------|--------------|------|
| `^TNX` | `DGS10` | 10年期国债收益率 |
| `^IRX` | `DTB3` | 3个月国债收益率 |
| `^VIX` | `VIXCLS` | VIX 收盘价 |
| `HYG` (信用利差) | `BAMLH0A0HYM2` | 高收益债利差（直接用利差，无需 ETF 价格） |
| `LQD` (信用利差) | `BAMLC0A0CM` | 投资级债利差 |

```python
# strategy/regime_filter.py - 宏观数据获取替代方案

import requests

FRED_API_KEY = os.getenv("FRED_API_KEY")  # 免费注册：fred.stlouisfed.org

def _fetch_fred_series(series_id: str, start_date: str) -> pd.Series:
    url = "https://api.stlouisfed.org/fred/series/observations"
    resp = requests.get(url, params={
        "series_id":      series_id,
        "observation_start": start_date,
        "api_key":        FRED_API_KEY,
        "file_type":      "json",
    })
    obs = resp.json()["observations"]
    s = pd.Series(
        {o["date"]: float(o["value"]) for o in obs if o["value"] != "."},
        name=series_id
    )
    s.index = pd.to_datetime(s.index)
    return s
```

---

## 五、执行路线图

```
阶段一（低风险，建议先做）
  ├── Step 1: data_fetcher.py          价格数据替换    ← 影响最广，先验证数据质量
  └── Step 3: earnings_surprise.py     财报惊喜替换    ← 改动最小，快速验证

阶段二（中等风险）
  ├── Step 2: historical_fundamentals.py   历史季报替换  ← 回测核心，需充分对比测试
  └── Step 4: insider_signal.py            内部人信号替换

阶段三（最后处理）
  ├── Step 5: fundamental_fetcher.py   基本面快照替换  ← 字段最多，需逐一核对空值
  └── Step 6: regime_filter.py         宏观指标        ← 换用 FRED API

验证方法（每阶段）：
  用相同股票池 + 相同时间段各跑一次回测，对比：
  - 信号分布是否一致（评分直方图）
  - 最终选股结果差异
  - 回测指标（Sharpe、最大回撤）是否在合理偏差内
```

---

## 六、总结

| 维度 | 结论 |
|------|------|
| 当前数据源 | **100% yfinance**，7个文件有直接依赖 |
| FMP 现状 | 项目中**零代码**，文档中提到是未来计划 |
| 总体可行性 | ✅ 完全可行，FMP 覆盖绝大部分需求 |
| 核心改动文件 | 6个文件（`data_fetcher`, `fundamental_fetcher`, `historical_fundamentals`, `earnings_surprise`, `insider_signal`, `regime_filter`） |
| strategy/ backtest/ 改动 | **零改动** |
| 最大风险 | `fundamental_fetcher.py` 40+字段映射 + 宏观 ticker 覆盖 |
| FMP 明显优势 | 内部人交易数据更深、数据质量更稳定、不受反爬限制 |
| 唯一保留建议 | 宏观指标建议换 FRED API 而非 FMP |
| 不需要改动的 | `strategy/momentum.py`、`strategy/portfolio_strategy.py`、`backtest/portfolio_backtester.py`、`data/historical_news.py`（FNSPID 已是 parquet） |
