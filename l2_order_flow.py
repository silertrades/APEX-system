# =============================================================================
# APEX SYSTEM — l2_order_flow.py
# =============================================================================
# Layer 2: Order Flow
#
# What this does:
#   - Reads CVD divergence from the live WebSocket feed
#   - Detects buy/sell aggression imbalances
#   - Identifies absorption (large orders being absorbed at key levels)
#   - Measures volume momentum vs price momentum
#
# Score: 0–20 points
#   20 = strong CVD divergence + volume confirms direction
#   0  = no divergence, volume neutral or against direction
# =============================================================================

import numpy as np
import pandas as pd
import logging

log = logging.getLogger("l2_order_flow")


# =============================================================================
# VOLUME ANALYSIS
# =============================================================================

def get_volume_trend(df: pd.DataFrame, period: int = 20) -> dict:
    """
    Measures whether volume is expanding or contracting
    relative to the recent average.

    Expanding volume on a move = institutional participation
    Contracting volume on a move = weak, likely to fade

    Returns:
        {
            "trend":       "expanding" | "contracting" | "neutral",
            "ratio":       float (current vol / average vol),
            "description": str
        }
    """
    if len(df) < period + 1:
        return {"trend": "neutral", "ratio": 1.0, "description": "Insufficient data"}

    recent_vol  = df["volume"].iloc[-1]
    avg_vol     = df["volume"].iloc[-period:-1].mean()

    if avg_vol == 0:
        return {"trend": "neutral", "ratio": 1.0, "description": "Zero volume"}

    ratio = recent_vol / avg_vol

    if ratio >= 1.5:
        return {
            "trend":       "expanding",
            "ratio":       round(ratio, 2),
            "description": f"Volume {ratio:.1f}x above average — strong participation"
        }
    elif ratio <= 0.6:
        return {
            "trend":       "contracting",
            "ratio":       round(ratio, 2),
            "description": f"Volume {ratio:.1f}x below average — weak participation"
        }
    else:
        return {
            "trend":       "neutral",
            "ratio":       round(ratio, 2),
            "description": f"Volume {ratio:.1f}x average — normal participation"
        }


def get_volume_delta_bias(df: pd.DataFrame, period: int = 10) -> dict:
    """
    Approximates buy/sell volume bias using candle body direction.
    Bullish candles (close > open) = buying pressure
    Bearish candles (close < open) = selling pressure

    This is an approximation of real order flow when
    tick-by-tick data isn't available per candle.

    Returns:
        {
            "bias":        "buying" | "selling" | "neutral",
            "strength":    float (0.0–1.0),
            "description": str
        }
    """
    if len(df) < period:
        return {"bias": "neutral", "strength": 0.0, "description": "Insufficient data"}

    recent = df.tail(period)

    bull_vol = recent[recent["close"] > recent["open"]]["volume"].sum()
    bear_vol = recent[recent["close"] < recent["open"]]["volume"].sum()
    total    = bull_vol + bear_vol

    if total == 0:
        return {"bias": "neutral", "strength": 0.0, "description": "No volume data"}

    bull_pct = bull_vol / total
    bear_pct = bear_vol / total

    if bull_pct >= 0.65:
        return {
            "bias":        "buying",
            "strength":    round(bull_pct, 3),
            "description": f"Buying bias {bull_pct*100:.0f}% of volume"
        }
    elif bear_pct >= 0.65:
        return {
            "bias":        "selling",
            "strength":    round(bear_pct, 3),
            "description": f"Selling bias {bear_pct*100:.0f}% of volume"
        }
    else:
        return {
            "bias":        "neutral",
            "strength":    round(max(bull_pct, bear_pct), 3),
            "description": f"Balanced flow — bull {bull_pct*100:.0f}% / bear {bear_pct*100:.0f}%"
        }


# =============================================================================
# ABSORPTION DETECTION
# =============================================================================

def detect_absorption(df: pd.DataFrame, period: int = 5) -> dict:
    """
    Detects absorption — when large volume appears but price
    barely moves. This means a large player is absorbing
    all the selling (bullish) or all the buying (bearish).

    High volume + small candle body = absorption

    Returns:
        {
            "absorption":  "bullish" | "bearish" | "none",
            "strength":    float (0.0–1.0),
            "description": str
        }
    """
    if len(df) < period + 1:
        return {"absorption": "none", "strength": 0.0, "description": "Insufficient data"}

    recent     = df.tail(period)
    avg_vol    = df["volume"].iloc[-period*3:-period].mean()
    avg_range  = (df["high"] - df["low"]).iloc[-period*3:-period].mean()

    if avg_vol == 0 or avg_range == 0:
        return {"absorption": "none", "strength": 0.0, "description": "No baseline data"}

    last            = df.iloc[-1]
    last_vol        = last["volume"]
    last_body       = abs(last["close"] - last["open"])
    last_range      = last["high"] - last["low"]

    vol_ratio       = last_vol / avg_vol
    body_ratio      = last_body / avg_range if avg_range > 0 else 1.0

    # High volume + small body = absorption
    is_absorption   = vol_ratio >= 1.8 and body_ratio <= 0.3

    if is_absorption:
        strength = min(1.0, vol_ratio / 3.0)
        # Direction: if close is in upper half of range = bulls absorbed sellers
        midpoint  = (last["high"] + last["low"]) / 2
        if last["close"] > midpoint:
            return {
                "absorption":  "bullish",
                "strength":    round(strength, 3),
                "description": f"Bullish absorption — {vol_ratio:.1f}x vol, tiny body"
            }
        else:
            return {
                "absorption":  "bearish",
                "strength":    round(strength, 3),
                "description": f"Bearish absorption — {vol_ratio:.1f}x vol, tiny body"
            }

    return {"absorption": "none", "strength": 0.0,
            "description": "No absorption detected"}


# =============================================================================
# PRICE VS VOLUME DIVERGENCE
# =============================================================================

def detect_price_volume_divergence(df: pd.DataFrame, period: int = 14) -> dict:
    """
    Detects divergence between price momentum and volume momentum.

    Price rising + volume falling = weak move, likely to reverse
    Price falling + volume falling = weak selloff, likely to bounce
    Price rising + volume rising  = strong move, likely to continue
    Price falling + volume rising = strong selloff, likely to continue

    Returns:
        {
            "divergence":  "bullish" | "bearish" | "none",
            "description": str
        }
    """
    if len(df) < period * 2:
        return {"divergence": "none", "description": "Insufficient data"}

    first_half  = df.iloc[-period*2:-period]
    second_half = df.iloc[-period:]

    price_change  = second_half["close"].mean() - first_half["close"].mean()
    volume_change = second_half["volume"].mean() - first_half["volume"].mean()

    price_up   = price_change  > 0
    price_dn   = price_change  < 0
    volume_up  = volume_change > 0
    volume_dn  = volume_change < 0

    # Bearish divergence: price up, volume down
    if price_up and volume_dn:
        return {
            "divergence":  "bearish",
            "description": "Price rising on falling volume — weak move"
        }

    # Bullish divergence: price down, volume down
    if price_dn and volume_dn:
        return {
            "divergence":  "bullish",
            "description": "Price falling on falling volume — weak selloff"
        }

    return {"divergence": "none", "description": "No price/volume divergence"}


# =============================================================================
# MAIN SCORER
# =============================================================================

def score(data: dict) -> dict:
    """
    Main entry point — called by scoring_engine.py

    Score breakdown (max 20):
        CVD divergence:           +8  (from WebSocket live feed)
        Volume delta bias:        +4  (buying vs selling pressure)
        Absorption detected:      +4  (smart money absorbing)
        Price/volume divergence:  +4  (confirms or denies move)
    """
    candles        = data.get("candles", {})
    cvd_divergence = data.get("cvd_divergence", {})

    ltf_df = candles.get("LTF", pd.DataFrame())
    mtf_df = candles.get("MTF", pd.DataFrame())

    if ltf_df.empty:
        return _empty_score("No LTF data")

    # --- CVD divergence (from live WebSocket) ---
    cvd_div     = cvd_divergence.get("divergence", "none")
    cvd_strength = cvd_divergence.get("strength", 0.0)

    # --- Volume analysis ---
    vol_trend   = get_volume_trend(ltf_df)
    vol_bias    = get_volume_delta_bias(ltf_df)
    absorption  = detect_absorption(ltf_df)
    pv_div      = detect_price_volume_divergence(mtf_df) if not mtf_df.empty else \
                  {"divergence": "none", "description": "No MTF data"}

    # --- Build score ---
    points  = 0
    reasons = []
    direction = "neutral"

    # CVD divergence (max 8)
    if cvd_div != "none":
        cvd_points = int(8 * cvd_strength)
        cvd_points = max(3, min(8, cvd_points))
        points    += cvd_points
        direction  = "long" if cvd_div == "bullish" else "short"
        reasons.append(f"CVD {cvd_div} divergence "
                       f"(strength: {cvd_strength:.2f}): "
                       f"{cvd_divergence.get('description', '')}")

    # Volume delta bias (max 4)
    if vol_bias["bias"] != "neutral":
        bias_points = int(4 * vol_bias["strength"])
        bias_points = max(1, min(4, bias_points))
        points     += bias_points
        bias_dir    = "long" if vol_bias["bias"] == "buying" else "short"
        if direction == "neutral":
            direction = bias_dir
        reasons.append(f"Volume bias: {vol_bias['description']}")

    # Absorption (max 4)
    if absorption["absorption"] != "none":
        abs_points = int(4 * absorption["strength"])
        abs_points = max(1, min(4, abs_points))
        points    += abs_points
        abs_dir    = "long" if absorption["absorption"] == "bullish" else "short"
        if direction == "neutral":
            direction = abs_dir
        reasons.append(f"Absorption: {absorption['description']}")

    # Price/volume divergence (max 4)
    if pv_div["divergence"] != "none":
        points += 4
        pv_dir  = "long" if pv_div["divergence"] == "bullish" else "short"
        if direction == "neutral":
            direction = pv_dir
        reasons.append(f"P/V divergence: {pv_div['description']}")

    points = min(20, points)

    log.debug(f"L2 score: {points}/20 | direction: {direction} | "
              f"{' | '.join(reasons)}")

    return {
        "layer":     "L2_order_flow",
        "score":     points,
        "max":       20,
        "direction": direction,
        "reasons":   reasons,
        "details": {
            "cvd_divergence": cvd_divergence,
            "volume_trend":   vol_trend,
            "volume_bias":    vol_bias,
            "absorption":     absorption,
            "pv_divergence":  pv_div,
        }
    }


def _empty_score(reason: str) -> dict:
    return {
        "layer":     "L2_order_flow",
        "score":     0,
        "max":       20,
        "direction": "neutral",
        "reasons":   [reason],
        "details":   {}
    }
