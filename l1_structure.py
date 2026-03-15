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
# Score: 0–20 points
#   20 = crystal clear structure, BOS confirmed, all TFs agree
#   0  = choppy, no clear structure, mixed signals
# =============================================================================

import numpy as np
import pandas as pd
import logging

log = logging.getLogger("l1_structure")


# =============================================================================
# HELPERS
# =============================================================================

def find_swing_highs(df: pd.DataFrame, lookback: int = 5) -> pd.Series:
    """
    Find swing highs — candles where the high is the highest
    of the surrounding `lookback` candles on each side.
    Returns a boolean Series — True at swing high candles.
    """
    highs    = df["high"]
    is_swing = pd.Series(False, index=df.index)

    for i in range(lookback, len(df) - lookback):
        window = highs.iloc[i - lookback: i + lookback + 1]
        if highs.iloc[i] == window.max():
            is_swing.iloc[i] = True

    return is_swing


def find_swing_lows(df: pd.DataFrame, lookback: int = 5) -> pd.Series:
    """
    Find swing lows — candles where the low is the lowest
    of the surrounding `lookback` candles on each side.
    Returns a boolean Series — True at swing low candles.
    """
    lows     = df["low"]
    is_swing = pd.Series(False, index=df.index)

    for i in range(lookback, len(df) - lookback):
        window = lows.iloc[i - lookback: i + lookback + 1]
        if lows.iloc[i] == window.min():
            is_swing.iloc[i] = True

    return is_swing


def get_recent_swings(df: pd.DataFrame, lookback: int = 5, n: int = 5) -> dict:
    """
    Returns the last N swing highs and swing lows as price levels.
    Used to determine trend structure.
    """
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

    Bullish:  Higher Highs (HH) + Higher Lows (HL)
    Bearish:  Lower Highs (LH) + Lower Lows (LL)
    Neutral:  Mixed structure

    Returns:
        {
            "bias":        "bullish" | "bearish" | "neutral",
            "strength":    float (0.0–1.0),
            "description": str
        }
    """
    if len(df) < 50:
        return {"bias": "neutral", "strength": 0.0, "description": "Insufficient data"}

    swings = get_recent_swings(df, lookback=5, n=4)
    highs  = swings["swing_highs"]
    lows   = swings["swing_lows"]

    if len(highs) < 2 or len(lows) < 2:
        return {"bias": "neutral", "strength": 0.0, "description": "Not enough swings"}

    # Check if making higher highs and higher lows
    hh = all(highs[i] > highs[i-1] for i in range(1, len(highs)))
    hl = all(lows[i]  > lows[i-1]  for i in range(1, len(lows)))

    # Check if making lower highs and lower lows
    lh = all(highs[i] < highs[i-1] for i in range(1, len(highs)))
    ll = all(lows[i]  < lows[i-1]  for i in range(1, len(lows)))

    if hh and hl:
        # Measure strength by how consistent the moves are
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

    # Partial structure
    if hh or hl:
        return {"bias": "bullish", "strength": 0.3, "description": "Partial bullish structure"}
    if lh or ll:
        return {"bias": "bearish", "strength": 0.3, "description": "Partial bearish structure"}

    return {"bias": "neutral", "strength": 0.0, "description": "No clear structure"}


# =============================================================================
# BREAK OF STRUCTURE (BOS)
# =============================================================================

def detect_bos(df: pd.DataFrame) -> dict:
    """
    Break of Structure — price closes beyond the most recent
    swing high (bullish BOS) or swing low (bearish BOS).

    A BOS confirms trend continuation — institutions have
    pushed through a key level and likely have more to go.

    Returns:
        {
            "bos":         "bullish" | "bearish" | "none",
            "level":       float (the broken level),
            "description": str
        }
    """
    if len(df) < 20:
        return {"bos": "none", "level": 0.0, "description": "Insufficient data"}

    swings      = get_recent_swings(df, lookback=5, n=3)
    last_close  = df["close"].iloc[-1]
    last_high   = df["high"].iloc[-1]
    last_low    = df["low"].iloc[-1]

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
    Change of Character — the FIRST sign that a trend is reversing.
    In a bullish trend: price breaks below the most recent Higher Low
    In a bearish trend: price breaks above the most recent Lower High

    This is the earliest possible reversal signal — it happens BEFORE
    a full structure shift, giving you early entry on reversals.

    Returns:
        {
            "choch":       True | False,
            "direction":   "bullish" | "bearish" | "none",
            "level":       float,
            "description": str
        }
    """
    if len(df) < 20 or trend_bias == "neutral":
        return {"choch": False, "direction": "none", "level": 0.0,
                "description": "No CHoCH — neutral structure"}

    swings     = get_recent_swings(df, lookback=5, n=3)
    last_close = df["close"].iloc[-1]

    if trend_bias == "bullish" and len(swings["swing_lows"]) > 0:
        # In bullish trend — break of recent HL = CHoCH bearish
        recent_hl = swings["swing_lows"][-1]
        if last_close < recent_hl:
            return {
                "choch":       True,
                "direction":   "bearish",
                "level":       round(recent_hl, 2),
                "description": f"Bearish CHoCH — broke HL at {recent_hl:.2f}"
            }

    if trend_bias == "bearish" and len(swings["swing_highs"]) > 0:
        # In bearish trend — break of recent LH = CHoCH bullish
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
    """
    Checks if structure bias agrees across all timeframes.
    More agreement = stronger signal.

    Returns:
        {
            "agreement":    "bullish" | "bearish" | "mixed",
            "score":        int (0–3, how many TFs agree),
            "description":  str
        }
    """
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
        "description": f"Mixed — {bullish_count} bull, {bearish_count} bear of {total} TFs"
    }


# =============================================================================
# MAIN SCORER
# =============================================================================

def score(data: dict) -> dict:
    """
    Main entry point — called by scoring_engine.py

    Takes the full data dict from DataManager.get_all()
    Returns a standardized score dict.

    Score breakdown (max 20):
        HTF bias clear:          +6
        MTF agreement:           +4
        BOS confirmed:           +6
        CHoCH detected:          +4
    """
    candles = data.get("candles", {})

    if not candles:
        return _empty_score("No candle data available")

    htf_df  = candles.get("HTF", pd.DataFrame())
    mtf_df  = candles.get("MTF", pd.DataFrame())
    ltf_df  = candles.get("LTF", pd.DataFrame())

    if htf_df.empty:
        return _empty_score("No HTF data")

    # --- HTF trend bias ---
    htf_bias = get_trend_bias(htf_df)
    mtf_bias = get_trend_bias(mtf_df) if not mtf_df.empty else {"bias": "neutral", "strength": 0.0}

    # --- BOS on MTF ---
    bos = detect_bos(mtf_df) if not mtf_df.empty else {"bos": "none"}

    # --- CHoCH on LTF ---
    choch = detect_choch(ltf_df, htf_bias["bias"]) if not ltf_df.empty else {"choch": False, "direction": "none"}

    # --- MTF agreement ---
    mtf_agreement = get_mtf_agreement(candles)

    # --- Build score ---
    points = 0
    reasons = []

    # HTF bias (max 6)
    if htf_bias["bias"] != "neutral":
        bias_points = int(6 * htf_bias["strength"])
        bias_points = max(2, min(6, bias_points))
        points += bias_points
        reasons.append(f"HTF {htf_bias['bias']} ({htf_bias['description']})")

    # MTF agreement (max 4)
    if mtf_agreement["agreement"] != "mixed":
        agree_points = min(4, mtf_agreement["score"])
        points += agree_points
        reasons.append(f"MTF agreement: {mtf_agreement['description']}")

    # BOS (max 6)
    if bos["bos"] != "none":
        # Full points only if BOS direction matches HTF bias
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

    # Determine signal direction
    if htf_bias["bias"] == "bullish" and bos.get("bos") == "bullish":
        direction = "long"
    elif htf_bias["bias"] == "bearish" and bos.get("bos") == "bearish":
        direction = "short"
    elif htf_bias["bias"] != "neutral":
        direction = "long" if htf_bias["bias"] == "bullish" else "short"
    else:
        direction = "neutral"

    points = min(20, points)

    log.debug(f"L1 score: {points}/20 | direction: {direction} | {' | '.join(reasons)}")

    return {
        "layer":     "L1_structure",
        "score":     points,
        "max":       20,
        "direction": direction,
        "reasons":   reasons,
        "details": {
            "htf_bias":     htf_bias,
            "mtf_bias":     mtf_bias,
            "bos":          bos,
            "choch":        choch,
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
