# =============================================================================
# APEX SYSTEM — l3_zones.py
# =============================================================================
# Layer 3: Institutional Zones
#
# What this does:
#   - Identifies Order Blocks (OB) — last opposing candle before
#     a strong impulsive move. This is where institutions placed orders.
#   - Identifies Fair Value Gaps (FVG) — price inefficiencies where
#     the market moved so fast a two-sided market never formed.
#     These act as magnets — price almost always returns to fill them.
#   - Detects liquidity pools — equal highs/lows where stop losses
#     are clustered. Institutions hunt these before reversing.
#   - Scores proximity — how close is current price to a key zone?
#
# Score: 0–15 points
#   15 = price at unmitigated OB + FVG + liquidity swept
#   0  = price in no man's land, no key zones nearby
# =============================================================================

import numpy as np
import pandas as pd
import logging

log = logging.getLogger("l3_zones")


# =============================================================================
# ORDER BLOCKS
# =============================================================================

def find_order_blocks(df: pd.DataFrame, lookback: int = 50) -> list:
    """
    Finds Order Blocks — the last bearish candle before a bullish
    impulse (bullish OB) or last bullish candle before a bearish
    impulse (bearish OB).

    An impulse is defined as 3+ consecutive candles in one direction
    with expanding range.

    Returns list of dicts:
        {
            "type":   "bullish" | "bearish",
            "top":    float,
            "bottom": float,
            "index":  int,
            "mitigated": bool
        }
    """
    obs     = []
    recent  = df.tail(lookback).reset_index(drop=True)
    n       = len(recent)

    for i in range(2, n - 3):
        candle = recent.iloc[i]

        # Look for 3 consecutive bullish candles after this point
        next_3 = recent.iloc[i+1:i+4]
        all_bullish = all(next_3["close"] > next_3["open"])
        strong_move = (next_3["close"].iloc[-1] - next_3["open"].iloc[0]) > \
                      (candle["high"] - candle["low"])

        if all_bullish and strong_move and candle["close"] < candle["open"]:
            # This bearish candle is a bullish OB
            mitigated = recent.iloc[i+1:]["low"].min() < candle["low"]
            obs.append({
                "type":      "bullish",
                "top":       round(candle["high"], 2),
                "bottom":    round(candle["low"], 2),
                "index":     i,
                "mitigated": mitigated
            })

        # Look for 3 consecutive bearish candles after this point
        all_bearish = all(next_3["close"] < next_3["open"])
        strong_dn   = (next_3["open"].iloc[0] - next_3["close"].iloc[-1]) > \
                      (candle["high"] - candle["low"])

        if all_bearish and strong_dn and candle["close"] > candle["open"]:
            # This bullish candle is a bearish OB
            mitigated = recent.iloc[i+1:]["high"].max() > candle["high"]
            obs.append({
                "type":      "bearish",
                "top":       round(candle["high"], 2),
                "bottom":    round(candle["low"], 2),
                "index":     i,
                "mitigated": mitigated
            })

    return obs


def get_nearest_ob(df: pd.DataFrame, obs: list) -> dict:
    """
    Finds the nearest unmitigated OB to current price.
    Returns the OB dict plus proximity as % of price.
    """
    current_price = df["close"].iloc[-1]
    unmitigated   = [ob for ob in obs if not ob["mitigated"]]

    if not unmitigated:
        return {"found": False, "ob": None, "proximity_pct": 1.0}

    # Find closest OB by midpoint distance
    def distance(ob):
        mid = (ob["top"] + ob["bottom"]) / 2
        return abs(current_price - mid) / current_price

    nearest = min(unmitigated, key=distance)
    prox    = distance(nearest)

    return {
        "found":         True,
        "ob":            nearest,
        "proximity_pct": round(prox, 4)
    }


# =============================================================================
# FAIR VALUE GAPS
# =============================================================================

def find_fvgs(df: pd.DataFrame, lookback: int = 50) -> list:
    """
    Finds Fair Value Gaps (FVG) — also called imbalances.

    Bullish FVG: candle[i-1].high < candle[i+1].low
      (gap between previous high and next low = unfilled space)

    Bearish FVG: candle[i-1].low > candle[i+1].high
      (gap between previous low and next high = unfilled space)

    Returns list of dicts:
        {
            "type":   "bullish" | "bearish",
            "top":    float,
            "bottom": float,
            "filled": bool
        }
    """
    fvgs   = []
    recent = df.tail(lookback).reset_index(drop=True)
    n      = len(recent)

    for i in range(1, n - 1):
        prev = recent.iloc[i - 1]
        curr = recent.iloc[i]
        nxt  = recent.iloc[i + 1]

        # Bullish FVG
        if prev["high"] < nxt["low"]:
            top    = nxt["low"]
            bottom = prev["high"]
            # Check if filled by subsequent price action
            filled = recent.iloc[i+1:]["low"].min() <= bottom
            fvgs.append({
                "type":   "bullish",
                "top":    round(top, 2),
                "bottom": round(bottom, 2),
                "size":   round(top - bottom, 2),
                "filled": filled
            })

        # Bearish FVG
        if prev["low"] > nxt["high"]:
            top    = prev["low"]
            bottom = nxt["high"]
            filled = recent.iloc[i+1:]["high"].max() >= top
            fvgs.append({
                "type":   "bearish",
                "top":    round(top, 2),
                "bottom": round(bottom, 2),
                "size":   round(top - bottom, 2),
                "filled": filled
            })

    return fvgs


def get_nearest_fvg(df: pd.DataFrame, fvgs: list) -> dict:
    """
    Finds the nearest unfilled FVG to current price.
    """
    current_price = df["close"].iloc[-1]
    unfilled      = [f for f in fvgs if not f["filled"]]

    if not unfilled:
        return {"found": False, "fvg": None, "proximity_pct": 1.0}

    def distance(fvg):
        mid = (fvg["top"] + fvg["bottom"]) / 2
        return abs(current_price - mid) / current_price

    nearest = min(unfilled, key=distance)
    prox    = distance(nearest)

    return {
        "found":         True,
        "fvg":           nearest,
        "proximity_pct": round(prox, 4)
    }


# =============================================================================
# LIQUIDITY POOLS
# =============================================================================

def find_liquidity_pools(df: pd.DataFrame,
                          lookback: int = 50,
                          tolerance: float = 0.002) -> dict:
    """
    Finds clusters of equal highs and equal lows.
    These are where retail stop losses are stacked —
    institutions will hunt these before reversing.

    Equal highs above price = buy stops (bearish liquidity)
    Equal lows below price  = sell stops (bullish liquidity)

    tolerance = how close two levels need to be to count as "equal"
    (0.002 = within 0.2% of each other)

    Returns:
        {
            "buy_stops":  [levels above price],
            "sell_stops": [levels below price],
            "nearest_buy_stop":  float,
            "nearest_sell_stop": float
        }
    """
    recent        = df.tail(lookback)
    current_price = df["close"].iloc[-1]
    highs         = recent["high"].values
    lows          = recent["low"].values

    buy_stops  = []   # Equal highs above price
    sell_stops = []   # Equal lows below price

    # Find equal highs
    for i in range(len(highs)):
        for j in range(i + 1, len(highs)):
            if abs(highs[i] - highs[j]) / highs[i] <= tolerance:
                level = (highs[i] + highs[j]) / 2
                if level > current_price and level not in buy_stops:
                    buy_stops.append(round(level, 2))

    # Find equal lows
    for i in range(len(lows)):
        for j in range(i + 1, len(lows)):
            if abs(lows[i] - lows[j]) / lows[i] <= tolerance:
                level = (lows[i] + lows[j]) / 2
                if level < current_price and level not in sell_stops:
                    sell_stops.append(round(level, 2))

    nearest_buy  = min(buy_stops,  key=lambda x: abs(x - current_price)) \
                   if buy_stops  else None
    nearest_sell = min(sell_stops, key=lambda x: abs(x - current_price)) \
                   if sell_stops else None

    return {
        "buy_stops":         sorted(buy_stops),
        "sell_stops":        sorted(sell_stops, reverse=True),
        "nearest_buy_stop":  nearest_buy,
        "nearest_sell_stop": nearest_sell,
    }


def detect_liquidity_sweep(df: pd.DataFrame, pools: dict) -> dict:
    """
    Detects if price just swept a liquidity pool —
    spiked through equal highs/lows then reversed.

    This is one of the highest probability setups:
    institutions run stops, grab liquidity, then reverse.

    Returns:
        {
            "swept":     True | False,
            "direction": "bullish" | "bearish" | "none",
            "level":     float,
            "description": str
        }
    """
    if len(df) < 3:
        return {"swept": False, "direction": "none",
                "level": 0.0, "description": "Insufficient data"}

    last   = df.iloc[-1]
    prev   = df.iloc[-2]

    # Bullish sweep: wick below sell stops then closed back above
    if pools["nearest_sell_stop"]:
        level = pools["nearest_sell_stop"]
        if (prev["low"] <= level and
                last["close"] > level and
                last["close"] > last["open"]):
            return {
                "swept":       True,
                "direction":   "bullish",
                "level":       level,
                "description": f"Bullish liquidity sweep at {level:.2f}"
            }

    # Bearish sweep: wick above buy stops then closed back below
    if pools["nearest_buy_stop"]:
        level = pools["nearest_buy_stop"]
        if (prev["high"] >= level and
                last["close"] < level and
                last["close"] < last["open"]):
            return {
                "swept":       True,
                "direction":   "bearish",
                "level":       level,
                "description": f"Bearish liquidity sweep at {level:.2f}"
            }

    return {"swept": False, "direction": "none",
            "level": 0.0, "description": "No liquidity sweep"}


# =============================================================================
# MAIN SCORER
# =============================================================================

def score(data: dict) -> dict:
    """
    Main entry point — called by scoring_engine.py

    Score breakdown (max 15):
        Price at unmitigated OB:     +5
        Price at unfilled FVG:       +4
        Liquidity sweep detected:    +4
        OB + FVG confluence:         +2 bonus
    """
    candles = data.get("candles", {})
    mtf_df  = candles.get("MTF", pd.DataFrame())
    htf_df  = candles.get("HTF", pd.DataFrame())
    ltf_df  = candles.get("LTF", pd.DataFrame())

    if mtf_df.empty:
        return _empty_score("No MTF data")

    current_price = mtf_df["close"].iloc[-1]

    # --- Find zones ---
    obs           = find_order_blocks(mtf_df)
    fvgs          = find_fvgs(mtf_df)
    nearest_ob    = get_nearest_ob(mtf_df, obs)
    nearest_fvg   = get_nearest_fvg(mtf_df, fvgs)
    liq_pools     = find_liquidity_pools(mtf_df)
    liq_sweep     = detect_liquidity_sweep(ltf_df, liq_pools) \
                    if not ltf_df.empty else \
                    {"swept": False, "direction": "none"}

    # --- Build score ---
    points    = 0
    reasons   = []
    direction = "neutral"

    # OB proximity (max 5)
    if nearest_ob["found"]:
        prox = nearest_ob["proximity_pct"]
        if prox <= 0.005:       # Within 0.5% of OB
            ob_points = 5
        elif prox <= 0.01:      # Within 1%
            ob_points = 3
        elif prox <= 0.02:      # Within 2%
            ob_points = 1
        else:
            ob_points = 0

        if ob_points > 0:
            points   += ob_points
            ob        = nearest_ob["ob"]
            ob_dir    = "long" if ob["type"] == "bullish" else "short"
            direction = ob_dir
            reasons.append(
                f"Price near {ob['type']} OB "
                f"({ob['bottom']:.2f}–{ob['top']:.2f}) "
                f"— {prox*100:.2f}% away"
            )

    # FVG proximity (max 4)
    if nearest_fvg["found"]:
        prox = nearest_fvg["proximity_pct"]
        if prox <= 0.005:
            fvg_points = 4
        elif prox <= 0.01:
            fvg_points = 2
        elif prox <= 0.02:
            fvg_points = 1
        else:
            fvg_points = 0

        if fvg_points > 0:
            points  += fvg_points
            fvg      = nearest_fvg["fvg"]
            fvg_dir  = "long" if fvg["type"] == "bullish" else "short"
            if direction == "neutral":
                direction = fvg_dir
            reasons.append(
                f"Price near {fvg['type']} FVG "
                f"({fvg['bottom']:.2f}–{fvg['top']:.2f}) "
                f"— {prox*100:.2f}% away"
            )

    # Liquidity sweep (max 4)
    if liq_sweep["swept"]:
        points   += 4
        sweep_dir = "long" if liq_sweep["direction"] == "bullish" else "short"
        if direction == "neutral":
            direction = sweep_dir
        reasons.append(f"Liquidity sweep: {liq_sweep['description']}")

    # Confluence bonus (OB + FVG both nearby)
    if nearest_ob["found"] and nearest_fvg["found"]:
        if nearest_ob["proximity_pct"] <= 0.01 and \
           nearest_fvg["proximity_pct"] <= 0.01:
            points  += 2
            reasons.append("OB + FVG confluence bonus")

    points = min(15, points)

    log.debug(f"L3 score: {points}/15 | direction: {direction} | "
              f"{' | '.join(reasons)}")

    return {
        "layer":     "L3_zones",
        "score":     points,
        "max":       15,
        "direction": direction,
        "reasons":   reasons,
        "details": {
            "order_blocks":    obs,
            "fvgs":            fvgs,
            "nearest_ob":      nearest_ob,
            "nearest_fvg":     nearest_fvg,
            "liquidity_pools": liq_pools,
            "liquidity_sweep": liq_sweep,
        }
    }


def _empty_score(reason: str) -> dict:
    return {
        "layer":     "L3_zones",
        "score":     0,
        "max":       15,
        "direction": "neutral",
        "reasons":   [reason],
        "details":   {}
    }
