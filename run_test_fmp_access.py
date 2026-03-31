"""
FMP API 访问权限测试脚本

测试当前 API Key 能访问哪些端点，确认升级前后的权限差异。
每个端点只打一次 API（测试用），不会消耗大量配额。

使用方式：
    python run_test_fmp_access.py --api-key YOUR_KEY
"""

import requests
import argparse
import os
import json
from datetime import datetime

BASE = "https://financialmodelingprep.com/api"
TEST_TICKER = "AAPL"

# 按类别定义所有要测试的端点
ENDPOINTS = [
    # ── 核心回测数据 ──────────────────────────────────────────────
    {
        "category": "核心回测数据",
        "name": "S&P500 历史成分股变动",
        "url": f"{BASE}/v3/historical/sp500_constituent",
        "params": {},
        "check": lambda r: isinstance(r, list) and len(r) > 0,
    },
    {
        "category": "核心回测数据",
        "name": "季度利润表",
        "url": f"{BASE}/v3/income-statement/{TEST_TICKER}",
        "params": {"period": "quarter", "limit": 2},
        "check": lambda r: isinstance(r, list) and len(r) > 0,
    },
    {
        "category": "核心回测数据",
        "name": "季度资产负债表",
        "url": f"{BASE}/v3/balance-sheet-statement/{TEST_TICKER}",
        "params": {"period": "quarter", "limit": 2},
        "check": lambda r: isinstance(r, list) and len(r) > 0,
    },
    {
        "category": "核心回测数据",
        "name": "季度现金流量表",
        "url": f"{BASE}/v3/cash-flow-statement/{TEST_TICKER}",
        "params": {"period": "quarter", "limit": 2},
        "check": lambda r: isinstance(r, list) and len(r) > 0,
    },
    {
        "category": "核心回测数据",
        "name": "季度关键指标（PE/ROE等）",
        "url": f"{BASE}/v3/key-metrics/{TEST_TICKER}",
        "params": {"period": "quarter", "limit": 2},
        "check": lambda r: isinstance(r, list) and len(r) > 0,
    },
    {
        "category": "核心回测数据",
        "name": "批量季度财务数据（Bulk）",
        "url": f"{BASE}/v4/financial-statements-bulk",
        "params": {"year": 2023, "period": "Q4"},
        "check": lambda r: isinstance(r, list) and len(r) > 0,
    },
    # ── 现有因子升级 ──────────────────────────────────────────────
    {
        "category": "现有因子升级",
        "name": "盈利惊喜历史",
        "url": f"{BASE}/v3/earnings-surprises/{TEST_TICKER}",
        "params": {},
        "check": lambda r: isinstance(r, list) and len(r) > 0,
    },
    {
        "category": "现有因子升级",
        "name": "分析师评级历史",
        "url": f"{BASE}/v3/analyst-stock-recommendations/{TEST_TICKER}",
        "params": {"limit": 5},
        "check": lambda r: isinstance(r, list) and len(r) > 0,
    },
    {
        "category": "现有因子升级",
        "name": "分析师价格目标历史",
        "url": f"{BASE}/v4/price-target",
        "params": {"symbol": TEST_TICKER},
        "check": lambda r: isinstance(r, list) and len(r) > 0,
    },
    {
        "category": "现有因子升级",
        "name": "内部人交易历史",
        "url": f"{BASE}/v4/insider-trading",
        "params": {"symbol": TEST_TICKER, "limit": 5},
        "check": lambda r: isinstance(r, list) and len(r) > 0,
    },
    # ── 新信号（意外收获）────────────────────────────────────────
    {
        "category": "新信号",
        "name": "国会议员交易披露",
        "url": f"{BASE}/v4/senate-trading",
        "params": {"symbol": TEST_TICKER},
        "check": lambda r: isinstance(r, list) and len(r) > 0,
    },
    {
        "category": "新信号",
        "name": "机构持仓 13F（最新）",
        "url": f"{BASE}/v3/institutional-holder/{TEST_TICKER}",
        "params": {},
        "check": lambda r: isinstance(r, list) and len(r) > 0,
    },
    {
        "category": "新信号",
        "name": "机构持仓 13F（历史变动）",
        "url": f"{BASE}/v4/institutional-ownership/symbol-ownership",
        "params": {"symbol": TEST_TICKER, "includeCurrentQuarter": "false", "limit": 3},
        "check": lambda r: isinstance(r, list) and len(r) > 0,
    },
    {
        "category": "新信号",
        "name": "做空数据（Short Interest）",
        "url": f"{BASE}/v4/short-selling",
        "params": {"symbol": TEST_TICKER},
        "check": lambda r: isinstance(r, list) and len(r) > 0,
    },
    # ── 宏观 / Regime Filter ──────────────────────────────────────
    {
        "category": "宏观/Regime Filter",
        "name": "国债收益率曲线历史",
        "url": f"{BASE}/v4/treasury",
        "params": {"from": "2024-01-01", "to": "2024-01-31"},
        "check": lambda r: isinstance(r, list) and len(r) > 0,
    },
    {
        "category": "宏观/Regime Filter",
        "name": "宏观经济指标（GDP/CPI等）",
        "url": f"{BASE}/v4/economic",
        "params": {"name": "GDP", "from": "2020-01-01", "to": "2024-01-01"},
        "check": lambda r: isinstance(r, list) and len(r) > 0,
    },
    {
        "category": "宏观/Regime Filter",
        "name": "市场风险溢价",
        "url": f"{BASE}/v4/market_risk_premium",
        "params": {},
        "check": lambda r: isinstance(r, list) and len(r) > 0,
    },
    # ── 财报日历 ──────────────────────────────────────────────────
    {
        "category": "财报日历",
        "name": "财报日历（未来30天）",
        "url": f"{BASE}/v3/earning_calendar",
        "params": {"from": "2025-04-01", "to": "2025-04-30"},
        "check": lambda r: isinstance(r, list) and len(r) > 0,
    },
    {
        "category": "财报日历",
        "name": "历史财报日期（单股）",
        "url": f"{BASE}/v3/historical/earning_calendar/{TEST_TICKER}",
        "params": {"limit": 5},
        "check": lambda r: isinstance(r, list) and len(r) > 0,
    },
]


def test_endpoint(ep: dict, api_key: str) -> dict:
    params = {**ep["params"], "apikey": api_key}
    try:
        r = requests.get(ep["url"], params=params, timeout=10)
        if r.status_code == 200:
            data = r.json()
            # FMP 有时返回 {"Error Message": "..."}
            if isinstance(data, dict) and "Error Message" in data:
                return {"status": "BLOCKED", "detail": data["Error Message"][:80]}
            ok = ep["check"](data)
            count = len(data) if isinstance(data, list) else "N/A"
            return {"status": "✅ OK", "detail": f"{count} 条记录"}
        elif r.status_code == 403:
            return {"status": "🔒 需升级", "detail": "403 Forbidden"}
        elif r.status_code == 401:
            return {"status": "🔒 需升级", "detail": "401 Unauthorized"}
        else:
            return {"status": f"⚠️  HTTP {r.status_code}", "detail": r.text[:80]}
    except Exception as e:
        return {"status": "❌ 错误", "detail": str(e)[:80]}


def main():
    parser = argparse.ArgumentParser(description="FMP API 访问权限测试")
    parser.add_argument("--api-key", default=os.environ.get("FMP_API_KEY"), help="FMP API Key")
    args = parser.parse_args()

    if not args.api_key:
        print("❌ 请提供 API Key: --api-key YOUR_KEY 或设置 FMP_API_KEY 环境变量")
        return

    print(f"\n{'='*60}")
    print(f"  FMP API 权限测试  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Key: {args.api_key[:8]}{'*'*20}")
    print(f"{'='*60}\n")

    results = []
    current_category = None

    for ep in ENDPOINTS:
        if ep["category"] != current_category:
            current_category = ep["category"]
            print(f"\n── {current_category} {'─'*40}")

        result = test_endpoint(ep, args.api_key)
        status = result["status"]
        detail = result["detail"]
        print(f"  {status:<15}  {ep['name']:<35}  {detail}")
        results.append({**ep, "result": result, "check": None})

    # 汇总
    ok = sum(1 for r in results if "OK" in r["result"]["status"])
    blocked = sum(1 for r in results if "升级" in r["result"]["status"] or "BLOCKED" in r["result"]["status"])
    total = len(results)

    print(f"\n{'='*60}")
    print(f"  结果汇总: ✅ 可访问 {ok}/{total}  |  🔒 需升级 {blocked}/{total}")
    print(f"{'='*60}\n")

    if blocked > 0:
        print("🔒 升级到 Premium 后可解锁的端点：")
        for r in results:
            if "升级" in r["result"]["status"] or "BLOCKED" in r["result"]["status"]:
                print(f"   - {r['name']}")


if __name__ == "__main__":
    main()
