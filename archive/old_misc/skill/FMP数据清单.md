# FMP Premium 可用数据清单

> 账号类型：Premium（$69/月月付）  
> API Key 存在环境变量 `FMP_API_KEY`  
> 实测日期：2026-03-30

---

## ✅ 可用数据（已验证）

### 一、财务报表（核心回测数据）
| 数据 | 频率 | 历史深度 | 关键字段 |
|------|------|---------|---------|
| 利润表 | 季度/年度 | 30年 | revenue, netIncome, eps, ebitda |
| 资产负债表 | 季度/年度 | 30年 | totalDebt, stockholdersEquity, netDebt |
| 现金流量表 | 季度/年度 | 30年 | freeCashFlow, operatingCashFlow |
| Key Metrics | 季度/年度 | 30年 | peRatio, evToEbitda, returnOnEquity |
| Financial Ratios | 季度/年度 | 30年 | grossProfitMargin, debtEquityRatio |

**重要**：用 `filingDate`（SEC提交日）而非 `date`（季末日）做回测时间轴，避免前视偏差。

---

### 二、指数成分股（修复生存者偏差的关键）
| 数据 | 说明 |
|------|------|
| S&P 500 当前成分股 | 503只，含行业分类 |
| **S&P 500 历史成分变动** | **1517条记录，含加入/移除日期和原因** |
| 纳斯达克当前成分股 | 101只 |
| 纳斯达克历史变动 | 436条记录 |

历史成分股数据可还原任意历史日期的指数成员，是修复生存者偏差的核心数据。

---

### 三、盈利因子
| 数据 | 说明 |
|------|------|
| 历史盈利（含惊喜） | epsActual vs epsEstimated，可计算 earnings surprise |
| 盈利日历 | 未来财报日期，含预期EPS/营收 |
| 分析师盈利预期 | 季度/年度前瞻预测 |

---

### 四、分析师信号
| 数据 | 说明 |
|------|------|
| 评级历史（Buy/Hold/Sell） | 各大投行历史评级变动，含日期和机构名 |
| 量化评分历史 | FMP自有评分体系 S/A/B/C/D/F，含子项得分 |
| 目标价共识 | 高/低/均值/中位数目标价 |
| 目标价详情 | 各机构分别给出的目标价 |

---

### 五、内部人交易（Form 4）
| 数据 | 说明 |
|------|------|
| 内部人交易搜索 | 按股票查询，含买卖类型、金额、持仓变化 |
| 内部人交易统计 | 汇总买卖次数和情绪分 |
| 全市场最新内部人交易 | 按日期查询全市场动态 |

交易类型：P-Purchase（买入）、S-Sale（卖出）、A-Award（授予）、G-Gift（赠予）等

---

### 六、国会议员交易（意外收获）
| 数据 | 说明 |
|------|------|
| 参议员交易记录 | AAPL有322条，历史数据完整 |
| 众议员交易记录 | AAPL有489条，历史数据完整 |
| 按议员姓名查询 | 可追踪特定议员的持仓变动 |

研究表明国会议员的股票收益显著跑赢市场，是可靠的 alpha 信号。

---

### 七、宏观数据
| 数据 | 说明 |
|------|------|
| 国债收益率曲线 | 日频，1月到30年期，2010年至今 |
| 经济日历 | 即将发布的宏观数据及预期值 |

**注意**：具体宏观指标（GDP/CPI/失业率）在 Premium 下返回空，改用下方免费替代。

---

## ❌ Premium 不含（需 Ultimate $139/月）

| 数据 | 影响 | 替代方案 |
|------|------|---------|
| Bulk批量端点 | 下载速度慢（需逐ticker） | 多线程+本地缓存 |
| 机构持仓13F | 无法追踪机构聪明钱 | 暂缺，影响不大 |
| 经济指标（GDP/CPI等） | 宏观因子不完整 | **FRED免费API** |

---

## 🔄 FRED 免费补充宏观数据

```python
# 完全免费，无需注册
import pandas as pd

FRED_SERIES = {
    "GDP":         "https://fred.stlouisfed.org/graph/fredgraph.csv?id=GDP",
    "CPI":         "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL",
    "FEDFUNDS":    "https://fred.stlouisfed.org/graph/fredgraph.csv?id=FEDFUNDS",
    "UNRATE":      "https://fred.stlouisfed.org/graph/fredgraph.csv?id=UNRATE",
    "PAYEMS":      "https://fred.stlouisfed.org/graph/fredgraph.csv?id=PAYEMS",
}

def get_fred(series_id):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    return pd.read_csv(url, parse_dates=["DATE"], index_col="DATE")
```

---

## 数据下载策略

由于 Premium 没有 bulk 端点，需逐 ticker 下载，建议：

1. 先下载 S&P 500 历史成分股（1次API调用）
2. 提取 2010-2025 出现过的所有 ticker（约 600-700 只）
3. 多线程下载每只股票的财务数据（750 calls/min，约需 5-10 分钟）
4. 存为 parquet 格式到本地，之后回测全离线运行

详见 `fmp-api/SKILL.md` 和 `fmp-api/references/endpoints.md`
