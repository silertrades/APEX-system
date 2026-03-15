# =============================================================================
# APEX SYSTEM — l6_sentiment.py
# =============================================================================
# Layer 6: Sentiment + Positioning
#
# What this does:
#   - Reads funding rates (crowded longs/shorts = contrarian signal)
#   - Analyzes open interest changes (smart money positioning)
#   - Detects long/short ratio extremes
#   - Measures fear/greed via volatility proxy
#
# Score: 0–15 points
#   15 = sentiment at extreme + positioning confirms direction
#   0  = sentiment neutral or working against trade
# =============================================================================

import numpy as np
import pandas as pd
import logging

from config import (
    FUNDING_EXTREME_LONG,
    FUNDING_EXTREME_SHORT,
    COT_EXTREME_PCT,
)

log = logging.getLogger("l6_sentiment")


# =============================================================================
# FUNDING RATE ANALYSIS
# =============================================================================

def analyze_funding_rate(funding_rate: float) -> dict:
    """
    Analyzes perpetual futures funding rate.

    Positive funding = longs pay shorts = market is long-biased
    Negative funding = shorts pay longs = market is short-biased

    EXTREME positive funding = overcrowded longs = bearish contrarian
    EXTREME negative funding = overcrowded shorts = bullish contrarian

    Mild positive funding in an uptrend = healthy, trend continues
    Mild negative funding in a downtrend = healthy, trend continues

    Returns:
        {
            "signal":      "bullish" | "bearish" | "neutral",
            "extreme":     bool,
            "description": str
        }
    """
    if funding_rate >= FUNDING_EXTREME_LONG:
        return {
            "signal":      "bearish",
            "extreme":     True,
            "description": f"Extreme positive funding ({funding_rate*100:.4f}%) "
                           f"— overcrowded longs, squeeze risk"
        }

    if funding_rate <= FUNDING_EXTREME_SHORT:
        return {
            "signal":      "bullish",
            "extreme":     True,
            "description": f"Extreme negative funding ({funding_rate*100:.4f}%) "
                           f"— overcrowded shorts, squeeze risk up"
        }

    if funding_rate > 0.01:
        return {
            "signal":      "bearish",
            "extreme":     False,
            "description": f"Elevated positive funding ({funding_rate*100:.4f}%) "
                           f"— slight long bias, watch for fade"
        }

    if funding_rate < -0.01:
        return {
            "signal":      "bullish",
            "extreme":     False,
            "description": f"Elevated negative funding ({funding_rate*100:.4f}%) "
                           f"— slight short bias, watch for squeeze"
        }

    return {
        "signal":      "neutral",
        "extreme":     False,
        "description": f"Neutral funding ({funding_rate*100:.4f}%) "
                       f"— no positioning extreme"
    }


# =============================================================================
# OPEN INTEREST ANALYSIS
# =============================================================================

def analyze_open_interest(oi_data: dict, candles: dict) -> dict:
    """
    Analyzes open interest changes relative to price.

    Price up + OI up    = new longs entering = bullish continuation
    Price up + OI down  = short covering = weak move, caution
    Price down + OI up  = new shorts entering = bearish continuation
    Price down + OI down = long liquidation = potential bottom

    Returns:
        {
            "signal":      "bullish" | "bearish" | "neutral",
            "description": str
        }
    """
    oi_change = oi_data.get("oi_change_pct", 0.0)
    mtf_df    = candles.get("MTF", pd.DataFrame())

    if mtf_df.empty or len(mtf_df) < 2:
        return {"signal": "neutral",
                "description": "Insufficient data for OI analysis"}

    # Price change over same period as OI
    price_change = (mtf_df["close"].iloc[-1] - mtf_df["close"].iloc[-24]) / \
                   (mtf_df["close"].iloc[-24] + 1e-9) \
                   if len(mtf_df) >= 24 else \
                   (mtf_df["close"].iloc[-1] - mtf_df["close"].iloc[0]) / \
                   (mtf_df["close"].iloc[0] + 1e-9)

    price_up = price_change > 0.005
    price_dn = price_change < -0.005
    oi_up    = oi_change    > 0.02
    oi_dn    = oi_change    < -0.02

    if price_up and oi_up:
        return {
            "signal":      "bullish",
            "description": f"Price up + OI up ({oi_change*100:.1f}%) "
                           f"— new longs entering, bullish continuation"
        }

    if price_dn and oi_up:
        return {
            "signal":      "bearish",
            "description": f"Price down + OI up ({oi_change*100:.1f}%) "
                           f"— new shorts entering, bearish continuation"
        }

    if price_up and oi_dn:
        return {
            "signal":      "neutral",
            "description": f"Price up + OI down ({oi_change*100:.1f}%) "
                           f"— short covering, weak bullish"
        }

    if price_dn and oi_dn:
        return {
            "signal":      "bullish",
            "description": f"Price down + OI down ({oi_change*100:.1f}%) "
                           f"— long liquidation exhaustion, potential bottom"
        }

    return {
        "signal":      "neutral",
        "description": f"OI change {oi_change*100:.1f}% — no clear signal"
    }


# =============================================================================
# FEAR AND GREED PROXY
# =============================================================================

def get_fear_greed_proxy(candles: dict) -> dict:
    """
    Approximates the Fear & Greed index using:
    - Price momentum (recent returns)
    - Volatility (realized vol)
    - Volume trend

    Score 0–100:
        0–25:  Extreme Fear  → contrarian bullish
        25–45: Fear          → mildly bullish
        45–55: Neutral
        55–75: Greed         → mildly bearish
        75–100: Extreme Greed → contrarian bearish

    Returns:
        {
            "score":       float (0–100),
            "sentiment":   "extreme_fear" | "fear" | "neutral" |
                           "greed" | "extreme_greed",
            "signal":      "bullish" | "bearish" | "neutral",
            "description": str
        }
    """
    mtf_df = candles.get("MTF", pd.DataFrame())
    htf_df = candles.get("HTF", pd.DataFrame())

    if mtf_df.empty or len(mtf_df) < 30:
        return {"score": 50.0, "sentiment": "neutral",
                "signal": "neutral", "description": "Insufficient data"}

    # Component 1: Price momentum (30-period)
    price_mom = (mtf_df["close"].iloc[-1] - mtf_df["close"].iloc[-30]) / \
                (mtf_df["close"].iloc[-30] + 1e-9)
    mom_score = min(100, max(0, 50 + price_mom * 200))

    # Component 2: Volatility (lower vol = more greed)
    returns   = mtf_df["close"].pct_change().tail(30)
    vol       = returns.std() * np.sqrt(30) * 100
    vol_score = min(100, max(0, 100 - vol * 3))

    # Component 3: Volume trend
    avg_vol    = mtf_df["volume"].tail(30).mean()
    recent_vol = mtf_df["volume"].tail(5).mean()
    vol_ratio  = recent_vol / (avg_vol + 1e-9)
    # High volume on up move = greed, high volume on down move = fear
    if price_mom > 0:
        vol_trend_score = min(100, 50 + (vol_ratio - 1) * 25)
    else:
        vol_trend_score = min(100, max(0, 50 - (vol_ratio - 1) * 25))

    # Weighted average
    fg_score = (mom_score * 0.5 + vol_score * 0.3 + vol_trend_score * 0.2)
    fg_score = round(fg_score, 1)

    if fg_score <= 25:
        return {
            "score":       fg_score,
            "sentiment":   "extreme_fear",
            "signal":      "bullish",
            "description": f"Extreme Fear ({fg_score:.0f}) — contrarian bullish"
        }
    elif fg_score <= 45:
        return {
            "score":       fg_score,
            "sentiment":   "fear",
            "signal":      "bullish",
            "description": f"Fear ({fg_score:.0f}) — mildly bullish contrarian"
        }
    elif fg_score <= 55:
        return {
            "score":       fg_score,
            "sentiment":   "neutral",
            "signal":      "neutral",
            "description": f"Neutral sentiment ({fg_score:.0f})"
        }
    elif fg_score <= 75:
        return {
            "score":       fg_score,
            "sentiment":   "greed",
            "signal":      "bearish",
            "description": f"Greed ({fg_score:.0f}) — mildly bearish contrarian"
        }
    else:
        return {
            "score":       fg_score,
            "sentiment":   "extreme_greed",
            "signal":      "bearish",
            "description": f"Extreme Greed ({fg_score:.0f}) "
                           f"— contrarian bearish, top risk"
        }


# =============================================================================
# LONG/SHORT RATIO
# =============================================================================

def get_long_short_ratio(funding_rate: float) -> dict:
    """
    Estimates long/short ratio from funding rate.
    Positive funding = more longs than shorts.

    Returns:
        {
            "estimated_long_pct":  float,
            "bias":                "long_heavy" | "short_heavy" | "balanced",
            "description":         str
        }
    """
    # Funding rate of 0.01% per 8h ≈ balanced
    # Each 0.01% above/below ≈ 2% more longs/shorts
    base       = 50.0
    long_pct   = min(90, max(10, base + funding_rate * 2000))
    short_pct  = 100 - long_pct

    if long_pct >= 65:
        bias = "long_heavy"
    elif short_pct >= 65:
        bias = "short_heavy"
    else:
        bias = "balanced"

    return {
        "estimated_long_pct":  round(long_pct, 1),
        "bias":                bias,
        "description":         f"Est. {long_pct:.0f}% longs / "
                               f"{short_pct:.0f}% shorts — {bias}"
    }


# =============================================================================
# MAIN SCORER
# =============================================================================

def score(data: dict) -> dict:
    """
    Main entry point — called by scoring_engine.py

    Score breakdown (max 15):
        Funding rate extreme:     +5  (contrarian signal)
        OI + price confluence:    +4  (smart money confirmation)
        Fear/Greed extreme:       +4  (contrarian signal)
        Long/short ratio extreme: +2  (positioning confirmation)
    """
    sentiment = data.get("sentiment", {})
    candles   = data.get("candles", {})

    funding_rate = sentiment.get("funding_rate", 0.0)
    oi_data      = sentiment.get("oi", {"oi": 0.0, "oi_change_pct": 0.0})

    # --- Run all sentiment checks ---
    funding   = analyze_funding_rate(funding_rate)
    oi        = analyze_open_interest(oi_data, candles)
    fear_greed = get_fear_greed_proxy(candles)
    ls_ratio  = get_long_short_ratio(funding_rate)

    # --- Build score ---
    points    = 0
    reasons   = []
    direction = "neutral"

    # Funding rate (max 5)
    if funding["signal"] != "neutral":
        if funding["extreme"]:
            points += 5
        else:
            points += 2
        fund_dir  = "long" if funding["signal"] == "bullish" else "short"
        direction = fund_dir
        reasons.append(f"Funding: {funding['description']}")

    # OI analysis (max 4)
    if oi["signal"] != "neutral":
        points  += 4
        oi_dir   = "long" if oi["signal"] == "bullish" else "short"
        if direction == "neutral":
            direction = oi_dir
        # Bonus if OI confirms funding direction
        if oi_dir == direction:
            points += 1
        reasons.append(f"OI: {oi['description']}")

    # Fear/Greed (max 4)
    if fear_greed["signal"] != "neutral":
        if fear_greed["sentiment"] in ["extreme_fear", "extreme_greed"]:
            points += 4
        else:
            points += 2
        fg_dir = "long" if fear_greed["signal"] == "bullish" else "short"
        if direction == "neutral":
            direction = fg_dir
        reasons.append(f"Fear/Greed: {fear_greed['description']}")

    # Long/short ratio (max 2)
    if ls_ratio["bias"] == "short_heavy":
        points   += 2
        if direction == "neutral":
            direction = "long"
        reasons.append(f"L/S ratio: {ls_ratio['description']}")
    elif ls_ratio["bias"] == "long_heavy":
        points   += 2
        if direction == "neutral":
            direction = "short"
        reasons.append(f"L/S ratio: {ls_ratio['description']}")

    points = min(15, points)

    log.debug(f"L6 score: {points}/15 | direction: {direction} | "
              f"{' | '.join(reasons)}")

    return {
        "layer":     "L6_sentiment",
        "score":     points,
        "max":       15,
        "direction": direction,
        "reasons":   reasons,
        "details": {
            "funding":    funding,
            "oi":         oi,
            "fear_greed": fear_greed,
            "ls_ratio":   ls_ratio,
        }
    }


def _empty_score(reason: str) -> dict:
    return {
        "layer":     "L6_sentiment",
        "score":     0,
        "max":       15,
        "direction": "neutral",
        "reasons":   [reason],
        "details":   {}
    }
