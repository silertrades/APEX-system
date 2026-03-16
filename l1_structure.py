# =============================================================================
# APEX SYSTEM — l1_structure.py
# =============================================================================
# Layer 1: Market Structure
#
# Scoring audit changes:
#   - Trend bias now awards points for PARTIAL structure (not just perfect)
#   - BOS scoring more graduated — rewards proximity not just confirmation
#   - CHoCH awards points even when just approaching key level
#   - MTF agreement scoring more generous
#   - Overall: should score 8-15/20 in most trending conditions
#
# Score: 0-20 points
# =============================================================================

import numpy as np
import pandas as pd
import logging

log = logging.getLogger("l1_structure")

SWING_LOOKBACK = 6     # Reduced from 8 — catches more valid swings
MIN_SWING_PCT  = 0.005 # Reduced from 0.008 — less filtering


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
            avg_price  = df["close"].iloc[i]
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
# TREND BIAS — more graduated scoring
# =============================================================================

def get_trend_bias(df: pd.DataFrame) -> dict:
    """
    Returns trend bias with graduated strength score.
    Now awards points for partial structure, not just perfect HH+HL.
    """
    if len(df) < 50:
        return {"bias": "neutral", "strength": 0.0,
                "description": "Insufficient data"}

    swings = get_recent_swings(df, lookback=SWING_LOOKBACK, n=5)
    highs  = swings["swing_highs"]
    lows   = swings["swing_lows"]

    if len(highs) < 2 or len(lows) < 2:
        return {"bias": "neutral", "strength": 0.0,
                "description": "Not enough swings"}

    # Count bullish vs bearish swing comparisons
    bull_score = 0
    bear_score = 0
    total      = 0

    # Check highs
    for i in range(1, len(highs)):
        total += 1
        if highs[i] > highs[i-1]:
            bull_score += 1
        elif highs[i] < highs[i-1]:
            bear_score += 1

    # Check lows
    for i in range(1, len(lows)):
        total += 1
        if lows[i] > lows[i-1]:
            bull_score += 1
        elif lows[i] < lows[i-1]:
            bear_score += 1

    if total == 0:
        return {"bias": "neutral", "strength": 0.0,
                "description": "No swing comparisons"}

    bull_pct = bull_score / total
    bear_pct = bear_score / total

    if bull_pct >= 0.6:
        return {
            "bias":        "bullish",
            "strength":    round(bull_pct, 3),
            "description": f"Bullish structure ({bull_score}/{total} swings bullish)"
        }
    elif bear_pct >= 0.6:
        return {
            "bias":        "bearish",
            "strength":    round(bear_pct, 3),
            "description": f"Bearish structure ({bear_score}/{total} swings bearish)"
        }
    elif bull_pct > bear_pct:
        return {
            "bias":        "bullish",
            "strength":    round(bull_pct * 0.5, 3),
            "description": f"Mild bullish structure ({bull_score}/{total})"
        }
    elif bear_pct > bull_pct:
        return {
            "bias":        "bearish",
            "strength":    round(bear_pct * 0.5, 3),
            "description": f"Mild bearish structure ({bear_score}/{total})"
        }

    return {"bias": "neutral", "strength": 0.0,
            "description": "Mixed structure"}


# =============================================================================
# BREAK OF STRUCTURE
# =============================================================================

def detect_bos(df: pd.DataFrame) -> dict:
    """
    Detects BOS. Now also awards partial points when price is
    approaching a key level (within 0.5%) even before breaking it.
    """
    if len(df) < 20:
        return {"bos": "none", "level": 0.0,
                "strength": 0.0, "description": "Insufficient data"}

    swings     = get_recent_swings(df, lookback=SWING_LOOKBACK, n=3)
    last_close = df["close"].iloc[-1]

    if len(swings["swing_highs"]) > 0:
        prev_high = swings["swing_highs"][-1]
        if last_close > prev_high:
            return {
                "bos":         "bullish",
                "level":       round(prev_high, 2),
                "strength":    1.0,
                "description": f"Bullish BOS — closed above {prev_high:.2f}"
            }
        # Near miss — within 0.5%
        proximity = (prev_high - last_close) / last_close
        if proximity <= 0.005:
            return {
                "bos":         "bullish_approaching",
                "level":       round(prev_high, 2),
                "strength":    0.5,
                "description": f"Approaching bullish BOS at {prev_high:.2f} "
                               f"({proximity*100:.2f}% away)"
            }

    if len(swings["swing_lows"]) > 0:
        prev_low = swings["swing_lows"][-1]
        if last_close < prev_low:
            return {
                "bos":         "bearish",
                "level":       round(prev_low, 2),
                "strength":    1.0,
                "description": f"Bearish BOS — closed below {prev_low:.2f}"
            }
        proximity = (last_close - prev_low) / last_close
        if proximity <= 0.005:
            return {
                "bos":         "bearish_approaching",
                "level":       round(prev_low, 2),
                "strength":    0.5,
                "description": f"Approaching bearish BOS at {prev_low:.2f} "
                               f"({proximity*100:.2f}% away)"
            }

    return {"bos": "none", "level": 0.0, "strength": 0.0,
            "description": "No BOS detected"}


# =============================================================================
# CHANGE OF CHARACTER
# =============================================================================

def detect_choch(df: pd.DataFrame, trend_bias: str) -> dict:
    if len(df) < 20 or trend_bias == "neutral":
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
# MTF AGREEMENT
# =============================================================================

def get_mtf_agreement(candles: dict) -> dict:
    biases     = {}
    for tf_name, df in candles.items():
        if not df.empty:
            bias = get_trend_bias(df)
            biases[tf_name] = bias["bias"]

    bullish_count = sum(1 for b in biases.values() if b == "bullish")
    bearish_count = sum(1 for b in biases.values() if b == "bearish")
    total         = len(biases)

    if total == 0:
        return {"agreement": "mixed", "score": 0,
                "description": "No timeframe data"}

    if bullish_count >= total * 0.6:
        return {
            "agreement":   "bullish",
            "score":       bullish_count,
            "description": f"Bullish on {bullish_count}/{total} timeframes"
        }
    if bearish_count >= total * 0.6:
        return {
            "agreement":   "bearish",
            "score":       bearish_count,
            "description": f"Bearish on {bearish_count}/{total} timeframes"
        }

    dominant = "bullish" if bullish_count >= bearish_count else "bearish"
    return {
        "agreement":   "mixed",
        "score":       max(bullish_count, bearish_count),
        "description": f"Mixed — {bullish_count} bull, "
                       f"{bearish_count} bear of {total} TFs"
    }


# =============================================================================
# MAIN SCORER — more graduated point awards
# =============================================================================

def score(data: dict) -> dict:
    """
    Score breakdown (max 20):
        HTF bias:        0-7  (graduated by strength)
        MTF agreement:   0-5  (graduated by count)
        BOS:             0-6  (full=6, approaching=3)
        CHoCH:           0-4
        Bonus:           +2 if BOS + CHoCH both fire same direction
    """
    candles = data.get("candles", {})

    if not candles:
        return _empty_score("No candle data")

    htf_df = candles.get("HTF", pd.DataFrame())
    mtf_df = candles.get("MTF", pd.DataFrame())
    ltf_df = candles.get("LTF", pd.DataFrame())

    if htf_df.empty:
        return _empty_score("No HTF data")

    htf_bias      = get_trend_bias(htf_df)
    mtf_bias      = get_trend_bias(mtf_df) if not mtf_df.empty else \
                    {"bias": "neutral", "strength": 0.0}
    bos           = detect_bos(mtf_df) if not mtf_df.empty else \
                    {"bos": "none", "strength": 0.0}
    choch         = detect_choch(ltf_df, htf_bias["bias"]) \
                    if not ltf_df.empty else \
                    {"choch": False, "direction": "none"}
    mtf_agreement = get_mtf_agreement(candles)

    points    = 0
    reasons   = []
    direction = "neutral"

    # HTF bias (max 7 — graduated by strength)
    if htf_bias["bias"] != "neutral":
        bias_points = int(7 * htf_bias["strength"])
        bias_points = max(2, min(7, bias_points))
        points     += bias_points
        direction   = "long" if htf_bias["bias"] == "bullish" else "short"
        reasons.append(f"HTF {htf_bias['bias']}: "
                       f"{htf_bias['description']}")

    # MTF agreement (max 5 — graduated by how many TFs agree)
    agree_score = mtf_agreement["score"]
    if mtf_agreement["agreement"] != "mixed":
        agree_points = min(5, agree_score + 1)
        points      += agree_points
        reasons.append(f"MTF: {mtf_agreement['description']}")
    elif agree_score >= 2:
        points += 2
        reasons.append(f"Partial MTF: {mtf_agreement['description']}")

    # BOS (max 6 — full BOS = 6, approaching = 3)
    bos_type = bos.get("bos", "none")
    if bos_type in ["bullish", "bearish"]:
        points += 6
        if direction == "neutral":
            direction = "long" if bos_type == "bullish" else "short"
        reasons.append(f"BOS: {bos['description']}")
    elif bos_type in ["bullish_approaching", "bearish_approaching"]:
        points += 3
        if direction == "neutral":
            direction = "long" if "bullish" in bos_type else "short"
        reasons.append(f"Near BOS: {bos['description']}")

    # CHoCH (max 4)
    if choch["choch"]:
        points += 4
        if direction == "neutral":
            direction = "long" if choch["direction"] == "bullish" else "short"
        reasons.append(f"CHoCH: {choch['description']}")

    # Confluence bonus
    if (bos_type in ["bullish", "bearish"] and choch["choch"]):
        points += 2
        reasons.append("BOS + CHoCH confluence bonus")

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
