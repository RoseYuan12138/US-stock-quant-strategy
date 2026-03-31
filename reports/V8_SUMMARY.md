# V8 Strategy Summary Report

## Architecture: Druckenmiller Attack/Defense

V8 implements a 5-phase system inspired by tradermonty/claude-trading-skills:

### Phase 1: Defense System (MarketTopDetector)
- **Distribution Day Counter**: O'Neil methodology — index drops >= 0.2% on higher volume, 25-day rolling window
- **Market Breadth Analyzer**: % of S&P 500 above 200DMA/50DMA, computed from individual stock prices
- **Market Top Detector**: Composite scoring (distribution 25%, leaders 20%, defensive rotation 15%, breadth 15%, technicals 15%, sentiment 10%) → risk zone (green/yellow/orange/red/critical) → exposure ceiling

### Phase 2: Offense System (FTDDetector)
- **Follow-Through Day state machine**: NO_SIGNAL → CORRECTION → RALLY_ATTEMPT → FTD_WINDOW → FTD_CONFIRMED
- Correction triggers at 7% decline (tuned from original 3%)
- FTD: day 4-10 with >= 1.25% gain + above-average volume
- Quality scoring 0-100 based on gain strength, volume, timing, QQQ confirmation

### Phase 3: Stock Selection
- **VCP Screener**: Minervini Stage 2 template (7-point filter) + progressive contraction detection
- **PEAD Screener**: Post-earnings drift — surprise >= 5%, gap-up >= 3%, volume confirmation
- **Factor subset**: 5 stable factors from V7 (analyst_revision, SUE, accruals, mom_6m, mom_12m_skip1)
- **Signal combination**: factor 40% + VCP 35% + PEAD 25%, with multi-signal bonus

### Phase 4: Position Sizing
- **ATR Position Sizer**: Risk 1% per trade, stop = 2x ATR(14), max 10% per stock, 30% per sector
- **Exposure Coach**: Synthesizes defense + offense → max_exposure (0-1) and action (NEW_ENTRY_ALLOWED / REDUCE_ONLY / CASH_PRIORITY)

### Phase 5: Feedback Loop
- **Signal Postmortem**: Tracks defense/offense signal accuracy, adjusts confidence weights
- **Edge Aggregator**: Tracks which signal sources contribute alpha, dynamically adjusts weights

---

## Backtest Results (First Iteration)

| Regime | Period | V8 Return | SPY Return | Alpha/yr | t-stat | Sharpe | MaxDD |
|--------|--------|-----------|------------|----------|--------|--------|-------|
| Bull   | 2017-2019 | -2.3% | +42.9% | -13.0% | -2.40 | -0.394 | -13.7% |
| Crash  | 2020 | -9.2% | +15.1% | -28.6% | -1.07 | -1.044 | -18.4% |
| Bear   | 2022-2023 | -23.0% | -0.5% | -14.3% | -1.37 | -1.670 | -27.2% |

### V7 Baseline (for comparison)

| Regime | V7 Return | SPY Return | Alpha/yr | Sharpe |
|--------|-----------|------------|----------|--------|
| Bull   | +36.2% | +42.9% | -1.5% | 0.52 |
| Crash  | +6.4% | +15.1% | -9.0% | 0.22 |
| Bear   | -19.2% | -0.5% | -11.6% | -1.11 |

---

## Diagnosis: Why V8 Underperforms V7

### Root Cause: Stock Selection Quality
1. **Factor composite IC near zero**: The 5 "stable" factors still have IC close to 0 (composite_z IC: -0.006 to +0.003). This means factor-based picks are essentially random.
2. **VCP/PEAD too selective**: In any given rebalance, VCP finds ~5-15 candidates and PEAD finds ~3-10. Most of the portfolio ends up being factor-driven (random).
3. **Only 3-8 positions**: ATR sizing creates concentrated positions, so bad picks hurt more.

### Secondary Issue: Defense System Over-Reacts
4. **Too much time in DEFENSIVE/BEAR mode**: Even in 2017 bull market, the strategy went DEFENSIVE by mid-year. The leading stock health check (ARKK, SOXX, etc.) and defensive rotation signals fire too often.
5. **Low exposure ceiling**: When defense reduces to 50% and there are only 4 good candidates, the portfolio barely invests at all.

### Factor IC Across Regimes (still near zero)
```
Factor               Bull     Crash    Bear
composite_z         -0.006   +0.003   -0.009
analyst_revision_z  -0.006   +0.025   +0.026  ← best
mom_12m_skip1_z     +0.007   +0.015   +0.010  ← consistent
sue_z               +0.005   +0.008   +0.005  ← consistent
accruals_z          +0.004   +0.014   +0.002
```

---

## Next Steps (Priority Order)

### 1. Fix Stock Selection (Highest Impact)
- **Equal-weight top-N instead of ATR sizing**: With near-zero IC, diversification matters more than position optimization. Try 20-25 equal-weight positions.
- **Momentum tilt**: mom_12m_skip1 and mom_6m are the only consistently positive factors. Weight them 60%+ of composite.
- **Lower VCP/PEAD thresholds**: Accept more candidates to increase diversification.

### 2. Calibrate Defense System
- **Raise risk thresholds**: MarketTopDetector fires too often. Consider: only trigger DEFENSIVE when composite risk >= 60 (currently 40).
- **Remove leading stock ETFs**: ARKK/SOXX/SMH aren't in our price universe. Either add them to price loading or remove this sub-signal.
- **Shorter distribution day window**: 25 days accumulates too many distribution days in normal markets.

### 3. Integrate Feedback Loop
- Wire SignalPostmortem into on_rebalance() to track signal accuracy in real-time.
- Wire EdgeAggregator to dynamically adjust factor/VCP/PEAD weights based on what's working.

### 4. Data Quality
- Filter 274 price anomalies (>100% single-day moves) identified in Phase 0.2.
- This may be causing trailing stops to fire incorrectly on bad data.
