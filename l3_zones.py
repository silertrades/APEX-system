# =============================================================================
# APEX SYSTEM — l3_zones.py
# =============================================================================
# Layer 3: Institutional Zones
#
# Scoring audit changes:
#   - Proximity scoring widened — 3% now scores points (was 0.5%)
#   - FVG scoring more generous — awards points for approaching zones
#   - Order block detection improved — larger lookback window
#   - Liquidity pool tolerance increased — catches more equal levels
#   - Overall: should score 6-12/15 when price near key zones
#
# Score: 0-15 points
# =============================================================================

import numpy as np
import pandas as pd
import logging

log = logging.getLogger("l3_zones")


# =============================================================================
# ORDER BLOCKS
# =============================================================================

def find_order_blocks(df: pd.DataFrame, lookback: int = 75) -> list:
    """
    Finds Order Blocks — last opposing candle before a strong impulse.
    Increased lookback from 50 to 75 for more zone discovery.
    """
    obs    = []
    recent = df.tail(lookback).reset_index(drop=True)
    n      = len(recent)

    for i in range(2, n - 3):
        candle = recent.iloc[i]
        next_3 = recent.iloc[i+1:i+4]

        all_bullish  = all(next_3["close"] > next_3["open"])
        strong_move  = (next_3["close"].iloc[-1] - next_3["open"].iloc[0]) > \
                       (candle["high"] - candle["low"])

        if all_bullish and strong_move and candle["close"] < candle["open"]:
            mitigated = recent.iloc[i+1:]["low"].min() < candle["low"]
            obs.append({
                "type":      "bullish",
                "top":       round(candle["high"], 4),
                "bottom":    round(candle["low"],  4),
                "index":     i,
                "mitigated": mitigated
            })

        all_bearish = all(next_3["close"] < next_3["open"])
        strong_dn   = (next_3["open"].iloc[0] - next_3["close"].iloc[-1]) > \
                      (candle["high"] - candle["low"])

        if all_bearish and strong_dn and candle["close"] > candle["open"]:
            mitigated = recent.iloc[i+1:]["high"].max() > candle["high"]
            obs.append({
                "type":      "bearish",
                "top":       round(candle["high"], 4),
                "bottom":    round(candle["low"],  4),
                "index":     i,
                "mitigated": mitigated
            })

    return obs


def get_nearest_ob(df: pd.DataFrame, obs: list) -> dict:
    """Finds nearest unmitigated OB to current price."""
    current_price = df["close"].iloc[-1]
    unmitigated   = [ob for ob in obs if not ob["mitigated"]]

    if not unmitigated:
        return {"found": False, "ob": None, "proximity_pct": 1.0}

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

def find_fvgs(df: pd.DataFrame, lookback: int = 75) -> list:
    """
    Finds Fair Value Gaps.
    Increased lookback from 50 to 75.
    """
    fvgs   = []
    recent = df.tail(lookback).reset_index(drop=True)
    n      = len(recent)

    for i in range(1, n - 1):
        prev = recent.iloc[i - 1]
        nxt  = recent.iloc[i + 1]

        # Bullish FVG
        if prev["high"] < nxt["low"]:
            top    = nxt["low"]
            bottom = prev["high"]
            filled = recent.iloc[i+1:]["low"].min() <= bottom
            size   = top - bottom
            # Only include meaningful FVGs (at least 0.05% of price)
            if size / (prev["close"] + 1e-9) >= 0.0005:
                fvgs.append({
                    "type":   "bullish",
                    "top":    round(top,    4),
                    "bottom": round(bottom, 4),
                    "size":   round(size,   4),
                    "filled": filled
                })

        # Bearish FVG
        if prev["low"] > nxt["high"]:
            top    = prev["low"]
            bottom = nxt["high"]
            filled = recent.iloc[i+1:]["high"].max() >= top
            size   = top - bottom
            if size / (prev["close"] + 1e-9) >= 0.0005:
                fvgs.append({
                    "type":   "bearish",
                    "top":    round(top,    4),
                    "bottom": round(bottom, 4),
                    "size":   round(size,   4),
                    "filled": filled
                })

    return fvgs


def get_nearest_fvg(df: pd.DataFrame, fvgs: list) -> dict:
    """Finds nearest unfilled FVG to current price."""
    current_price = df["close"].iloc[-1]
    unfilled      = [f for f in fvgs if not f["filled"]]

    if not unfilled:
        return {"found": False, "fvg": None, "proximity_pct": 1.0}

    def distance(fvg):
        mid = (fvg["top"] + fvg["bottom"]) / 2
        return abs(current_price - mid) / current_price

    nearest = min(unfilled, key=distance)
    prox    = distance(nearest)

    # Also check if price is INSIDE the FVG
    inside = nearest["bottom"] <= current_price <= nearest["top"]

    return {
        "found":         True,
        "fvg":           nearest,
        "proximity_pct": round(prox, 4),
        "inside":        inside,
    }


# =============================================================================
# LIQUIDITY POOLS
# =============================================================================

def find_liquidity_pools(df: pd.DataFrame,
                          lookback: int = 75,
                          tolerance: float = 0.003) -> dict:
    """
    Finds equal highs and equal lows (stop loss clusters).
    Tolerance increased from 0.002 to 0.003 — catches more levels.
    """
    recent        = df.tail(lookback)
    current_price = df["close"].iloc[-1]
    highs         = recent["high"].values
    lows          = recent["low"].values

    buy_stops  = []
    sell_stops = []

    for i in range(len(highs)):
        for j in range(i + 1, len(highs)):
            if abs(highs[i] - highs[j]) / (highs[i] + 1e-9) <= tolerance:
                level = (highs[i] + highs[j]) / 2
                if level > current_price and level not in buy_stops:
                    buy_stops.append(round(level, 4))

    for i in range(len(lows)):
        for j in range(i + 1, len(lows)):
            if abs(lows[i] - lows[j]) / (lows[i] + 1e-9) <= tolerance:
                level = (lows[i] + lows[j]) / 2
                if level < current_price and level not in sell_stops:
                    sell_stops.append(round(level, 4))

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
    """Detects if price just swept a liquidity pool."""
    if len(df) < 3:
        return {"swept": False, "direction": "none",
                "level": 0.0, "description": "Insufficient data"}

    last = df.iloc[-1]
    prev = df.iloc[-2]

    if pools["nearest_sell_stop"]:
        level = pools["nearest_sell_stop"]
        if (prev["low"] <= level and
                last["close"] > level and
                last["close"] > last["open"]):
            return {
                "swept":       True,
                "direction":   "bullish",
                "level":       level,
                "description": f"Bullish liquidity sweep at {level:.4f}"
            }

    if pools["nearest_buy_stop"]:
        level = pools["nearest_buy_stop"]
        if (prev["high"] >= level and
                last["close"] < level and
                last["close"] < last["open"]):
            return {
                "swept":       True,
                "direction":   "bearish",
                "level":       level,
                "description": f"Bearish liquidity sweep at {level:.4f}"
            }

    return {"swept": False, "direction": "none",
            "level": 0.0, "description": "No liquidity sweep"}


# =============================================================================
# MAIN SCORER — widened proximity scoring
# =============================================================================

def score(data: dict) -> dict:
    """
    Score breakdown (max 15):
        OB proximity:         0-5  (within 3% scores, within 0.5% = full)
        FVG proximity:        0-4  (within 3% scores, inside = full)
        Liquidity sweep:      0-4
        OB + FVG confluence:  +2 bonus

    Proximity tiers (widened from original):
        Within 0.5%:  full points
        Within 1.0%:  75% points
        Within 2.0%:  50% points
        Within 3.0%:  25% points
        Beyond 3.0%:  0 points
    """
    candles = data.get("candles", {})
    mtf_df  = candles.get("MTF", pd.DataFrame())
    htf_df  = candles.get("HTF", pd.DataFrame())
    ltf_df  = candles.get("LTF", pd.DataFrame())

    if mtf_df.empty:
        return _empty_score("No MTF data")

    # Find zones on MTF
    obs        = find_order_blocks(mtf_df)
    fvgs       = find_fvgs(mtf_df)
    nearest_ob = get_nearest_ob(mtf_df, obs)
    nearest_fvg = get_nearest_fvg(mtf_df, fvgs)

    # Also check HTF zones for extra confluence
    htf_obs  = find_order_blocks(htf_df) if not htf_df.empty else []
    htf_fvgs = find_fvgs(htf_df)         if not htf_df.empty else []
    htf_ob   = get_nearest_ob(htf_df, htf_obs)   if not htf_df.empty else \
               {"found": False}
    htf_fvg  = get_nearest_fvg(htf_df, htf_fvgs) if not htf_df.empty else \
               {"found": False}

    liq_pools = find_liquidity_pools(mtf_df)
    liq_sweep = detect_liquidity_sweep(ltf_df, liq_pools) \
                if not ltf_df.empty else \
                {"swept": False, "direction": "none"}

    points    = 0
    reasons   = []
    direction = "neutral"

    def proximity_points(prox: float, max_pts: int) -> int:
        """Convert proximity % to points using graduated tiers."""
        if prox <= 0.005:   return max_pts          # Within 0.5%
        elif prox <= 0.01:  return int(max_pts * 0.75)  # Within 1%
        elif prox <= 0.02:  return int(max_pts * 0.50)  # Within 2%
        elif prox <= 0.03:  return int(max_pts * 0.25)  # Within 3%
        else:               return 0

    # OB proximity (max 5)
    if nearest_ob["found"]:
        prox     = nearest_ob["proximity_pct"]
        ob_pts   = proximity_points(prox, 5)

        # Bonus if inside the OB
        ob       = nearest_ob["ob"]
        current  = mtf_df["close"].iloc[-1]
        if ob["bottom"] <= current <= ob["top"]:
            ob_pts = 5

        if ob_pts > 0:
            points   += ob_pts
            ob_dir    = "long" if ob["type"] == "bullish" else "short"
            direction = ob_dir
            reasons.append(
                f"Price near {ob['type']} OB "
                f"({ob['bottom']:.2f}–{ob['top']:.2f}) "
                f"— {prox*100:.2f}% away"
            )

    # FVG proximity (max 4)
    if nearest_fvg["found"]:
        prox    = nearest_fvg["proximity_pct"]
        fvg_pts = proximity_points(prox, 4)

        # Full points if inside FVG
        if nearest_fvg.get("inside"):
            fvg_pts = 4

        if fvg_pts > 0:
            points  += fvg_pts
            fvg      = nearest_fvg["fvg"]
            fvg_dir  = "long" if fvg["type"] == "bullish" else "short"
            if direction == "neutral":
                direction = fvg_dir
            reasons.append(
                f"Price near {fvg['type']} FVG "
                f"({fvg['bottom']:.2f}–{fvg['top']:.2f}) "
                f"— {prox*100:.2f}% away"
            )

    # HTF zone bonus — extra point if HTF also has nearby zone
    if htf_ob["found"] and htf_ob["proximity_pct"] <= 0.03:
        points += 1
        reasons.append(f"HTF OB confluence")
    elif htf_fvg["found"] and htf_fvg["proximity_pct"] <= 0.03:
        points += 1
        reasons.append(f"HTF FVG confluence")

    # Liquidity sweep (max 4)
    if liq_sweep["swept"]:
        points   += 4
        sweep_dir = "long" if liq_sweep["direction"] == "bullish" else "short"
        if direction == "neutral":
            direction = sweep_dir
        reasons.append(f"Liquidity sweep: {liq_sweep['description']}")

    # OB + FVG confluence bonus
    if nearest_ob["found"] and nearest_fvg["found"]:
        if (nearest_ob["proximity_pct"]  <= 0.02 and
                nearest_fvg["proximity_pct"] <= 0.02):
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
