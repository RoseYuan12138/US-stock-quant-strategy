---
name: fmp-api
description: >
  FMP (Financial Modeling Prep) stable API knowledge base. Use this skill whenever
  the user wants to fetch data from Financial Modeling Prep, write any code that
  calls financialmodelingprep.com, asks about FMP endpoints, or needs stock
  fundamentals, insider trading, congressional trading, analyst ratings, earnings,
  macro indicators, or S&P 500 constituent data via API. Also trigger when the user
  mentions "FMP", "Financial Modeling Prep", or is debugging why an FMP API call
  returns empty or 403. This skill prevents wasted time from using deprecated legacy
  endpoints — always load it before writing any FMP code.
---

# FMP Stable API Knowledge Base

## CRITICAL: Legacy Endpoints Are Dead

Accounts created after **August 31, 2025** cannot use `/api/v3/` or `/api/v4/` — they return errors.

**All requests must use `/stable/` prefix:**
```
https://financialmodelingprep.com/stable/<endpoint>?apikey=KEY
```

Auth via query param: `?apikey=YOUR_KEY`  
Auth via header: `apikey: YOUR_KEY`

Rate limits: Free=250/day, Starter=300/min, **Premium=750/min**, Ultimate=3000/min

---

## Quick Reference — Verified Working Endpoints (Premium)

Read `references/endpoints.md` for full parameter details and response fields.

### Core Data
| Data | Endpoint |
|------|----------|
| Income statement | `GET /stable/income-statement?symbol=X&period=quarter&limit=N` |
| Balance sheet | `GET /stable/balance-sheet-statement?symbol=X&period=quarter` |
| Cash flow | `GET /stable/cash-flow-statement?symbol=X&period=quarter` |
| Key metrics | `GET /stable/key-metrics?symbol=X&period=quarter` |
| Financial ratios | `GET /stable/ratios?symbol=X&period=quarter` |
| S&P 500 current | `GET /stable/sp500-constituent` |
| S&P 500 history | `GET /stable/historical-sp500-constituent` |

### Factor Signals
| Signal | Endpoint |
|--------|----------|
| Earnings history | `GET /stable/earnings?symbol=X&limit=N` |
| Analyst grades history | `GET /stable/grades-historical?symbol=X&limit=N` |
| Analyst ratings history | `GET /stable/ratings-historical?symbol=X&limit=N` |
| Price target consensus | `GET /stable/price-target-consensus?symbol=X` |
| **Insider trading** | `GET /stable/insider-trading/search?symbol=X` ⚠️ |
| **Senate trading** | `GET /stable/senate-trades?symbol=X` |
| **House trading** | `GET /stable/house-trades?symbol=X` |

### Macro
| Data | Endpoint |
|------|----------|
| Treasury rates | `GET /stable/treasury-rates?from=YYYY-MM-DD&to=YYYY-MM-DD` |
| Earnings calendar | `GET /stable/earnings-calendar?from=DATE&to=DATE` |

### NOT available on Premium (needs Ultimate)
- Bulk endpoints (`/stable/income-statement-bulk` etc.)
- 13F institutional holdings
- Economic indicators (GDP/CPI) → use FRED free API instead

---

## Common Pitfalls

**⚠️ Insider trading wrong path:**
```python
# WRONG — returns empty []
GET /stable/insider-trading?symbol=AAPL
# CORRECT
GET /stable/insider-trading/search?symbol=AAPL
```

**⚠️ Point-in-time for backtesting:**
- Use `filingDate` field (SEC submission date), NOT `date` (quarter end)
- `filingDate` is 30-90 days after quarter end

**⚠️ No bulk endpoints on Premium:**
- Must loop per ticker, use rate limiter at 750 calls/min

---

## Python Pattern

```python
import requests, os, time

BASE = "https://financialmodelingprep.com/stable"
KEY = os.environ["FMP_API_KEY"]

def fmp_get(endpoint, **params):
    params["apikey"] = KEY
    r = requests.get(f"{BASE}/{endpoint}", params=params)
    r.raise_for_status()
    return r.json()

# S&P 500 constituents at a historical date (point-in-time)
def get_sp500_at_date(target_date: str) -> set:
    changes = fmp_get("historical-sp500-constituent")
    universe = set()
    for row in changes:
        if row.get("dateAdded") and row["dateAdded"] <= target_date:
            universe.add(row["symbol"])
        removal = row.get("date", "")
        if removal and removal <= target_date and row.get("removedTicker"):
            universe.discard(row["removedTicker"])
    return universe

# Congressional trading (Senate + House)
def get_congressional_trades(symbol):
    return fmp_get("senate-trades", symbol=symbol) + fmp_get("house-trades", symbol=symbol)
```

---

See `references/endpoints.md` for complete field listings.
