# =============================================================================
# APEX SYSTEM — l4_macro.py
# =============================================================================
# Layer 4: Macro + Volatility Regime
#
# What this does:
#   - Reads the volatility environment (VIX proxy from BTC realized vol)
#   - Determines risk-on vs risk-off regime
#   - Detects trend vs mean-reversion market conditions
#   - Classifies the current regime for position sizing
#
# Score: 0–15 points
#   15 = macro strongly supports the trade direction
#   0  = macro is working against the trade
# =============================================================================

import numpy as np
import pandas as pd
import logging

from config import (
    VIX_RISK_OFF_THRESHOLD,
    DXY_MOMENTUM_PERIOD,
)

log = logging.getLogger("l4_macro")


# =============================================================================
# VOLATILITY REGIME
# =============================================================================

def classify_vol_regime(vix: float) -> dict:
    """
    Classifies the volatility environment.

    Low vol  (VIX < 15): Trending, momentum strategies work best
    Mid vol  (VIX 15-25): Normal, all strategies viable
    High vol (VIX > 25): Mean reversion, reduce size, be selective
    Extreme  (VIX > 35): Crisis mode, only short or cash

    Returns:
        {
            "regime":      "low" | "mid" | "high" | "extreme",
            "risk_on":     bool,
            "description": str
        }
    """
    if vix < 15:
        return {
            "regime":      "low",
            "risk_on":     True,
            "description": f"Low vol ({vix:.1f}) — trending conditions, "
                           f"momentum strategies favored"
        }
    elif vix < VIX_RISK_OFF_THRESHOLD:
        return {
            "regime":      "mid",
            "risk_on":     True,
            "description": f"Mid vol ({vix:.1f}) — normal conditions, "
                           f"all strategies viable"
        }
    elif vix < 35:
        return {
            "regime":      "high",
            "risk_on":     False,
            "description": f"High vol ({vix:.1f}) — risk-off, "
                           f"reduce size, mean reversion favored"
        }
    else:
        return {
            "regime":      "extreme",
            "risk_on":     False,
            "description": f"Extreme vol ({vix:.1f}) — crisis conditions, "
                           f"cash or short only"
        }


# =============================================================================
# TREND VS MEAN REVERSION REGIME
# =============================================================================

def classify_market_regime(df: pd.DataFrame, period: int = 20) -> dict:
    """
    Determines if the market is trending or mean-reverting
    using the ADX concept (simplified) and Hurst exponent proxy.

    Trending:       Price making consistent directional moves
    Mean-reverting: Price oscillating around a mean

    Uses a simplified approach:
    - Calculate the ratio of absolute price change to total path length
    - High ratio = trending (efficient movement)
    - Low ratio  = mean reverting (choppy, inefficient)

    Returns:
        {
            "regime":      "trending" | "mean_reverting" | "neutral",
            "strength":    float (0.0–1.0),
            "description": str
        }
    """
    if len(df) < period * 2:
        return {
            "regime":      "neutral",
            "strength":    0.5,
            "description": "Insufficient data for regime classification"
        }

    recent = df["close"].tail(period).values

    # Net displacement vs total path
    net_move   = abs(recent[-1] - recent[0])
    total_path = sum(abs(recent[i] - recent[i-1])
                     for i in range(1, len(recent)))

    if total_path == 0:
        return {
            "regime":      "neutral",
            "strength":    0.5,
            "description": "No price movement"
        }

    efficiency = net_move / total_path

    if efficiency >= 0.6:
        return {
            "regime":      "trending",
            "strength":    round(efficiency, 3),
            "description": f"Trending market (efficiency: {efficiency:.2f}) "
                           f"— momentum strategies favored"
        }
    elif efficiency <= 0.3:
        return {
            "regime":      "mean_reverting",
            "strength":    round(1 - efficiency, 3),
            "description": f"Mean-reverting market (efficiency: {efficiency:.2f}) "
                           f"— fading strategies favored"
        }
    else:
        return {
            "regime":      "neutral",
            "strength":    round(efficiency, 3),
            "description": f"Neutral regime (efficiency: {efficiency:.2f}) "
                           f"— selective entries only"
        }


# =============================================================================
# DXY REGIME (CRYPTO PROXY)
# =============================================================================

def classify_dxy_regime(dxy_momentum: float) -> dict:
    """
    Classifies the DXY (dollar) environment.
    For crypto we use inverse BTC momentum as a proxy.

    Strong dollar (DXY up) = risk-off = headwind for crypto longs
    Weak dollar  (DXY dn)  = risk-on  = tailwind for crypto longs

    Returns:
        {
            "regime":      "risk_on" | "risk_off" | "neutral",
            "description": str
        }
    """
    if dxy_momentum < -0.02:
        return {
            "regime":      "risk_on",
            "description": f"Dollar weakening ({dxy_momentum*100:.1f}%) "
                           f"— tailwind for crypto longs"
        }
    elif dxy_momentum > 0.02:
        return {
            "regime":      "risk_off",
            "description": f"Dollar strengthening ({dxy_momentum*100:.1f}%) "
                           f"— headwind for crypto longs"
        }
    else:
        return {
            "regime":      "neutral",
            "description": f"Dollar neutral ({dxy_momentum*100:.1f}%) "
                           f"— no macro bias"
        }


# =============================================================================
# YIELD CURVE
# =============================================================================

def classify_yield_curve(slope: float) -> dict:
    """
    Classifies the yield curve environment.
    Currently returns neutral for crypto-only mode.
    Will be enhanced when futures data is added.

    Returns:
        {
            "regime":      "normal" | "flat" | "inverted",
            "description": str
        }
    """
    if slope > 1.0:
        return {
            "regime":      "normal",
            "description": f"Normal yield curve (+{slope:.2f}) "
                           f"— growth environment"
        }
    elif slope > 0:
        return {
            "regime":      "flat",
            "description": f"Flat yield curve ({slope:.2f}) "
                           f"— caution, slowdown risk"
        }
    else:
        return {
            "regime":      "inverted",
            "description": f"Inverted yield curve ({slope:.2f}) "
                           f"— recession risk, risk-off"
        }


# =============================================================================
# OVERALL REGIME CLASSIFIER
# =============================================================================

def get_overall_regime(vol_regime: dict,
                       market_regime: dict,
                       dxy_regime: dict,
                       yield_regime: dict) -> dict:
    """
    Combines all regime signals into one overall classification.

    Returns:
        {
            "mode":        "trend" | "mean_reversion" | "breakout" | "avoid",
            "risk_level":  "low" | "medium" | "high",
            "description": str
        }
    """
    is_risk_on    = vol_regime["risk_on"]
    is_trending   = market_regime["regime"] == "trending"
    is_mean_rev   = market_regime["regime"] == "mean_reverting"
    is_crisis     = vol_regime["regime"] == "extreme"
    dxy_risk_on   = dxy_regime["regime"] == "risk_on"
    dxy_risk_off  = dxy_regime["regime"] == "risk_off"

    # Crisis — avoid or short only
    if is_crisis:
        return {
            "mode":        "avoid",
            "risk_level":  "high",
            "description": "Crisis conditions — avoid longs, reduce all exposure"
        }

    # Best conditions: low vol + trending + risk on
    if is_risk_on and is_trending and not dxy_risk_off:
        return {
            "mode":        "trend",
            "risk_level":  "low",
            "description": "Ideal trend conditions — full size momentum entries"
        }

    # Mean reversion conditions
    if is_risk_on and is_mean_rev:
        return {
            "mode":        "mean_reversion",
            "risk_level":  "medium",
            "description": "Mean reversion conditions — fade extremes, "
                           "tight targets"
        }

    # High vol trending — breakout mode
    if not is_risk_on and is_trending:
        return {
            "mode":        "breakout",
            "risk_level":  "medium",
            "description": "High vol trend — breakout entries only, "
                           "wider stops"
        }

    # Default
    return {
        "mode":        "mean_reversion",
        "risk_level":  "medium",
        "description": "Mixed conditions — selective entries, "
                       "reduced size"
    }


# =============================================================================
# MAIN SCORER
# =============================================================================

def score(data: dict) -> dict:
    """
    Main entry point — called by scoring_engine.py

    Score breakdown (max 15):
        Vol regime supports trade:    +5
        Market regime matches mode:   +4
        DXY regime supports trade:    +3
        Yield curve supports trade:   +3
    """
    macro     = data.get("macro", {})
    candles   = data.get("candles", {})
    mtf_df    = candles.get("MTF", pd.DataFrame())

    vix       = macro.get("vix", 20.0)
    dxy_mom   = macro.get("dxy_momentum", 0.0)
    yc_slope  = macro.get("yield_curve_slope", 1.0)

    # --- Classify regimes ---
    vol_regime    = classify_vol_regime(vix)
    market_regime = classify_market_regime(mtf_df) if not mtf_df.empty else \
                    {"regime": "neutral", "strength": 0.5,
                     "description": "No data"}
    dxy_regime    = classify_dxy_regime(dxy_mom)
    yield_regime  = classify_yield_curve(yc_slope)
    overall       = get_overall_regime(vol_regime, market_regime,
                                       dxy_regime, yield_regime)

    # --- Build score ---
    points    = 0
    reasons   = []
    direction = "neutral"

    # Vol regime (max 5)
    if vol_regime["regime"] == "low":
        points += 5
        reasons.append(f"Vol regime: {vol_regime['description']}")
    elif vol_regime["regime"] == "mid":
        points += 3
        reasons.append(f"Vol regime: {vol_regime['description']}")
    elif vol_regime["regime"] == "high":
        points += 1
        reasons.append(f"Vol regime: {vol_regime['description']}")
    else:
        # Extreme vol — macro is working against us
        points += 0
        reasons.append(f"Vol regime: {vol_regime['description']}")

    # Market regime (max 4)
    if overall["mode"] == "trend":
        points += 4
        reasons.append(f"Market regime: {market_regime['description']}")
    elif overall["mode"] == "mean_reversion":
        points += 2
        reasons.append(f"Market regime: {market_regime['description']}")
    elif overall["mode"] == "breakout":
        points += 3
        reasons.append(f"Market regime: {market_regime['description']}")

    # DXY regime (max 3)
    if dxy_regime["regime"] == "risk_on":
        points += 3
        direction = "long"
        reasons.append(f"DXY: {dxy_regime['description']}")
    elif dxy_regime["regime"] == "neutral":
        points += 2
        reasons.append(f"DXY: {dxy_regime['description']}")
    else:
        points += 0
        reasons.append(f"DXY: {dxy_regime['description']}")

    # Yield curve (max 3)
    if yield_regime["regime"] == "normal":
        points += 3
        reasons.append(f"Yield curve: {yield_regime['description']}")
    elif yield_regime["regime"] == "flat":
        points += 1
        reasons.append(f"Yield curve: {yield_regime['description']}")
    else:
        points += 0
        reasons.append(f"Yield curve: {yield_regime['description']}")

    points = min(15, points)

    log.debug(f"L4 score: {points}/15 | regime: {overall['mode']} | "
              f"{' | '.join(reasons)}")

    return {
        "layer":     "L4_macro",
        "score":     points,
        "max":       15,
        "direction": direction,
        "reasons":   reasons,
        "details": {
            "vol_regime":    vol_regime,
            "market_regime": market_regime,
            "dxy_regime":    dxy_regime,
            "yield_regime":  yield_regime,
            "overall":       overall,
        }
    }


def _empty_score(reason: str) -> dict:
    return {
        "layer":     "L4_macro",
        "score":     0,
        "max":       15,
        "direction": "neutral",
        "reasons":   [reason],
        "details":   {}
    }
