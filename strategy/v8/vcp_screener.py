"""VCP Screener — Minervini Volatility Contraction Pattern detection.

Finds stocks in Stage 2 uptrend with progressively tighter consolidations,
signaling institutional accumulation before a breakout.
"""

import numpy as np
import pandas as pd


class VCPScreener:
    """Screen for Volatility Contraction Patterns in price data."""

    # Stage 2 trend template parameters
    MIN_DAYS_200SMA_UP = 22      # 200DMA must be rising for 22+ days
    RS_MIN = 60                   # Relative strength vs S&P 500

    # VCP pattern parameters
    T1_DEPTH_MIN = 0.08           # First contraction minimum 8%
    T1_DEPTH_MAX = 0.35           # First contraction maximum 35%
    CONTRACTION_RATIO = 0.75      # Each tightening must be 25%+ tighter
    MIN_CONTRACTIONS = 2
    PATTERN_MIN_DAYS = 15
    PATTERN_MAX_DAYS = 325

    def screen(self, date: pd.Timestamp, universe: list,
               price_data: dict, spy_data: pd.DataFrame = None) -> list:
        """Screen universe for VCP candidates.

        Returns:
            List of dicts: [{symbol, vcp_score, pivot_price, stage2_score, ...}]
        """
        candidates = []

        # SPY return for RS calculation
        spy_return_52w = 0
        if spy_data is not None:
            spy_up_to = spy_data[spy_data.index <= date]
            if len(spy_up_to) >= 252:
                spy_return_52w = (float(spy_up_to["Close"].iloc[-1]) /
                                  float(spy_up_to["Close"].iloc[-252]) - 1)

        for sym in universe:
            if sym in ("SPY", "QQQ") or sym not in price_data:
                continue

            df = price_data[sym]
            df_up_to = df[df.index <= date]

            if len(df_up_to) < 260:
                continue

            close = df_up_to["Close"].values.astype(float)
            volume = (df_up_to["Volume"].values.astype(float)
                      if "Volume" in df_up_to.columns else None)

            # Step 1: Stage 2 trend template
            stage2 = self._check_stage2(close, spy_return_52w)
            if stage2["score"] < 60:
                continue

            # Step 2: VCP detection
            vcp = self._detect_vcp(close, volume)
            if vcp is None:
                continue

            # Step 3: Volume dryup check
            vol_dryup = 0
            if volume is not None and len(volume) >= 50:
                recent_vol = np.mean(volume[-10:])
                avg_vol = np.mean(volume[-50:])
                if avg_vol > 0:
                    vol_ratio = recent_vol / avg_vol
                    if vol_ratio < 0.5:
                        vol_dryup = 30
                    elif vol_ratio < 0.7:
                        vol_dryup = 15

            # Composite score
            composite = (vcp["pattern_score"] * 0.5 +
                         stage2["score"] * 0.3 +
                         vol_dryup * 0.2)

            candidates.append({
                "symbol": sym,
                "vcp_score": round(composite, 1),
                "pattern_score": round(vcp["pattern_score"], 1),
                "stage2_score": round(stage2["score"], 1),
                "pivot_price": round(vcp["pivot"], 2),
                "n_contractions": vcp["n_contractions"],
                "tightness": round(vcp["tightness_ratio"], 3),
                "current_price": round(close[-1], 2),
            })

        # Sort by score
        candidates.sort(key=lambda x: x["vcp_score"], reverse=True)
        return candidates

    def _check_stage2(self, close: np.ndarray, spy_52w_return: float) -> dict:
        """Check Minervini Stage 2 trend template (7-point filter).

        Returns dict with score (0-100) and details.
        """
        n = len(close)
        current = close[-1]
        sma_50 = np.mean(close[-50:])
        sma_150 = np.mean(close[-150:]) if n >= 150 else sma_50
        sma_200 = np.mean(close[-200:]) if n >= 200 else sma_150

        low_52w = np.min(close[-252:]) if n >= 252 else np.min(close)
        high_52w = np.max(close[-252:]) if n >= 252 else np.max(close)

        # 200DMA rising check
        sma_200_22d_ago = np.mean(close[-222:-22]) if n >= 222 else sma_200
        sma_200_rising = sma_200 > sma_200_22d_ago

        # RS calculation
        stock_52w_return = current / close[-252] - 1 if n >= 252 else 0
        rs = stock_52w_return - spy_52w_return

        checks = 0
        total = 7

        # 1. Price > 150-day & 200-day SMA
        if current > sma_150 and current > sma_200:
            checks += 1
        # 2. 150-day SMA > 200-day SMA
        if sma_150 > sma_200:
            checks += 1
        # 3. 200-day SMA rising >= 22 days
        if sma_200_rising:
            checks += 1
        # 4. Price > 50-day SMA
        if current > sma_50:
            checks += 1
        # 5. Price >= 52-week low + 25%
        if current >= low_52w * 1.25:
            checks += 1
        # 6. Price within 25% of 52-week high
        if current >= high_52w * 0.75:
            checks += 1
        # 7. RS > threshold
        if rs > 0.10:  # Outperforming by 10%+
            checks += 1

        score = (checks / total) * 100

        return {"score": score, "checks_passed": checks, "rs": rs}

    def _detect_vcp(self, close: np.ndarray, volume: np.ndarray = None) -> dict:
        """Detect VCP pattern in price data.

        Returns dict with pattern details or None if no valid VCP found.
        """
        n = len(close)
        if n < self.PATTERN_MIN_DAYS:
            return None

        # Find swing points using simple peak/trough detection
        lookback = min(n, self.PATTERN_MAX_DAYS)
        data = close[-lookback:]

        # Find the pattern starting point (recent 52-week high area)
        high_idx = np.argmax(data)
        high_val = data[high_idx]

        if high_idx < 10:
            return None

        # Find contractions after the high
        contractions = []
        i = high_idx
        prev_high = high_val

        while i < len(data) - 5:
            # Find next trough
            trough_window = min(i + 60, len(data))
            segment = data[i:trough_window]
            if len(segment) < 5:
                break

            trough_idx_local = np.argmin(segment)
            trough_val = segment[trough_idx_local]
            trough_idx = i + trough_idx_local

            depth = (prev_high - trough_val) / prev_high

            if depth < 0.02:
                break  # Too shallow, pattern done

            # Find next high after trough
            remaining = data[trough_idx:]
            if len(remaining) < 3:
                break

            next_high_idx_local = np.argmax(remaining[:min(40, len(remaining))])
            next_high_val = remaining[next_high_idx_local]
            next_high_idx = trough_idx + next_high_idx_local

            if next_high_idx <= trough_idx:
                break

            contractions.append({
                "depth": depth,
                "trough": trough_val,
                "high": prev_high,
                "next_high": next_high_val,
            })

            prev_high = next_high_val
            i = next_high_idx + 1

        if len(contractions) < self.MIN_CONTRACTIONS:
            return None

        # Validate: first contraction in range
        t1_depth = contractions[0]["depth"]
        if t1_depth < self.T1_DEPTH_MIN or t1_depth > self.T1_DEPTH_MAX:
            return None

        # Validate: progressive tightening
        valid_contractions = [contractions[0]]
        for j in range(1, len(contractions)):
            ratio = contractions[j]["depth"] / contractions[j - 1]["depth"]
            if ratio <= self.CONTRACTION_RATIO:
                valid_contractions.append(contractions[j])
            else:
                break  # Tightening broken

        if len(valid_contractions) < self.MIN_CONTRACTIONS:
            return None

        # Compute pattern score
        n_cont = len(valid_contractions)
        tightness = (valid_contractions[-1]["depth"] /
                     valid_contractions[0]["depth"])

        base_score = min(n_cont / 4, 1.0) * 50 + 20
        tightness_bonus = (1 - tightness) * 30  # Tighter = better

        pattern_score = min(base_score + tightness_bonus, 100)

        # Pivot price = high of the last contraction
        pivot = max(c["next_high"] for c in valid_contractions[-2:])

        return {
            "pattern_score": pattern_score,
            "n_contractions": n_cont,
            "tightness_ratio": tightness,
            "pivot": pivot,
        }
