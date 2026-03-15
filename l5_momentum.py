# =============================================================================
# APEX SYSTEM — l5_momentum.py
# =============================================================================
# Layer 5: Multi-Timeframe Momentum
#
# What this does:
#   - Checks EMA stack alignment across all 4 timeframes
#   - Detects RSI hidden divergence (trend continuation signal)
#   - Reads MACD histogram compression + expansion
#   - Identifies momentum squeeze (Bollinger + Keltner compression)
#
# Score: 0–15 points
#   15 = all TFs aligned + RSI hidden div + MACD expansion
#   0  = momentum against direction or flat
# =============================================================================

import numpy as np
import pandas as pd
import logging

from config import (
    EMA_FAST, EMA_MID, EMA_SLOW, EMA_ANCHOR,
    RSI_PERIOD, RSI_OVERBOUGHT, RSI_OVERSOLD,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    TF_ALIGNMENT_MIN,
)

log = logging.getLogger("l5_momentum")


# =============================================================================
# INDICATORS
# =============================================================================

def calc_ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    Relative Strength Index.
    Returns a series of RSI values (0–100).
    """
    delta  = series.diff()
    gain   = delta.clip(lower=0)
    loss   = -delta.clip(upper=0)
    avg_g  = gain.ewm(com=period - 1, adjust=False).mean()
    avg_l  = loss.ewm(com=period - 1, adjust=False).mean()
    rs     = avg_g / (avg_l + 1e-10)
    return 100 - (100 / (1 + rs))


def calc_macd(series: pd.Series,
              fast:   int = MACD_FAST,
              slow:   int = MACD_SLOW,
              signal: int = MACD_SIGNAL) -> dict:
    """
    MACD — Moving Average Convergence Divergence.
    Returns macd line, signal line, and histogram.
    """
    ema_fast   = calc_ema(series, fast)
    ema_slow   = calc_ema(series, slow)
    macd_line  = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    histogram  = macd_line - signal_line

    return {
        "macd":      macd_line,
        "signal":    signal_line,
        "histogram": histogram,
    }


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range."""
    high  = df["high"]
    low   = df["low"]
    close = df["close"]
    tr    = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, adjust=False).mean()


# =============================================================================
# EMA STACK ALIGNMENT
# =============================================================================

def check_ema_alignment(df: pd.DataFrame) -> dict:
    """
    Checks if EMAs are in perfect bullish or bearish stack order.

    Bullish stack: price > EMA9 > EMA21 > EMA50 > EMA200
    Bearish stack: price < EMA9 < EMA21 < EMA50 < EMA200

    Returns:
        {
            "aligned":     "bullish" | "bearish" | "none",
            "strength":    float (0.0–1.0),
            "description": str
        }
    """
    if len(df) < EMA_ANCHOR + 10:
        return {"aligned": "none", "strength": 0.0,
                "description": "Insufficient data for EMA calculation"}

    close   = df["close"]
    ema9    = calc_ema(close, EMA_FAST).iloc[-1]
    ema21   = calc_ema(close, EMA_MID).iloc[-1]
    ema50   = calc_ema(close, EMA_SLOW).iloc[-1]
    ema200  = calc_ema(close, EMA_ANCHOR).iloc[-1]
    price   = close.iloc[-1]

    # Perfect bullish stack
    if price > ema9 > ema21 > ema50 > ema200:
        # Strength = how spread the EMAs are relative to price
        spread   = (ema9 - ema200) / price
        strength = min(1.0, spread * 20)
        return {
            "aligned":     "bullish",
            "strength":    round(strength, 3),
            "description": f"Perfect bullish EMA stack "
                           f"(9:{ema9:.0f} 21:{ema21:.0f} "
                           f"50:{ema50:.0f} 200:{ema200:.0f})"
        }

    # Perfect bearish stack
    if price < ema9 < ema21 < ema50 < ema200:
        spread   = (ema200 - ema9) / price
        strength = min(1.0, spread * 20)
        return {
            "aligned":     "bearish",
            "strength":    round(strength, 3),
            "description": f"Perfect bearish EMA stack "
                           f"(9:{ema9:.0f} 21:{ema21:.0f} "
                           f"50:{ema50:.0f} 200:{ema200:.0f})"
        }

    # Partial bullish (at least 3 of 4 in order)
    bullish_count = sum([
        price > ema9,
        ema9   > ema21,
        ema21  > ema50,
        ema50  > ema200,
    ])

    bearish_count = sum([
        price < ema9,
        ema9   < ema21,
        ema21  < ema50,
        ema50  < ema200,
    ])

    if bullish_count >= 3:
        return {
            "aligned":     "bullish",
            "strength":    round(bullish_count / 4, 3),
            "description": f"Partial bullish EMA stack ({bullish_count}/4)"
        }

    if bearish_count >= 3:
        return {
            "aligned":     "bearish",
            "strength":    round(bearish_count / 4, 3),
            "description": f"Partial bearish EMA stack ({bearish_count}/4)"
        }

    return {
        "aligned":     "none",
        "strength":    0.0,
        "description": f"EMA stack mixed — no clear alignment"
    }


# =============================================================================
# MULTI-TIMEFRAME EMA ALIGNMENT
# =============================================================================

def check_mtf_ema_alignment(candles: dict) -> dict:
    """
    Checks EMA alignment across all timeframes.
    Counts how many TFs have bullish vs bearish alignment.

    Returns:
        {
            "direction":   "bullish" | "bearish" | "mixed",
            "count":       int (how many TFs aligned),
            "total":       int,
            "description": str,
            "by_tf":       dict
        }
    """
    results    = {}
    bull_count = 0
    bear_count = 0

    for tf_name, df in candles.items():
        if not df.empty and len(df) > EMA_ANCHOR + 10:
            alignment = check_ema_alignment(df)
            results[tf_name] = alignment
            if alignment["aligned"] == "bullish":
                bull_count += 1
            elif alignment["aligned"] == "bearish":
                bear_count += 1

    total = len(results)

    if bull_count >= TF_ALIGNMENT_MIN:
        return {
            "direction":   "bullish",
            "count":       bull_count,
            "total":       total,
            "description": f"Bullish EMA alignment on {bull_count}/{total} TFs",
            "by_tf":       results,
        }

    if bear_count >= TF_ALIGNMENT_MIN:
        return {
            "direction":   "bearish",
            "count":       bear_count,
            "total":       total,
            "description": f"Bearish EMA alignment on {bear_count}/{total} TFs",
            "by_tf":       results,
        }

    dominant = "bullish" if bull_count > bear_count else "bearish"
    return {
        "direction":   "mixed",
        "count":       max(bull_count, bear_count),
        "total":       total,
        "description": f"Mixed EMA alignment — {bull_count} bull, "
                       f"{bear_count} bear of {total} TFs",
        "by_tf":       results,
    }


# =============================================================================
# RSI HIDDEN DIVERGENCE
# =============================================================================

def detect_rsi_hidden_divergence(df: pd.DataFrame) -> dict:
    """
    Hidden divergence = trend continuation signal.

    Bullish hidden divergence:
      Price makes Higher Low, RSI makes Lower Low
      → Pullback in an uptrend, buyers still in control

    Bearish hidden divergence:
      Price makes Lower High, RSI makes Higher High
      → Rally in a downtrend, sellers still in control

    This is different from regular divergence (which is reversal).
    Hidden divergence says: the trend is intact, keep going.

    Returns:
        {
            "divergence":  "bullish" | "bearish" | "none",
            "description": str
        }
    """
    if len(df) < RSI_PERIOD * 3:
        return {"divergence": "none", "description": "Insufficient data"}

    rsi    = calc_rsi(df["close"], RSI_PERIOD)
    prices = df["close"]

    # Look at two halves of recent data
    n      = min(50, len(df))
    mid    = n // 2

    price_first  = prices.iloc[-n:-mid]
    price_second = prices.iloc[-mid:]
    rsi_first    = rsi.iloc[-n:-mid]
    rsi_second   = rsi.iloc[-mid:]

    price_hl = price_second.min() > price_first.min()   # Higher low
    price_lh = price_second.max() < price_first.max()   # Lower high
    rsi_ll   = rsi_second.min()   < rsi_first.min()     # Lower RSI low
    rsi_hh   = rsi_second.max()   > rsi_first.max()     # Higher RSI high

    # Bullish hidden: price HL + RSI LL
    if price_hl and rsi_ll:
        rsi_val = rsi.iloc[-1]
        return {
            "divergence":  "bullish",
            "description": f"Bullish hidden div — price HL, RSI LL "
                           f"(RSI: {rsi_val:.1f}) — trend continuation up"
        }

    # Bearish hidden: price LH + RSI HH
    if price_lh and rsi_hh:
        rsi_val = rsi.iloc[-1]
        return {
            "divergence":  "bearish",
            "description": f"Bearish hidden div — price LH, RSI HH "
                           f"(RSI: {rsi_val:.1f}) — trend continuation down"
        }

    return {"divergence": "none",
            "description": "No RSI hidden divergence"}


def get_rsi_level(df: pd.DataFrame) -> dict:
    """
    Returns current RSI level and whether it's at an extreme.

    Returns:
        {
            "value":       float,
            "condition":   "overbought" | "oversold" | "neutral",
            "description": str
        }
    """
    if len(df) < RSI_PERIOD + 5:
        return {"value": 50.0, "condition": "neutral",
                "description": "Insufficient data"}

    rsi_val = calc_rsi(df["close"], RSI_PERIOD).iloc[-1]

    if rsi_val >= RSI_OVERBOUGHT:
        return {
            "value":       round(rsi_val, 1),
            "condition":   "overbought",
            "description": f"RSI overbought ({rsi_val:.1f}) — caution on longs"
        }
    elif rsi_val <= RSI_OVERSOLD:
        return {
            "value":       round(rsi_val, 1),
            "condition":   "oversold",
            "description": f"RSI oversold ({rsi_val:.1f}) — caution on shorts"
        }
    else:
        return {
            "value":       round(rsi_val, 1),
            "condition":   "neutral",
            "description": f"RSI neutral ({rsi_val:.1f})"
        }


# =============================================================================
# MACD ANALYSIS
# =============================================================================

def analyze_macd(df: pd.DataFrame) -> dict:
    """
    Analyzes MACD for:
    1. Histogram compression then expansion (momentum building)
    2. Zero line cross (trend change confirmation)
    3. Signal line cross (entry trigger)

    Returns:
        {
            "signal":      "bullish" | "bearish" | "none",
            "compression": bool,
            "cross":       bool,
            "description": str
        }
    """
    if len(df) < MACD_SLOW + MACD_SIGNAL + 5:
        return {"signal": "none", "compression": False,
                "cross": False, "description": "Insufficient data"}

    macd_data = calc_macd(df["close"])
    hist      = macd_data["histogram"]
    macd_line = macd_data["macd"]
    sig_line  = macd_data["signal"]

    current_hist = hist.iloc[-1]
    prev_hist    = hist.iloc[-2]
    prev2_hist   = hist.iloc[-3]

    # Detect compression (histogram getting smaller)
    compression = abs(prev_hist) < abs(prev2_hist) and \
                  abs(prev2_hist) < abs(hist.iloc[-4]) \
                  if len(hist) > 4 else False

    # Detect expansion (histogram growing after compression)
    expansion = abs(current_hist) > abs(prev_hist) and compression

    # Signal line cross
    cross = (macd_line.iloc[-1] > sig_line.iloc[-1]) != \
            (macd_line.iloc[-2] > sig_line.iloc[-2])

    # Zero line position
    above_zero = macd_line.iloc[-1] > 0

    if current_hist > 0 and expansion:
        return {
            "signal":      "bullish",
            "compression": compression,
            "cross":       cross,
            "description": "MACD bullish expansion — momentum accelerating up"
        }

    if current_hist < 0 and expansion:
        return {
            "signal":      "bearish",
            "compression": compression,
            "cross":       cross,
            "description": "MACD bearish expansion — momentum accelerating down"
        }

    if cross and above_zero:
        return {
            "signal":      "bullish",
            "compression": compression,
            "cross":       True,
            "description": "MACD bullish signal cross above zero"
        }

    if cross and not above_zero:
        return {
            "signal":      "bearish",
            "compression": compression,
            "cross":       True,
            "description": "MACD bearish signal cross below zero"
        }

    if current_hist > 0:
        return {
            "signal":      "bullish",
            "compression": compression,
            "cross":       False,
            "description": f"MACD histogram positive ({current_hist:.4f})"
        }

    return {
        "signal":      "bearish",
        "compression": compression,
        "cross":       False,
        "description": f"MACD histogram negative ({current_hist:.4f})"
    }


# =============================================================================
# MOMENTUM SQUEEZE
# =============================================================================

def detect_squeeze(df: pd.DataFrame, period: int = 20) -> dict:
    """
    Detects the momentum squeeze — when Bollinger Bands contract
    inside Keltner Channels. This signals a big move is coming.

    When BBands are inside Keltner = squeeze ON  (coiling)
    When BBands break outside      = squeeze OFF (explosive move)

    Returns:
        {
            "squeeze_on":  bool,
            "firing":      bool,
            "direction":   "bullish" | "bearish" | "none",
            "description": str
        }
    """
    if len(df) < period * 2:
        return {"squeeze_on": False, "firing": False,
                "direction": "none", "description": "Insufficient data"}

    close  = df["close"]
    high   = df["high"]
    low    = df["low"]

    # Bollinger Bands
    bb_mid  = close.rolling(period).mean()
    bb_std  = close.rolling(period).std()
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std

    # Keltner Channels
    atr      = calc_atr(df, period)
    kc_upper = bb_mid + 1.5 * atr
    kc_lower = bb_mid - 1.5 * atr

    # Current values
    curr_bb_upper = bb_upper.iloc[-1]
    curr_bb_lower = bb_lower.iloc[-1]
    curr_kc_upper = kc_upper.iloc[-1]
    curr_kc_lower = kc_lower.iloc[-1]
    prev_bb_upper = bb_upper.iloc[-2]
    prev_bb_lower = bb_lower.iloc[-2]
    prev_kc_upper = kc_upper.iloc[-2]
    prev_kc_lower = kc_lower.iloc[-2]

    # Squeeze ON: BBands inside Keltner
    squeeze_on = (curr_bb_upper < curr_kc_upper and
                  curr_bb_lower > curr_kc_lower)

    # Squeeze firing: was ON, now OFF
    prev_squeeze = (prev_bb_upper < prev_kc_upper and
                    prev_bb_lower > prev_kc_lower)
    firing = prev_squeeze and not squeeze_on

    if firing:
        # Direction based on price relative to midline
        direction = "bullish" if close.iloc[-1] > bb_mid.iloc[-1] \
                    else "bearish"
        return {
            "squeeze_on":  False,
            "firing":      True,
            "direction":   direction,
            "description": f"Squeeze FIRING {direction} — explosive move expected"
        }

    if squeeze_on:
        return {
            "squeeze_on":  True,
            "firing":      False,
            "direction":   "none",
            "description": "Squeeze ON — coiling, big move incoming"
        }

    return {
        "squeeze_on":  False,
        "firing":      False,
        "direction":   "none",
        "description": "No squeeze detected"
    }


# =============================================================================
# MAIN SCORER
# =============================================================================

def score(data: dict) -> dict:
    """
    Main entry point — called by scoring_engine.py

    Score breakdown (max 15):
        MTF EMA alignment:        +5
        RSI hidden divergence:    +4
        MACD signal:              +3
        Squeeze firing:           +3
    """
    candles = data.get("candles", {})
    mtf_df  = candles.get("MTF", pd.DataFrame())
    ltf_df  = candles.get("LTF", pd.DataFrame())
    htf_df  = candles.get("HTF", pd.DataFrame())

    if mtf_df.empty:
        return _empty_score("No MTF data")

    # --- Run all momentum checks ---
    mtf_ema    = check_mtf_ema_alignment(candles)
    rsi_hidden = detect_rsi_hidden_divergence(mtf_df)
    rsi_level  = get_rsi_level(mtf_df)
    macd       = analyze_macd(mtf_df)
    squeeze    = detect_squeeze(ltf_df) if not ltf_df.empty else \
                 {"squeeze_on": False, "firing": False,
                  "direction": "none", "description": "No LTF data"}

    # --- Build score ---
    points    = 0
    reasons   = []
    direction = "neutral"

    # MTF EMA alignment (max 5)
    if mtf_ema["direction"] != "mixed":
        ema_points = min(5, mtf_ema["count"] + 1)
        points    += ema_points
        direction  = "long" if mtf_ema["direction"] == "bullish" else "short"
        reasons.append(f"EMA: {mtf_ema['description']}")

    # RSI hidden divergence (max 4)
    if rsi_hidden["divergence"] != "none":
        points   += 4
        rsi_dir   = "long" if rsi_hidden["divergence"] == "bullish" else "short"
        if direction == "neutral":
            direction = rsi_dir
        reasons.append(f"RSI: {rsi_hidden['description']}")

    # Add RSI level context (no points — just penalize if extreme against us)
    if rsi_level["condition"] == "overbought" and direction == "long":
        points = max(0, points - 2)
        reasons.append(f"RSI caution: {rsi_level['description']}")
    elif rsi_level["condition"] == "oversold" and direction == "short":
        points = max(0, points - 2)
        reasons.append(f"RSI caution: {rsi_level['description']}")

    # MACD (max 3)
    if macd["signal"] != "none":
        macd_dir = "long" if macd["signal"] == "bullish" else "short"
        if macd["cross"] or (macd_dir == direction):
            macd_pts = 3 if macd["cross"] else 2
            points  += macd_pts
            if direction == "neutral":
                direction = macd_dir
            reasons.append(f"MACD: {macd['description']}")

    # Squeeze (max 3)
    if squeeze["firing"]:
        points   += 3
        sq_dir    = "long" if squeeze["direction"] == "bullish" else "short"
        if direction == "neutral":
            direction = sq_dir
        reasons.append(f"Squeeze: {squeeze['description']}")
    elif squeeze["squeeze_on"]:
        points += 1
        reasons.append(f"Squeeze: {squeeze['description']}")

    points = min(15, points)

    log.debug(f"L5 score: {points}/15 | direction: {direction} | "
              f"{' | '.join(reasons)}")

    return {
        "layer":     "L5_momentum",
        "score":     points,
        "max":       15,
        "direction": direction,
        "reasons":   reasons,
        "details": {
            "mtf_ema":     mtf_ema,
            "rsi_hidden":  rsi_hidden,
            "rsi_level":   rsi_level,
            "macd":        macd,
            "squeeze":     squeeze,
        }
    }


def _empty_score(reason: str) -> dict:
    return {
        "layer":     "L5_momentum",
        "score":     0,
        "max":       15,
        "direction": "neutral",
        "reasons":   [reason],
        "details":   {}
    }
