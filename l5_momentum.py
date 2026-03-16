# =============================================================================
# APEX SYSTEM — l5_momentum.py
# =============================================================================
# Layer 5: Multi-Timeframe Momentum
#
# Scoring audit changes:
#   - RSI overbought no longer penalizes in trending conditions
#   - RSI overbought/oversold now ADDS points as confirmation
#     (overbought in uptrend = strong momentum, not a warning)
#   - MACD scoring more graduated
#   - EMA alignment scoring more generous for partial alignment
#   - Overall: should score 8-12/15 in trending conditions
#
# Score: 0-15 points
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
    return series.ewm(span=period, adjust=False).mean()


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
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
    ema_fast    = calc_ema(series, fast)
    ema_slow    = calc_ema(series, slow)
    macd_line   = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    histogram   = macd_line - signal_line
    return {
        "macd":      macd_line,
        "signal":    signal_line,
        "histogram": histogram,
    }


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
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
    Checks EMA stack alignment.
    Now awards partial points for 2/4 or 3/4 alignment.
    """
    if len(df) < EMA_ANCHOR + 10:
        return {"aligned": "none", "strength": 0.0,
                "count": 0,
                "description": "Insufficient data"}

    close  = df["close"]
    ema9   = calc_ema(close, EMA_FAST).iloc[-1]
    ema21  = calc_ema(close, EMA_MID).iloc[-1]
    ema50  = calc_ema(close, EMA_SLOW).iloc[-1]
    ema200 = calc_ema(close, EMA_ANCHOR).iloc[-1]
    price  = close.iloc[-1]

    bull_count = sum([
        price > ema9,
        ema9   > ema21,
        ema21  > ema50,
        ema50  > ema200,
    ])

    bear_count = sum([
        price < ema9,
        ema9   < ema21,
        ema21  < ema50,
        ema50  < ema200,
    ])

    if bull_count == 4:
        spread   = (ema9 - ema200) / price
        strength = min(1.0, spread * 20)
        return {
            "aligned":     "bullish",
            "strength":    round(strength, 3),
            "count":       4,
            "description": f"Perfect bullish EMA stack (4/4)"
        }

    if bear_count == 4:
        spread   = (ema200 - ema9) / price
        strength = min(1.0, spread * 20)
        return {
            "aligned":     "bearish",
            "strength":    round(strength, 3),
            "count":       4,
            "description": f"Perfect bearish EMA stack (4/4)"
        }

    if bull_count >= 3:
        return {
            "aligned":     "bullish",
            "strength":    round(bull_count / 4, 3),
            "count":       bull_count,
            "description": f"Bullish EMA alignment ({bull_count}/4)"
        }

    if bear_count >= 3:
        return {
            "aligned":     "bearish",
            "strength":    round(bear_count / 4, 3),
            "count":       bear_count,
            "description": f"Bearish EMA alignment ({bear_count}/4)"
        }

    if bull_count == 2:
        return {
            "aligned":     "bullish",
            "strength":    0.3,
            "count":       2,
            "description": f"Weak bullish EMA alignment (2/4)"
        }

    if bear_count == 2:
        return {
            "aligned":     "bearish",
            "strength":    0.3,
            "count":       2,
            "description": f"Weak bearish EMA alignment (2/4)"
        }

    return {
        "aligned":     "none",
        "strength":    0.0,
        "count":       0,
        "description": "EMA stack mixed"
    }


# =============================================================================
# MULTI-TIMEFRAME EMA ALIGNMENT
# =============================================================================

def check_mtf_ema_alignment(candles: dict) -> dict:
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

    dominant = "bullish" if bull_count >= bear_count else "bearish"
    return {
        "direction":   dominant,
        "count":       max(bull_count, bear_count),
        "total":       total,
        "description": f"Partial {dominant} EMA — "
                       f"{bull_count} bull, {bear_count} bear of {total} TFs",
        "by_tf":       results,
    }


# =============================================================================
# RSI ANALYSIS — trending aware
# =============================================================================

def analyze_rsi(df: pd.DataFrame, direction: str,
                regime: str = "neutral") -> dict:
    """
    RSI analysis that understands trending conditions.

    In a TRENDING market:
      - Overbought (>70) on a LONG signal = strong momentum, ADD points
      - Oversold  (<30) on a SHORT signal = strong momentum, ADD points
      - Overbought on a SHORT = caution, small penalty
      - Oversold   on a LONG  = caution, small penalty

    In a NON-TRENDING market:
      - Overbought = caution on longs (original behavior)
      - Oversold   = caution on shorts (original behavior)

    Returns:
        {
            "value":       float,
            "condition":   str,
            "points":      int  (+2 to -1),
            "description": str
        }
    """
    if len(df) < RSI_PERIOD + 5:
        return {"value": 50.0, "condition": "neutral",
                "points": 0, "description": "Insufficient data"}

    rsi_val   = calc_rsi(df["close"], RSI_PERIOD).iloc[-1]
    is_trend  = regime in ["trend", "trending", "low"]

    if rsi_val >= RSI_OVERBOUGHT:
        if direction == "long" and is_trend:
            # Overbought in uptrend = strong momentum confirmation
            return {
                "value":       round(rsi_val, 1),
                "condition":   "overbought_trending",
                "points":      2,
                "description": f"RSI overbought ({rsi_val:.1f}) in trend "
                               f"— strong momentum confirmation"
            }
        elif direction == "short":
            # Overbought = good for shorts
            return {
                "value":       round(rsi_val, 1),
                "condition":   "overbought",
                "points":      1,
                "description": f"RSI overbought ({rsi_val:.1f}) "
                               f"— confirms short bias"
            }
        else:
            # Overbought on long in non-trend = slight caution
            return {
                "value":       round(rsi_val, 1),
                "condition":   "overbought",
                "points":      -1,
                "description": f"RSI overbought ({rsi_val:.1f}) "
                               f"— caution on longs"
            }

    elif rsi_val <= RSI_OVERSOLD:
        if direction == "short" and is_trend:
            return {
                "value":       round(rsi_val, 1),
                "condition":   "oversold_trending",
                "points":      2,
                "description": f"RSI oversold ({rsi_val:.1f}) in trend "
                               f"— strong momentum confirmation"
            }
        elif direction == "long":
            return {
                "value":       round(rsi_val, 1),
                "condition":   "oversold",
                "points":      1,
                "description": f"RSI oversold ({rsi_val:.1f}) "
                               f"— confirms long bias"
            }
        else:
            return {
                "value":       round(rsi_val, 1),
                "condition":   "oversold",
                "points":      -1,
                "description": f"RSI oversold ({rsi_val:.1f}) "
                               f"— caution on shorts"
            }

    # Neutral RSI
    return {
        "value":       round(rsi_val, 1),
        "condition":   "neutral",
        "points":      0,
        "description": f"RSI neutral ({rsi_val:.1f})"
    }


def detect_rsi_hidden_divergence(df: pd.DataFrame) -> dict:
    """
    Hidden divergence = trend continuation signal.
    Bullish: price HL + RSI LL → trend continuation up
    Bearish: price LH + RSI HH → trend continuation down
    """
    if len(df) < RSI_PERIOD * 3:
        return {"divergence": "none", "description": "Insufficient data"}

    rsi    = calc_rsi(df["close"], RSI_PERIOD)
    prices = df["close"]
    n      = min(50, len(df))
    mid    = n // 2

    price_first  = prices.iloc[-n:-mid]
    price_second = prices.iloc[-mid:]
    rsi_first    = rsi.iloc[-n:-mid]
    rsi_second   = rsi.iloc[-mid:]

    price_hl = price_second.min() > price_first.min()
    price_lh = price_second.max() < price_first.max()
    rsi_ll   = rsi_second.min()   < rsi_first.min()
    rsi_hh   = rsi_second.max()   > rsi_first.max()

    if price_hl and rsi_ll:
        return {
            "divergence":  "bullish",
            "description": f"Bullish hidden div — price HL, RSI LL "
                           f"— trend continuation up"
        }

    if price_lh and rsi_hh:
        return {
            "divergence":  "bearish",
            "description": f"Bearish hidden div — price LH, RSI HH "
                           f"— trend continuation down"
        }

    return {"divergence": "none",
            "description": "No RSI hidden divergence"}


# =============================================================================
# MACD ANALYSIS — more graduated
# =============================================================================

def analyze_macd(df: pd.DataFrame) -> dict:
    if len(df) < MACD_SLOW + MACD_SIGNAL + 5:
        return {"signal": "none", "compression": False,
                "cross": False, "description": "Insufficient data",
                "strength": 0.0}

    macd_data    = calc_macd(df["close"])
    hist         = macd_data["histogram"]
    macd_line    = macd_data["macd"]
    sig_line     = macd_data["signal"]

    current_hist = hist.iloc[-1]
    prev_hist    = hist.iloc[-2]
    prev2_hist   = hist.iloc[-3]

    compression  = abs(prev_hist) < abs(prev2_hist) and \
                   abs(prev2_hist) < abs(hist.iloc[-4]) \
                   if len(hist) > 4 else False

    expansion    = abs(current_hist) > abs(prev_hist) and compression
    cross        = (macd_line.iloc[-1] > sig_line.iloc[-1]) != \
                   (macd_line.iloc[-2] > sig_line.iloc[-2])
    above_zero   = macd_line.iloc[-1] > 0

    # Measure strength by histogram size relative to price
    price        = df["close"].iloc[-1]
    hist_strength = min(1.0, abs(current_hist) / (price * 0.001 + 1e-9))

    if current_hist > 0 and expansion:
        return {"signal": "bullish", "compression": compression,
                "cross": cross, "strength": hist_strength,
                "description": "MACD bullish expansion — momentum accelerating"}

    if current_hist < 0 and expansion:
        return {"signal": "bearish", "compression": compression,
                "cross": cross, "strength": hist_strength,
                "description": "MACD bearish expansion — momentum accelerating"}

    if cross and above_zero:
        return {"signal": "bullish", "compression": compression,
                "cross": True, "strength": 0.8,
                "description": "MACD bullish signal cross above zero"}

    if cross and not above_zero:
        return {"signal": "bearish", "compression": compression,
                "cross": True, "strength": 0.8,
                "description": "MACD bearish signal cross below zero"}

    if current_hist > 0:
        return {"signal": "bullish", "compression": compression,
                "cross": False, "strength": hist_strength,
                "description": f"MACD histogram positive ({current_hist:.4f})"}

    return {"signal": "bearish", "compression": compression,
            "cross": False, "strength": hist_strength,
            "description": f"MACD histogram negative ({current_hist:.4f})"}


# =============================================================================
# MOMENTUM SQUEEZE
# =============================================================================

def detect_squeeze(df: pd.DataFrame, period: int = 20) -> dict:
    if len(df) < period * 2:
        return {"squeeze_on": False, "firing": False,
                "direction": "none", "description": "Insufficient data"}

    close    = df["close"]
    bb_mid   = close.rolling(period).mean()
    bb_std   = close.rolling(period).std()
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    atr      = calc_atr(df, period)
    kc_upper = bb_mid + 1.5 * atr
    kc_lower = bb_mid - 1.5 * atr

    curr_bb_upper = bb_upper.iloc[-1]
    curr_bb_lower = bb_lower.iloc[-1]
    curr_kc_upper = kc_upper.iloc[-1]
    curr_kc_lower = kc_lower.iloc[-1]
    prev_bb_upper = bb_upper.iloc[-2]
    prev_bb_lower = bb_lower.iloc[-2]
    prev_kc_upper = kc_upper.iloc[-2]
    prev_kc_lower = kc_lower.iloc[-2]

    squeeze_on   = (curr_bb_upper < curr_kc_upper and
                    curr_bb_lower > curr_kc_lower)
    prev_squeeze = (prev_bb_upper < prev_kc_upper and
                    prev_bb_lower > prev_kc_lower)
    firing       = prev_squeeze and not squeeze_on

    if firing:
        direction = "bullish" if close.iloc[-1] > bb_mid.iloc[-1] \
                    else "bearish"
        return {"squeeze_on": False, "firing": True, "direction": direction,
                "description": f"Squeeze FIRING {direction} — big move expected"}

    if squeeze_on:
        return {"squeeze_on": True, "firing": False, "direction": "none",
                "description": "Squeeze ON — coiling, big move incoming"}

    return {"squeeze_on": False, "firing": False, "direction": "none",
            "description": "No squeeze"}


# =============================================================================
# MAIN SCORER
# =============================================================================

def score(data: dict) -> dict:
    """
    Score breakdown (max 15):
        MTF EMA alignment:        0-5  (graduated by count and strength)
        RSI analysis:             0-3  (trending-aware, can add OR subtract)
        RSI hidden divergence:    0-3
        MACD signal:              0-2
        Squeeze:                  0-2
    """
    candles = data.get("candles", {})
    mtf_df  = candles.get("MTF", pd.DataFrame())
    ltf_df  = candles.get("LTF", pd.DataFrame())

    if mtf_df.empty:
        return _empty_score("No MTF data")

    # Get regime from macro data for RSI interpretation
    macro_data = data.get("macro", {})
    # We'll derive regime from VIX as proxy
    vix    = macro_data.get("vix", 20.0)
    regime = "trend" if vix < 20 else "neutral"

    mtf_ema    = check_mtf_ema_alignment(candles)
    rsi_hidden = detect_rsi_hidden_divergence(mtf_df)
    macd       = analyze_macd(mtf_df)
    squeeze    = detect_squeeze(ltf_df) if not ltf_df.empty else \
                 {"squeeze_on": False, "firing": False,
                  "direction": "none", "description": "No LTF data"}

    points    = 0
    reasons   = []
    direction = "neutral"

    # MTF EMA alignment (max 5)
    if mtf_ema["direction"] != "none":
        # Full 5 for 4/4, 4 for 3/4, 2 for 2/4
        count = mtf_ema["count"]
        if count >= 4:
            ema_points = 5
        elif count >= 3:
            ema_points = 4
        elif count >= 2:
            ema_points = 2
        else:
            ema_points = 0

        if ema_points > 0:
            points   += ema_points
            direction = "long" if mtf_ema["direction"] == "bullish" else "short"
            reasons.append(f"EMA: {mtf_ema['description']}")

    # RSI — trending aware (max +3, min -1)
    rsi_result = analyze_rsi(mtf_df, direction, regime)
    rsi_points = rsi_result["points"]
    if rsi_points != 0:
        points += rsi_points
        reasons.append(f"RSI: {rsi_result['description']}")

    # RSI hidden divergence (max 3)
    if rsi_hidden["divergence"] != "none":
        points  += 3
        hd_dir   = "long" if rsi_hidden["divergence"] == "bullish" else "short"
        if direction == "neutral":
            direction = hd_dir
        reasons.append(f"RSI hidden div: {rsi_hidden['description']}")

    # MACD (max 2 — reduced from 3, more conservative)
    if macd["signal"] != "none":
        macd_dir = "long" if macd["signal"] == "bullish" else "short"
        if macd["cross"] or (macd_dir == direction):
            macd_pts = 2 if macd["cross"] else 1
            points  += macd_pts
            if direction == "neutral":
                direction = macd_dir
            reasons.append(f"MACD: {macd['description']}")

    # Squeeze (max 2)
    if squeeze["firing"]:
        points  += 2
        sq_dir   = "long" if squeeze["direction"] == "bullish" else "short"
        if direction == "neutral":
            direction = sq_dir
        reasons.append(f"Squeeze: {squeeze['description']}")
    elif squeeze["squeeze_on"]:
        points += 1
        reasons.append(f"Squeeze building: {squeeze['description']}")

    points = max(0, min(15, points))

    log.debug(f"L5 score: {points}/15 | direction: {direction} | "
              f"{' | '.join(reasons)}")

    return {
        "layer":     "L5_momentum",
        "score":     points,
        "max":       15,
        "direction": direction,
        "reasons":   reasons,
        "details": {
            "mtf_ema":    mtf_ema,
            "rsi":        rsi_result,
            "rsi_hidden": rsi_hidden,
            "macd":       macd,
            "squeeze":    squeeze,
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
