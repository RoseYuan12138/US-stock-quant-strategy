# 新闻数据方案

> 日期: 2026-03-29
> 状态: 待执行

---

## 当前问题

V6 新闻因子用的 ashraq/financial-news 只有 4 万条标题，覆盖 61/85 ticker，到 2020 年截止。回测增量只有 +0.77% Alpha，数据太差是主因。

---

## 三档方案

### 省钱档 — $0/月（推荐先试）

| 数据源 | 用途 | 覆盖 |
|--------|------|------|
| **FNSPID** (HuggingFace) | 回测 | 1999-2023, 1570万条, S&P 500 |
| **SEC EDGAR 8-K** | 重大事件补充 | 全历史, 免费 |
| **Finnhub 免费版** | 实时信号 | 60次/分, 只有近期 |

- FNSPID: 约 13 分钟下完, ~500MB-1GB
- 缺点: 2024-2025 无新闻覆盖（因子自动降级为中性）

### 性价比档 — $30/月

| 数据源 | 费用 | 用途 |
|--------|------|------|
| **Tiingo Power** | $30/月 | 历史 + 实时 + 情绪, 一站搞定 |

- 15+ 年历史, 2000万+ 文章
- 自带情绪标签 + ticker 映射
- 有 Python SDK (`pip install tiingo`)
- 覆盖 2018-2025 全部回测 + Telegram 实时推送
- 注册: https://www.tiingo.com/about/pricing

### 豪华档 — $60/月

| 数据源 | 费用 | 用途 |
|--------|------|------|
| **Tiingo Power** | $30/月 | 深历史回测 (15年+) |
| **Polygon Starter** | $29/月 | LLM 级实时情绪 |

- 两个源交叉验证, 质量最高
- Polygon 的 per-ticker LLM sentiment 是业界最好的之一
- 实时用 Polygon, 回测用 Tiingo

---

## 主要 API 对比

| | Tiingo | Polygon | Finnhub | Alpha Vantage | MarketAux |
|---|---|---|---|---|---|
| 月费 | $30 | $29 | $50+ | $50 | $29 |
| 历史深度 | **15年+** | 几年(不明确) | 不明确 | 不明确 | 不明确 |
| 自带情绪 | 有 | 有(LLM级) | 有(聚合) | 有 | 有(实体级) |
| 文章数量 | **2000万+** | 未披露 | 未披露 | 200条/次上限 | 未披露 |
| Python SDK | 有 | 有 | 有 | 无 | 无 |
| 实时推送 | 有 | WebSocket | WebSocket | 无 | 无 |
| 适合回测 | **最佳** | 良好 | 一般 | 差 | 一般 |

---

## 执行计划

1. **先下载 FNSPID**（免费, 13分钟）→ 跑 2018-2023 回测看效果
2. 如果 Alpha 提升明显 → 买 Tiingo $30/月补齐 2024-2025
3. 如果要做 Telegram 实时推送 → Finnhub 免费版先顶着, 不够再加 Tiingo/Polygon

---

## 下载命令

```bash
cd /Users/minicat/.openclaw/yuancuihua-workspace/stock-quant
python3 run_download_fnspid.py
```

脚本位置: `run_download_fnspid.py`（见下方）
