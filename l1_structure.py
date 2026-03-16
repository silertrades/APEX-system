# =============================================================================
# APEX SYSTEM — l1_structure.py
# =============================================================================
# Layer 1: Market Structure
#
# What this does:
#   - Identifies the HTF (Daily) trend bias — bullish or bearish
#   - Detects Break of Structure (BOS) — trend continuation signal
#   - Detects Change of Character (CHoCH) — earliest reversal signal
#   - Scores swing high/low quality
#
# Changes from v1:
#   - Swing lookback increased from 5 to 8 for cleaner structure detection
#   - Minimum swing count increased to reduce noise on high-liquidity assets
#   - BOS confirmation requires close beyond level, not just touch
#   - Added swing strength filter — small swings ignored
#
# Score: 0–20 points
# =============================================================================

import numpy as np
import pandas as pd
import logging

log = logging.getLogger("l1_structure")

# Increased from 5 to 8 — filters out noise on liquid markets like BTC
SWING_LOOKBACK = 8

# Minimum % move to count as a valid swing
MIN_SWING_PCT = 0.008   # 0.8%


# =============================================================================
# HELPERS
# =============================================================================

def find_swing_highs(df: pd.DataFrame,
                     lookback: int = SWING_LOOKBACK) -> pd.Series:
    highs    = df["high"]
    is_swing = pd.Series(False, index=df.index)

    for i in range(lookback, len(df) - lookback):
        window = highs.iloc[i - lookback: i + lookback + 1]
        if highs.iloc[i] == window.max():
            # Filter out tiny swings
            avg_price = df["close"].iloc[i]
            swing_size = (highs.iloc[i] - df["low"].iloc[i]) / avg_price
            if swing_size >= MIN_SWING_PCT:
                is_swing.iloc[i] = True

    return is_swing


def find_swing_lows(df: pd.DataFrame,
                    lookback: int = SWING_LOOKBACK) -> pd.Series:
    lows     = df["low"]
    is_swing = pd.Series(False, index=df.index)

    for i in range(lookback, len(df) - lookback):
        window = lows.iloc[i - lookback: i + lookback + 1]
        if lows.iloc[i] == window.min():
            avg_price  = df["close"].iloc[i]
            swing_size = (df["high"].iloc[i] - lows.iloc[i]) / avg_price
            if swing_size >= MIN_SWING_PCT:
                is_swing.iloc[i] = True

    return is_swing


def get_recent_swings(df: pd.DataFrame,
                      lookback: int = SWING_LOOKBACK,
                      n: int = 5) -> dict:
    sh_mask = find_swing_highs(df, lookback)
    sl_mask = find_swing_lows(df, lookback)

    swing_highs = df["high"][sh_mask].values[-n:]
    swing_lows  = df["low"][sl_mask].values[-n:]

    return {
        "swing_highs": swing_highs,
        "swing_lows":  swing_lows,
    }


# =============================================================================
# TREND BIAS
# =============================================================================

def get_trend_bias(df: pd.DataFrame) -> dict:
    """
    Determines the current trend bias from swing structure.
    Requires minimum 3 swings to confirm — reduces false signals.
    """
    if len(df) < 80:
        return {"bias": "neutral", "strength": 0.0,
                "description": "Insufficient data"}

    swings = get_recent_swings(df, lookback=SWING_LOOKBACK, n=4)
    highs  = swings["swing_highs"]
    lows   = swings["swing_lows"]

    if len(highs) < 3 or len(lows) < 3:
        return {"bias": "neutral", "strength": 0.0,
                "description": "Not enough swings"}

    hh = all(highs[i] > highs[i-1] for i in range(1, len(highs)))
    hl = all(lows[i]  > lows[i-1]  for i in range(1, len(lows)))
    lh = all(highs[i] < highs[i-1] for i in range(1, len(highs)))
    ll = all(lows[i]  < lows[i-1]  for i in range(1, len(lows)))

    if hh and hl:
        high_diffs = [highs[i] - highs[i-1] for i in range(1, len(highs))]
        low_diffs  = [lows[i]  - lows[i-1]  for i in range(1, len(lows))]
        strength   = min(1.0, (np.mean(high_diffs) + np.mean(low_diffs)) /
                        (df["close"].iloc[-1] * 0.02))
        return {
            "bias":        "bullish",
            "strength":    round(strength, 3),
            "description": f"HH+HL structure confirmed ({len(highs)} swings)"
        }

    if lh and ll:
        high_diffs = [highs[i-1] - highs[i] for i in range(1, len(highs))]
        low_diffs  = [lows[i-1]  - lows[i]  for i in range(1, len(lows))]
        strength   = min(1.0, (np.mean(high_diffs) + np.mean(low_diffs)) /
                        (df["close"].iloc[-1] * 0.02))
        return {
            "bias":        "bearish",
            "strength":    round(strength, 3),
            "description": f"LH+LL structure confirmed ({len(highs)} swings)"
        }

    if hh or hl:
        return {"bias": "bullish", "strength": 0.3,
                "description": "Partial bullish structure"}
    if lh or ll:
        return {"bias": "bearish", "strength": 0.3,
                "description": "Partial bearish structure"}

    return {"bias": "neutral", "strength": 0.0,
            "description": "No clear structure"}


# =============================================================================
# BREAK OF STRUCTURE (BOS)
# =============================================================================

def detect_bos(df: pd.DataFrame) -> dict:
    """
    Break of Structure — price CLOSES beyond the most recent swing high/low.
    Requires a candle close, not just a wick — reduces fakeout signals.
    """
    if len(df) < 30:
        return {"bos": "none", "level": 0.0, "description": "Insufficient data"}

    swings     = get_recent_swings(df, lookback=SWING_LOOKBACK, n=3)
    last_close = df["close"].iloc[-1]

    if len(swings["swing_highs"]) > 0:
        prev_swing_high = swings["swing_highs"][-1]
        if last_close > prev_swing_high:
            return {
                "bos":         "bullish",
                "level":       round(prev_swing_high, 2),
                "description": f"Bullish BOS — closed above {prev_swing_high:.2f}"
            }

    if len(swings["swing_lows"]) > 0:
        prev_swing_low = swings["swing_lows"][-1]
        if last_close < prev_swing_low:
            return {
                "bos":         "bearish",
                "level":       round(prev_swing_low, 2),
                "description": f"Bearish BOS — closed below {prev_swing_low:.2f}"
            }

    return {"bos": "none", "level": 0.0, "description": "No BOS detected"}


# =============================================================================
# CHANGE OF CHARACTER (CHoCH)
# =============================================================================

def detect_choch(df: pd.DataFrame, trend_bias: str) -> dict:
    """
    Change of Character — first sign of trend reversal.
    """
    if len(df) < 30 or trend_bias == "neutral":
        return {"choch": False, "direction": "none", "level": 0.0,
                "description": "No CHoCH — neutral structure"}

    swings     = get_recent_swings(df, lookback=SWING_LOOKBACK, n=3)
    last_close = df["close"].iloc[-1]

    if trend_bias == "bullish" and len(swings["swing_lows"]) > 0:
        recent_hl = swings["swing_lows"][-1]
        if last_close < recent_hl:
            return {
                "choch":       True,
                "direction":   "bearish",
                "level":       round(recent_hl, 2),
                "description": f"Bearish CHoCH — broke HL at {recent_hl:.2f}"
            }

    if trend_bias == "bearish" and len(swings["swing_highs"]) > 0:
        recent_lh = swings["swing_highs"][-1]
        if last_close > recent_lh:
            return {
                "choch":       True,
                "direction":   "bullish",
                "level":       round(recent_lh, 2),
                "description": f"Bullish CHoCH — broke LH at {recent_lh:.2f}"
            }

    return {"choch": False, "direction": "none", "level": 0.0,
            "description": "No CHoCH detected"}


# =============================================================================
# MULTI-TIMEFRAME STRUCTURE AGREEMENT
# =============================================================================

def get_mtf_agreement(candles: dict) -> dict:
    biases = {}
    for tf_name, df in candles.items():
        if not df.empty:
            bias = get_trend_bias(df)
            biases[tf_name] = bias["bias"]

    bullish_count = sum(1 for b in biases.values() if b == "bullish")
    bearish_count = sum(1 for b in biases.values() if b == "bearish")
    total         = len(biases)

    if bullish_count >= total * 0.75:
        return {
            "agreement":   "bullish",
            "score":       bullish_count,
            "description": f"Bullish on {bullish_count}/{total} timeframes"
        }
    if bearish_count >= total * 0.75:
        return {
            "agreement":   "bearish",
            "score":       bearish_count,
            "description": f"Bearish on {bearish_count}/{total} timeframes"
        }

    dominant = "bullish" if bullish_count > bearish_count else "bearish"
    return {
        "agreement":   "mixed",
        "score":       max(bullish_count, bearish_count),
        "description": f"Mixed — {bullish_count} bull, "
                       f"{bearish_count} bear of {total} TFs"
    }


# =============================================================================
# MAIN SCORER
# =============================================================================

def score(data: dict) -> dict:
    """
    Main entry point — called by scoring_engine.py

    Score breakdown (max 20):
        HTF bias clear:          +6
        MTF agreement:           +4
        BOS confirmed:           +6
        CHoCH detected:          +4
    """
    candles = data.get("candles", {})

    if not candles:
        return _empty_score("No candle data available")

    htf_df = candles.get("HTF", pd.DataFrame())
    mtf_df = candles.get("MTF", pd.DataFrame())
    ltf_df = candles.get("LTF", pd.DataFrame())

    if htf_df.empty:
        return _empty_score("No HTF data")

    htf_bias      = get_trend_bias(htf_df)
    mtf_bias      = get_trend_bias(mtf_df) if not mtf_df.empty else \
                    {"bias": "neutral", "strength": 0.0}
    bos           = detect_bos(mtf_df) if not mtf_df.empty else \
                    {"bos": "none"}
    choch         = detect_choch(ltf_df, htf_bias["bias"]) \
                    if not ltf_df.empty else \
                    {"choch": False, "direction": "none"}
    mtf_agreement = get_mtf_agreement(candles)

    points  = 0
    reasons = []

    # HTF bias (max 6)
    if htf_bias["bias"] != "neutral":
        bias_points = int(6 * htf_bias["strength"])
        bias_points = max(2, min(6, bias_points))
        points     += bias_points
        reasons.append(f"HTF {htf_bias['bias']} "
                       f"({htf_bias['description']})")

    # MTF agreement (max 4)
    if mtf_agreement["agreement"] != "mixed":
        agree_points = min(4, mtf_agreement["score"])
        points      += agree_points
        reasons.append(f"MTF agreement: {mtf_agreement['description']}")

    # BOS (max 6)
    if bos["bos"] != "none":
        if bos["bos"] == htf_bias["bias"]:
            points += 6
            reasons.append(f"BOS confirmed: {bos['description']}")
        else:
            points += 2
            reasons.append(f"BOS against trend: {bos['description']}")

    # CHoCH (max 4)
    if choch["choch"]:
        points += 4
        reasons.append(f"CHoCH: {choch['description']}")

    # Direction
    if htf_bias["bias"] == "bullish" and bos.get("bos") == "bullish":
        direction = "long"
    elif htf_bias["bias"] == "bearish" and bos.get("bos") == "bearish":
        direction = "short"
    elif htf_bias["bias"] != "neutral":
        direction = "long" if htf_bias["bias"] == "bullish" else "short"
    else:
        direction = "neutral"

    points = min(20, points)

    log.debug(f"L1 score: {points}/20 | direction: {direction} | "
              f"{' | '.join(reasons)}")

    return {
        "layer":     "L1_structure",
        "score":     points,
        "max":       20,
        "direction": direction,
        "reasons":   reasons,
        "details": {
            "htf_bias":      htf_bias,
            "mtf_bias":      mtf_bias,
            "bos":           bos,
            "choch":         choch,
            "mtf_agreement": mtf_agreement,
        }
    }


def _empty_score(reason: str) -> dict:
    return {
        "layer":     "L1_structure",
        "score":     0,
        "max":       20,
        "direction": "neutral",
        "reasons":   [reason],
        "details":   {}
    }
