# 代码库整理计划

## 核心思路
用户只想保留 V7 策略。V7 目前是一个 1456 行的独立脚本 (`v7_sector_neutral.py`)，
不依赖现有的 `strategy/` `backtest/` 模块。整理分两步：归档旧代码 → 重构 V7 为模块化结构。

## 第一步：归档（移到 archive/）

### 归档的 Python 脚本：
- `run_portfolio_validation_v3.py` — V3 回测（不再使用）
- `run_portfolio_validation_v6.py` — V6 回测（不再使用）
- `run_oos_test.py` — OOS 测试（基于旧策略）
- `run_backtest_2025_2026.py` — 旧策略的近期回测
- `run_paper_trading.py` — 基于 V5/V6 的模拟交易
- `run_download_fnspid.py` — HuggingFace 新闻数据下载（V7 不用）
- `run_test_fmp_access.py` — FMP API 测试工具（一次性）

### 归档的文档：
- `STRATEGY-REPORT.md` (60KB) — V1-V6 的详细报告
- `STRATEGY-GUIDE.md` — V1-V6 版本对比
- `STRATEGY-EVALUATION.md` — 旧策略评估
- `PROGRESS.md` — 旧进度记录
- `baseline_metrics.md` — yfinance 基准指标
- `datasource_switch_analysis.md` — 数据源切换分析（已完成）
- `NEWS-DATA-PLAN.md` — 新闻数据计划（V7 不用新闻因子）
- `architecture.mmd` — 旧架构图

### 合并 trash/ → archive/：
- 将现有 `trash/` 内容也移入 `archive/`，统一管理

## 第二步：重构 V7 为模块化

将 `v7_sector_neutral.py`（1456 行）拆分为：

```
stock-quant/
├── data/
│   ├── fmp_loader.py          # FMP parquet 数据加载（从 v7 提取）
│   ├── fmp_data_manager.py    # FMP 数据下载管理（保留）
│   ├── fmp_constituent_fetcher.py  # 成分股获取（保留）
│   └── fmp_fundamental_fetcher.py  # 基本面获取（保留）
│
├── strategy/
│   ├── factors.py             # 因子计算（SUE, analyst momentum, accruals, insider, momentum）
│   ├── portfolio.py           # 组合构建（sector-neutral, IC-weighted）
│   └── regime.py              # 市场状态（保留现有 regime_filter 核心逻辑）
│
├── backtest/
│   └── engine.py              # 回测引擎（从 v7 提取，支持 bi-weekly）
│
├── fmp-datasource/            # FMP 数据下载工具（保留不动）
│
├── config/
│   └── config.yaml            # 策略参数（更新为 V7 参数）
│
├── reports/                   # 回测结果（保留）
│
├── run_backtest.py            # 主回测入口
├── run_daily_signals.py       # 每日信号（更新为 V7 逻辑）
├── run_download_fmp_data.py   # 数据下载入口（保留）
│
├── archive/                   # 归档旧代码和文档
│
├── fmp_vs_yfinance_comparison.md  # 更新为当前状态
├── README.md                  # 重写为 V7 策略文档
└── requirements.txt
```

### 归档的 data/ 模块（V7 不再使用）：
- `data/data_fetcher.py` — yfinance 价格获取
- `data/fundamental_fetcher.py` — yfinance 基本面
- `data/historical_fundamentals.py` — 旧历史基本面
- `data/historical_news.py` — 新闻数据
- `data/live_news_sentiment.py` — 实时新闻情绪

### 归档的 strategy/ 模块（V7 有自己的实现）：
- `strategy/portfolio_strategy.py` — V3-V6 组合策略
- `strategy/momentum.py` — 旧动量（V7 有新实现）
- `strategy/earnings_surprise.py` — 旧 SUE（V7 有新实现）
- `strategy/insider_signal.py` — 旧内部人（V7 有新实现）

## 第三步：更新文档
- 更新 `fmp_vs_yfinance_comparison.md`（反映 V7 全面使用 FMP）
- 重写 `README.md`（V7 策略说明、使用方法、架构）

## 执行顺序
1. 归档旧文件 → archive/
2. 拆分 v7_sector_neutral.py 为模块
3. 更新 run 脚本
4. 更新文档
5. 验证运行
