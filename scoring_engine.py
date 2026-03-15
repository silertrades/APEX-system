# =============================================================================
# APEX SYSTEM — scoring_engine.py
# =============================================================================
# The brain of the system.
#
# What this does:
#   - Runs all 6 layers for a given symbol
#   - Weights and combines scores into a single 0-100 score
#   - Determines overall trade direction by consensus
#   - Classifies the regime (trend / mean_reversion / breakout)
#   - Calculates entry, stop loss, and take profit levels
#   - Returns a complete trade signal ready for the alert manager
#
# A signal only fires when score >= SCORE_THRESHOLD_STANDARD (65)
# AND at least 4 of 6 layers agree on direction
# =============================================================================

import numpy as np
import pandas as pd
import logging

from config import (
    LAYER_WEIGHTS,
    SCORE_THRESHOLD_STANDARD,
    SCORE_THRESHOLD_HIGH_CONVICTION,
    SCORE_THRESHOLD_MAX_SIZE,
    ATR_STOP_MULTIPLIER,
    ATR_PERIOD,
    TP1_R, TP2_R, TP3_R,
    MAX_POSITION_PCT,
    KELLY_FRACTION,
)

import l1_structure
import l2_order_flow
import l3_zones
import l4_macro
import l5_momentum
import l6_sentiment

log = logging.getLogger("scoring_engine")


# =============================================================================
# ATR CALCULATION
# =============================================================================

def calc_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> float:
    """Returns the current ATR value for stop loss sizing."""
    if len(df) < period + 1:
        return df["close"].iloc[-1] * 0.01  # Default 1% of price

    high  = df["high"]
    low   = df["low"]
    close = df["close"]

    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)

    return tr.ewm(com=period - 1, adjust=False).mean().iloc[-1]


# =============================================================================
# DIRECTION CONSENSUS
# =============================================================================

def get_direction_consensus(layer_results: list) -> dict:
    """
    Determines overall trade direction by weighted vote
    across all layers.

    Returns:
        {
            "direction":   "long" | "short" | "neutral",
            "confidence":  float (0.0–1.0),
            "long_votes":  int,
            "short_votes": int,
            "description": str
        }
    """
    long_weight  = 0.0
    short_weight = 0.0
    total_weight = 0.0

    for result in layer_results:
        layer_name = result["layer"]
        direction  = result["direction"]
        score      = result["score"]
        max_score  = result["max"]
        weight     = LAYER_WEIGHTS.get(layer_name, 10)

        # Weight each vote by score percentage × layer weight
        score_pct = score / max_score if max_score > 0 else 0

        if direction == "long":
            long_weight  += weight * score_pct
        elif direction == "short":
            short_weight += weight * score_pct

        total_weight += weight * score_pct

    if total_weight == 0:
        return {
            "direction":   "neutral",
            "confidence":  0.0,
            "long_weight": 0.0,
            "short_weight": 0.0,
            "description": "No weighted votes"
        }

    long_pct  = long_weight  / total_weight
    short_pct = short_weight / total_weight

    if long_pct >= 0.6:
        return {
            "direction":   "long",
            "confidence":  round(long_pct, 3),
            "long_weight": round(long_weight, 1),
            "short_weight": round(short_weight, 1),
            "description": f"Long consensus ({long_pct*100:.0f}% weighted vote)"
        }

    if short_pct >= 0.6:
        return {
            "direction":   "short",
            "confidence":  round(short_pct, 3),
            "long_weight": round(long_weight, 1),
            "short_weight": round(short_weight, 1),
            "description": f"Short consensus ({short_pct*100:.0f}% weighted vote)"
        }

    return {
        "direction":   "neutral",
        "confidence":  0.0,
        "long_weight": round(long_weight, 1),
        "short_weight": round(short_weight, 1),
        "description": f"Mixed signals — long {long_pct*100:.0f}% "
                       f"vs short {short_pct*100:.0f}%"
    }


# =============================================================================
# TRADE LEVELS
# =============================================================================

def calculate_trade_levels(data: dict, direction: str) -> dict:
    """
    Calculates precise entry, stop loss, and take profit levels.

    Entry:  Current price (market order on signal)
    Stop:   ATR-based stop loss
    TP1-3:  R-multiple targets

    Returns:
        {
            "entry":  float,
            "stop":   float,
            "tp1":    float,
            "tp2":    float,
            "tp3":    float,
            "r":      float,  (stop distance in points)
            "r_pct":  float,  (stop distance as % of price)
        }
    """
    candles = data.get("candles", {})
    ltf_df  = candles.get("LTF", pd.DataFrame())
    mtf_df  = candles.get("MTF", pd.DataFrame())

    # Use LTF for entry, MTF for ATR
    df_for_entry = ltf_df if not ltf_df.empty else mtf_df
    df_for_atr   = mtf_df if not mtf_df.empty else ltf_df

    if df_for_entry.empty:
        return {}

    entry = df_for_entry["close"].iloc[-1]
    atr   = calc_atr(df_for_atr)
    r     = atr * ATR_STOP_MULTIPLIER

    if direction == "long":
        stop = entry - r
        tp1  = entry + r * TP1_R
        tp2  = entry + r * TP2_R
        tp3  = entry + r * TP3_R
    else:
        stop = entry + r
        tp1  = entry - r * TP1_R
        tp2  = entry - r * TP2_R
        tp3  = entry - r * TP3_R

    return {
        "entry":  round(entry, 2),
        "stop":   round(stop,  2),
        "tp1":    round(tp1,   2),
        "tp2":    round(tp2,   2),
        "tp3":    round(tp3,   2),
        "r":      round(r,     2),
        "r_pct":  round(r / entry * 100, 3),
    }


# =============================================================================
# POSITION SIZING
# =============================================================================

def calculate_position_size(score: float,
                             r_pct: float,
                             account_size: float = 10000) -> dict:
    """
    Calculates recommended position size using a Kelly-fraction approach.

    Higher score = larger position (up to MAX_POSITION_PCT cap).
    Lower score  = smaller position.

    Returns:
        {
            "size_pct":    float (% of account to risk),
            "size_usd":    float (dollar amount to risk),
            "description": str
        }
    """
    # Scale size with score
    score_factor = (score - SCORE_THRESHOLD_STANDARD) / \
                   (100 - SCORE_THRESHOLD_STANDARD)
    score_factor = max(0.0, min(1.0, score_factor))

    # Kelly fraction scaled by score
    size_pct = MAX_POSITION_PCT * KELLY_FRACTION * (1 + score_factor)
    size_pct = min(MAX_POSITION_PCT, size_pct)

    # Extra size for high conviction
    if score >= SCORE_THRESHOLD_MAX_SIZE:
        size_pct = MAX_POSITION_PCT
    elif score >= SCORE_THRESHOLD_HIGH_CONVICTION:
        size_pct = MAX_POSITION_PCT * 0.75

    size_usd = account_size * size_pct

    return {
        "size_pct":    round(size_pct * 100, 2),
        "size_usd":    round(size_usd, 2),
        "description": f"Risk {size_pct*100:.1f}% of account "
                       f"(${size_usd:.0f} on $10k)"
    }


# =============================================================================
# SIGNAL CLASSIFICATION
# =============================================================================

def classify_signal(score: float) -> dict:
    """
    Classifies signal strength based on score.

    Returns:
        {
            "tier":        "standard" | "high_conviction" | "max_size",
            "emoji":       str,
            "description": str
        }
    """
    if score >= SCORE_THRESHOLD_MAX_SIZE:
        return {
            "tier":        "max_size",
            "emoji":       "🔥",
            "description": "MAX SIZE — rare, career-defining setup"
        }
    elif score >= SCORE_THRESHOLD_HIGH_CONVICTION:
        return {
            "tier":        "high_conviction",
            "emoji":       "⚡",
            "description": "HIGH CONVICTION — 1.5x normal size"
        }
    else:
        return {
            "tier":        "standard",
            "emoji":       "✅",
            "description": "STANDARD — normal position size"
        }


# =============================================================================
# REGIME CLASSIFIER
# =============================================================================

def get_trade_regime(layer_results: list) -> str:
    """
    Determines the trading regime based on layer signals.
    This affects exit strategy.

    trend:          Trail stops, let winners run to TP3
    mean_reversion: Take profits quickly, TP1 and TP2 only
    breakout:       Enter on close, wider stops, TP3 target

    Returns: "trend" | "mean_reversion" | "breakout"
    """
    # Extract L4 regime details
    for result in layer_results:
        if result["layer"] == "L4_macro":
            details = result.get("details", {})
            overall = details.get("overall", {})
            mode    = overall.get("mode", "trend")
            if mode in ["trend", "mean_reversion", "breakout"]:
                return mode

    return "trend"  # Default


# =============================================================================
# MAIN SCORER
# =============================================================================

def run(data: dict) -> dict:
    """
    Main entry point. Runs all 6 layers and returns
    a complete signal dict.

    Returns None if score is below threshold or
    direction is unclear.

    Returns:
        {
            "symbol":       str,
            "score":        float (0–100),
            "direction":    "long" | "short",
            "tier":         "standard" | "high_conviction" | "max_size",
            "regime":       "trend" | "mean_reversion" | "breakout",
            "levels":       dict (entry, stop, tp1, tp2, tp3),
            "sizing":       dict,
            "consensus":    dict,
            "layer_scores": list,
            "timestamp":    str,
        }
    """
    symbol = data.get("symbol", "UNKNOWN")
    log.info(f"Running scoring engine for {symbol}...")

    # --- Run all 6 layers ---
    layer_results = []

    try:
        layer_results.append(l1_structure.score(data))
    except Exception as e:
        log.error(f"L1 failed: {e}")
        layer_results.append(l1_structure._empty_score(str(e)))

    try:
        layer_results.append(l2_order_flow.score(data))
    except Exception as e:
        log.error(f"L2 failed: {e}")
        layer_results.append(l2_order_flow._empty_score(str(e)))

    try:
        layer_results.append(l3_zones.score(data))
    except Exception as e:
        log.error(f"L3 failed: {e}")
        layer_results.append(l3_zones._empty_score(str(e)))

    try:
        layer_results.append(l4_macro.score(data))
    except Exception as e:
        log.error(f"L4 failed: {e}")
        layer_results.append(l4_macro._empty_score(str(e)))

    try:
        layer_results.append(l5_momentum.score(data))
    except Exception as e:
        log.error(f"L5 failed: {e}")
        layer_results.append(l5_momentum._empty_score(str(e)))

    try:
        layer_results.append(l6_sentiment.score(data))
    except Exception as e:
        log.error(f"L6 failed: {e}")
        layer_results.append(l6_sentiment._empty_score(str(e)))

    # --- Calculate weighted total score ---
    total_score    = 0.0
    total_possible = 0.0

    for result in layer_results:
        layer_name  = result["layer"]
        raw_score   = result["score"]
        max_score   = result["max"]
        weight      = LAYER_WEIGHTS.get(layer_name, 10)

        # Normalize to 0-100 per layer then weight
        normalized  = (raw_score / max_score * 100) if max_score > 0 else 0
        weighted    = normalized * (weight / 100)
        total_score += weighted

    total_score = round(min(100.0, total_score), 1)

    # --- Direction consensus ---
    consensus = get_direction_consensus(layer_results)
    direction = consensus["direction"]

    # --- Log layer breakdown ---
    log.info(f"{symbol} | Total score: {total_score}/100 | "
             f"Direction: {direction}")
    for result in layer_results:
        log.info(f"  {result['layer']}: {result['score']}/{result['max']} "
                 f"({result['direction']}) — "
                 f"{' | '.join(result['reasons'][:2])}")

    # --- Check if signal should fire ---
    if total_score < SCORE_THRESHOLD_STANDARD:
        log.info(f"{symbol} | Score {total_score} below threshold "
                 f"{SCORE_THRESHOLD_STANDARD} — no signal")
        return None

    if direction == "neutral":
        log.info(f"{symbol} | No direction consensus — no signal")
        return None

    # --- Calculate levels and sizing ---
    levels  = calculate_trade_levels(data, direction)
    if not levels:
        log.warning(f"{symbol} | Could not calculate trade levels")
        return None

    sizing  = calculate_position_size(total_score, levels["r_pct"])
    tier    = classify_signal(total_score)
    regime  = get_trade_regime(layer_results)

    signal = {
        "symbol":       symbol,
        "score":        total_score,
        "direction":    direction,
        "tier":         tier["tier"],
        "emoji":        tier["emoji"],
        "tier_desc":    tier["description"],
        "regime":       regime,
        "levels":       levels,
        "sizing":       sizing,
        "consensus":    consensus,
        "layer_scores": layer_results,
        "timestamp":    str(pd.Timestamp.now()),
    }

    log.info(f"{symbol} | SIGNAL FIRED | Score: {total_score} | "
             f"{direction.upper()} | Regime: {regime}")

    return signal
