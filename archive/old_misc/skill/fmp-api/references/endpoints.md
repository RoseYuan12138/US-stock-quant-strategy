# FMP Stable API — Complete Endpoint Reference

Base URL: `https://financialmodelingprep.com/stable`  
Auth: `?apikey=KEY` on every request

---

## 1. Financial Statements

```
GET /stable/income-statement?symbol=X&period=quarter&limit=N
GET /stable/balance-sheet-statement?symbol=X&period=quarter&limit=N
GET /stable/cash-flow-statement?symbol=X&period=quarter&limit=N
```
Key fields: `filingDate` (use for PIT), `date` (quarter end, do NOT use for PIT)

Income: `revenue`, `grossProfit`, `operatingIncome`, `netIncome`, `ebitda`, `eps`, `epsDiluted`  
Balance: `totalAssets`, `totalLiabilities`, `stockholdersEquity`, `totalDebt`, `netDebt`, `cashAndCashEquivalents`  
Cashflow: `operatingCashFlow`, `freeCashFlow`, `capitalExpenditures`, `dividendsPaid`

TTM versions: append `-ttm` to endpoint name, only `symbol` param needed.

---

## 2. Key Metrics & Ratios

```
GET /stable/key-metrics?symbol=X&period=quarter&limit=N
GET /stable/ratios?symbol=X&period=quarter&limit=N
```
Key metrics: `peRatio`, `priceToBookRatio`, `evToEbitda`, `returnOnEquity`, `returnOnAssets`,
`debtToEquity`, `freeCashFlowYield`, `earningsYield`, `marketCap`, `enterpriseValue`

Ratios: `grossProfitMargin`, `operatingProfitMargin`, `netProfitMargin`, `currentRatio`, `debtEquityRatio`

---

## 3. S&P 500 Constituents

```
GET /stable/sp500-constituent               # current ~503 members
GET /stable/historical-sp500-constituent    # 1517 historical changes
GET /stable/nasdaq-constituent
GET /stable/historical-nasdaq-constituent
```

Historical fields: `dateAdded`, `symbol`, `date` (removal), `removedTicker`, `reason`

Point-in-time:
```python
def get_sp500_at_date(changes, target_date):
    universe = set()
    for row in changes:
        if row.get("dateAdded","") <= target_date and row.get("symbol"):
            universe.add(row["symbol"])
        if row.get("date","") <= target_date and row.get("removedTicker"):
            universe.discard(row["removedTicker"])
    return universe
```

---

## 4. Earnings

```
GET /stable/earnings?symbol=X&limit=N
GET /stable/earnings-calendar?from=DATE&to=DATE
GET /stable/analyst-estimates?symbol=X&period=quarter&limit=N
```
Earnings fields: `date`, `epsActual`, `epsEstimated`, `revenueActual`, `revenueEstimated`  
Surprise = `(epsActual - epsEstimated) / abs(epsEstimated)`

---

## 5. Analyst Ratings & Price Targets

```
GET /stable/grades-historical?symbol=X&limit=N
GET /stable/ratings-historical?symbol=X&limit=N
GET /stable/price-target-consensus?symbol=X
GET /stable/price-target-summary?symbol=X
```
Grades fields: `date`, `gradingCompany`, `previousGrade`, `newGrade`  
Ratings fields: `date`, `rating` (S/A/B/C/D/F), `ratingScore` (1–5), `ratingRecommendation`  
Price target: `targetHigh`, `targetLow`, `targetConsensus`, `targetMedian`

---

## 6. Insider Trading

**CORRECT path:**
```
GET /stable/insider-trading/search?symbol=X&limit=N
```
Wrong: `/stable/insider-trading?symbol=X` → returns `[]`

Fields: `filingDate`, `transactionDate`, `reportingName`, `typeOfOwner`,
`transactionType` (P-Purchase/S-Sale/A-Award/D-Disposition/G-Gift),
`securitiesTransacted`, `price`, `securitiesOwned`, `acquisitionOrDisposition`

Latest across all stocks:
```
GET /stable/insider-trading/latest?date=YYYY-MM-DD&limit=100
GET /stable/insider-trading/statistics?symbol=X
```

---

## 7. Congressional Trading

```
GET /stable/senate-trades?symbol=X
GET /stable/house-trades?symbol=X
GET /stable/senate-latest?page=0&limit=100
GET /stable/house-latest?page=0&limit=100
GET /stable/senate-trades-by-name?name=Nancy+Pelosi
GET /stable/house-trades-by-name?name=Nancy+Pelosi
```

Fields: `disclosureDate` (use for PIT), `transactionDate`, `firstName`, `lastName`,
`office`, `type` (purchase/sale/exchange), `amount` (e.g. "$1,001 - $15,000"), `link`

---

## 8. Treasury Rates

```
GET /stable/treasury-rates?from=YYYY-MM-DD&to=YYYY-MM-DD
```
Daily data. Fields: `date`, `month1`, `month2`, `month3`, `month6`,
`year1`, `year2`, `year5`, `year10`, `year20`, `year30`

Inversion signal: `year10 - year2 < 0`

---

## 9. Economic Calendar

```
GET /stable/economic-calendar?from=YYYY-MM-DD&to=YYYY-MM-DD
```
Fields: `date`, `event`, `previous`, `estimate`, `actual`, `impact` (Low/Medium/High)

Note: Specific indicators (GDP, CPI, etc.) return empty on Premium.  
Use FRED instead: `https://fred.stlouisfed.org/graph/fredgraph.csv?id=GDP`

FRED series IDs: `GDP`, `CPIAUCSL`, `FEDFUNDS`, `UNRATE`, `PAYEMS`, `UMCSENT`
