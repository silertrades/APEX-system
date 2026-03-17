# =============================================================================
# APEX SYSTEM — scoring_engine.py
# =============================================================================
# The brain of the system.
#
# Changes from audit:
#   - Long signals only (backtest shows 53.6% vs 47.7% for shorts)
#   - Mean-reversion regime requires score >= 75 (vs 65 for trend)
#   - BTC requires score >= 75 (underperforms at lower scores)
#   - These thresholds are data-driven from backtest results
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
# SYMBOL-SPECIFIC THRESHOLDS
# =============================================================================
# Based on backtest results — symbols that underperform require higher scores

SYMBOL_THRESHOLDS = {
    "BTCUSDT": 75,    # Underperforms at lower scores
    "ETHUSDT": 65,
    "SOLUSDT": 65,
    "BNBUSDT": 65,
    "AVAXUSDT": 65,
    "XRPUSDT": 65,
}

# Regime-specific thresholds
REGIME_THRESHOLDS = {
    "trend":          65,   # Standard threshold
    "mean_reversion": 75,   # Higher bar — less reliable
    "breakout":       65,
    "avoid":          999,  # Never fire in crisis
}


# =============================================================================
# ATR CALCULATION
# =============================================================================

def calc_atr(df: pd.DataFrame, period: int = ATR_PERIOD) -> float:
    if len(df) < period + 1:
        return df["close"].iloc[-1] * 0.01

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
    long_weight  = 0.0
    short_weight = 0.0
    total_weight = 0.0

    for result in layer_results:
        layer_name = result["layer"]
        direction  = result["direction"]
        score      = result["score"]
        max_score  = result["max"]
        weight     = LAYER_WEIGHTS.get(layer_name, 10)
        score_pct  = score / max_score if max_score > 0 else 0

        if direction == "long":
            long_weight  += weight * score_pct
        elif direction == "short":
            short_weight += weight * score_pct

        total_weight += weight * score_pct

    if total_weight == 0:
        return {
            "direction":    "neutral",
            "confidence":   0.0,
            "long_weight":  0.0,
            "short_weight": 0.0,
            "description":  "No weighted votes"
        }

    long_pct  = long_weight  / total_weight
    short_pct = short_weight / total_weight

    if long_pct >= 0.6:
        return {
            "direction":    "long",
            "confidence":   round(long_pct, 3),
            "long_weight":  round(long_weight, 1),
            "short_weight": round(short_weight, 1),
            "description":  f"Long consensus ({long_pct*100:.0f}% weighted vote)"
        }

    if short_pct >= 0.6:
        return {
            "direction":    "short",
            "confidence":   round(short_pct, 3),
            "long_weight":  round(long_weight, 1),
            "short_weight": round(short_weight, 1),
            "description":  f"Short consensus ({short_pct*100:.0f}% weighted vote)"
        }

    return {
        "direction":    "neutral",
        "confidence":   0.0,
        "long_weight":  round(long_weight, 1),
        "short_weight": round(short_weight, 1),
        "description":  f"Mixed — long {long_pct*100:.0f}% vs short {short_pct*100:.0f}%"
    }


# =============================================================================
# TRADE LEVELS
# =============================================================================

def calculate_trade_levels(data: dict, direction: str) -> dict:
    candles = data.get("candles", {})
    ltf_df  = candles.get("LTF", pd.DataFrame())
    mtf_df  = candles.get("MTF", pd.DataFrame())

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
    score_factor = (score - SCORE_THRESHOLD_STANDARD) / \
                   (100 - SCORE_THRESHOLD_STANDARD)
    score_factor = max(0.0, min(1.0, score_factor))

    size_pct = MAX_POSITION_PCT * KELLY_FRACTION * (1 + score_factor)
    size_pct = min(MAX_POSITION_PCT, size_pct)

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
    for result in layer_results:
        if result["layer"] == "L4_macro":
            details = result.get("details", {})
            overall = details.get("overall", {})
            mode    = overall.get("mode", "trend")
            if mode in ["trend", "mean_reversion", "breakout", "avoid"]:
                return mode
    return "trend"


# =============================================================================
# EFFECTIVE THRESHOLD
# =============================================================================

def get_effective_threshold(symbol: str, regime: str) -> float:
    """
    Returns the effective score threshold for a symbol + regime combo.
    Takes the HIGHER of the symbol threshold and regime threshold.

    Examples:
        BTCUSDT + trend:          max(75, 65) = 75
        BTCUSDT + mean_reversion: max(75, 75) = 75
        ETHUSDT + trend:          max(65, 65) = 65
        ETHUSDT + mean_reversion: max(65, 75) = 75
    """
    symbol_threshold = SYMBOL_THRESHOLDS.get(symbol, SCORE_THRESHOLD_STANDARD)
    regime_threshold = REGIME_THRESHOLDS.get(regime, SCORE_THRESHOLD_STANDARD)
    return max(symbol_threshold, regime_threshold)


# =============================================================================
# MAIN SCORER
# =============================================================================

def run(data: dict) -> dict:
    """
    Main entry point. Runs all 6 layers and returns
    a complete signal dict, or None if no signal.

    Key filters applied:
    1. Long signals only
    2. Symbol-specific thresholds
    3. Regime-specific thresholds
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
    total_score = 0.0
    for result in layer_results:
        layer_name = result["layer"]
        raw_score  = result["score"]
        max_score  = result["max"]
        weight     = LAYER_WEIGHTS.get(layer_name, 10)
        normalized = (raw_score / max_score * 100) if max_score > 0 else 0
        weighted   = normalized * (weight / 100)
        total_score += weighted

    total_score = round(min(100.0, total_score), 1)

    # --- Direction consensus ---
    consensus = get_direction_consensus(layer_results)
    direction = consensus["direction"]

    # --- Regime ---
    regime = get_trade_regime(layer_results)

    # --- Log layer breakdown ---
    log.info(f"{symbol} | Total score: {total_score}/100 | "
             f"Direction: {direction}")
    for result in layer_results:
        log.info(f"  {result['layer']}: {result['score']}/{result['max']} "
                 f"({result['direction']}) — "
                 f"{' | '.join(result['reasons'][:2])}")

    # --- Filter 1: Long signals only ---
    if direction != "long":
        log.info(f"{symbol} | Direction {direction} filtered "
                 f"— long signals only")
        return None

    # --- Filter 2: Get effective threshold ---
    threshold = get_effective_threshold(symbol, regime)

    if total_score < threshold:
        log.info(f"{symbol} | Score {total_score} below threshold "
                 f"{threshold} (symbol:{SYMBOL_THRESHOLDS.get(symbol,65)} "
                 f"regime:{REGIME_THRESHOLDS.get(regime,65)}) — no signal")
        return None

    # --- Calculate levels and sizing ---
    levels = calculate_trade_levels(data, direction)
    if not levels:
        log.warning(f"{symbol} | Could not calculate trade levels")
        return None

    sizing = calculate_position_size(total_score, levels["r_pct"])
    tier   = classify_signal(total_score)

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
             f"LONG | Regime: {regime} | Threshold was: {threshold}")

    return signal
