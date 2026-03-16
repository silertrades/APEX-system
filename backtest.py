# =============================================================================
# APEX SYSTEM — backtest.py
# =============================================================================
# Walks through 2 years of historical data candle by candle,
# runs all 6 scoring layers at each point, logs signals,
# and checks forward to see if TP or SL was hit.
#
# HOW TO RUN:
#   python backtest.py
#
# OUTPUT:
#   backtest_results.csv  — every signal with full outcome
#   backtest_report.txt   — summary stats and performance breakdown
#
# This runs locally or on Railway. Takes 5-15 minutes to complete.
# =============================================================================

import os
import csv
import time
import logging
import numpy as np
import pandas as pd
import requests
from datetime import datetime, timedelta

# Import scoring layers
import l1_structure
import l2_order_flow
import l3_zones
import l4_macro
import l5_momentum
import l6_sentiment
from scoring_engine import (
    get_direction_consensus,
    calculate_trade_levels,
    get_trade_regime,
    calc_atr,
)
from config import (
    CRYPTO_SYMBOLS,
    TIMEFRAMES,
    LAYER_WEIGHTS,
    SCORE_THRESHOLD_STANDARD,
    ATR_STOP_MULTIPLIER,
    ATR_PERIOD,
    TP1_R, TP2_R, TP3_R,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("backtest")

# =============================================================================
# SETTINGS
# =============================================================================

BACKTEST_DAYS     = 365        # 1 year
WARMUP_CANDLES    = 250        # Candles needed before scoring starts
BACKTEST_SCORE_THRESHOLD = 25  # Lower than live — accounts for no live CVD
STEP_CANDLES      = 4          # Check every 4 candles on 4H (= every 16hrs)
                               # Balances thoroughness vs speed
FORWARD_CANDLES   = 100        # How many candles forward to check for outcome
RESULTS_CSV       = "backtest_results.csv"
REPORT_TXT        = "backtest_report.txt"

BINANCE_REST      = "https://api.binance.com"

# Timeframe to step through (MTF = 4H is the primary signal timeframe)
STEP_TIMEFRAME    = "4H"
STEP_INTERVAL     = "4h"

# All timeframes needed for scoring
TF_INTERVALS = {
    "HTF": "1d",
    "MTF": "4h",
    "ITF": "1h",
    "LTF": "15m",
}


# =============================================================================
# DATA FETCHING
# =============================================================================

def fetch_historical(symbol: str, interval: str, days: int) -> pd.DataFrame:
    """
    Fetches full historical OHLCV data from Binance.
    Handles pagination and rate limiting with retries.
    """
    log.info(f"Fetching {symbol} {interval} — {days} days...")

    all_candles = []
    end_time    = int(datetime.now().timestamp() * 1000)
    start_time  = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)

    while start_time < end_time:
        try:
            resp = requests.get(
                f"{BINANCE_REST}/api/v3/klines",
                params={
                    "symbol":    symbol,
                    "interval":  interval,
                    "startTime": start_time,
                    "limit":     1000,
                },
                timeout=15
            )
            resp.raise_for_status()
            candles = resp.json()

            if not candles:
                break

            all_candles.extend(candles)
            start_time = candles[-1][0] + 1
            time.sleep(0.5)

        except Exception as e:
            log.error(f"Fetch error {symbol} {interval}: {e}")
            time.sleep(5)
            continue

    if not all_candles:
        return pd.DataFrame()

    df = pd.DataFrame(all_candles, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore"
    ])

    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    df.dropna(inplace=True)

    log.info(f"  {symbol} {interval}: {len(df)} candles loaded.")
    return df


def get_slice(df: pd.DataFrame, end_idx: int, n: int) -> pd.DataFrame:
    """Returns a slice of dataframe ending at end_idx with n candles."""
    start = max(0, end_idx - n)
    return df.iloc[start:end_idx].copy()


def build_candles_at_point(
    all_data: dict,
    symbol: str,
    mtf_idx: int,
    mtf_df: pd.DataFrame
) -> dict:
    """
    Builds the candles dict as the bot would see it at a given point in time.
    Uses the MTF index to align all other timeframes to the same moment.
    """
    # Get the timestamp at this MTF candle
    current_time = mtf_df.index[mtf_idx]

    candles = {}

    for tf_name, tf_df in all_data[symbol].items():
        # Get all candles up to and including current_time
        available = tf_df[tf_df.index <= current_time]
        if len(available) >= 50:
            candles[tf_name] = available.tail(500).copy()

    return candles


# =============================================================================
# SCORING AT A POINT IN TIME
# =============================================================================
def layer_lookup_score(layer_results: list, layer_name: str) -> int:
    """Helper to get a specific layer score from results list."""
    for r in layer_results:
        if r["layer"] == layer_name:
            return r["score"]
    return 0
    
def score_at_point(candles: dict, symbol: str) -> dict:
    """
    Runs all 6 layers at a specific point in time.
    Returns the same structure as the live scoring engine.
    """
    # Build a minimal data dict (no live order flow in backtest)
    data = {
        "symbol":         symbol,
        "candles":        candles,
        "cvd_divergence": {"divergence": "none", "strength": 0.0,
                           "description": "Backtest — no live CVD"},
        "macro": {
            "vix":               20.0,   # Neutral — no live macro in backtest
            "dxy_momentum":      0.0,
            "yield_curve_slope": 1.0,
        },
        "sentiment": {
            "funding_rate": 0.0,
            "oi":           {"oi": 0.0, "oi_change_pct": 0.0},
        },
        "timestamp": str(pd.Timestamp.now()),
    }

    # Run all layers
    layer_results = []
    for layer_fn in [
        l1_structure, l2_order_flow, l3_zones,
        l4_macro, l5_momentum, l6_sentiment
    ]:
        try:
            result = layer_fn.score(data)
            layer_results.append(result)
        except Exception as e:
            log.debug(f"Layer error: {e}")

    if not layer_results:
        return None

    # Calculate weighted score
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
    consensus   = get_direction_consensus(layer_results)
    direction   = consensus["direction"]

    # Always log scores above 20 so we can see what's being generated
    if total_score >= 20 and direction != "neutral":
        log.info(f"Score: {symbol} {total_score}/100 {direction} "
                 f"L1:{layer_lookup_score(layer_results,'L1_structure')} "
                 f"L3:{layer_lookup_score(layer_results,'L3_zones')} "
                 f"L4:{layer_lookup_score(layer_results,'L4_macro')} "
                 f"L5:{layer_lookup_score(layer_results,'L5_momentum')}")

    if total_score < BACKTEST_SCORE_THRESHOLD or direction == "neutral":
        return None

    # Calculate trade levels
    levels = calculate_trade_levels(data, direction)
    if not levels:
        return None

    regime = get_trade_regime(layer_results)

    return {
        "symbol":       symbol,
        "score":        total_score,
        "direction":    direction,
        "regime":       regime,
        "levels":       levels,
        "layer_scores": layer_results,
        "consensus":    consensus,
    }


# =============================================================================
# OUTCOME CHECKING
# =============================================================================

def check_outcome(
    direction: str,
    entry: float,
    stop: float,
    tp1: float,
    tp2: float,
    tp3: float,
    forward_df: pd.DataFrame
) -> dict:
    """
    Walks forward through candles to find outcome.
    Checks each candle's high and low to see if TP or SL was touched.

    Returns the full journey:
    {
        "outcome":      str,   e.g. "TP2_THEN_SL"
        "tp1_hit":      bool,
        "tp2_hit":      bool,
        "tp3_hit":      bool,
        "sl_hit":       bool,
        "tp1_candle":   int,   candles until TP1 hit
        "max_r":        float, maximum R achieved
        "final_r":      float, R at final outcome
    }
    """
    tp1_hit   = False
    tp2_hit   = False
    tp3_hit   = False
    sl_hit    = False
    tp1_candle = None
    max_price_r = 0.0
    r_distance  = abs(entry - stop)

    if r_distance == 0:
        return _empty_outcome()

    for i, (idx, row) in enumerate(forward_df.iterrows()):
        high = row["high"]
        low  = row["low"]

        if direction == "long":
            # Calculate max R achieved this candle
            candle_r = (high - entry) / r_distance
            max_price_r = max(max_price_r, candle_r)

            # Check targets (must be hit in order)
            if not tp1_hit and high >= tp1:
                tp1_hit    = True
                tp1_candle = i + 1

            if tp1_hit and not tp2_hit and high >= tp2:
                tp2_hit = True

            if tp2_hit and not tp3_hit and high >= tp3:
                tp3_hit = True

            # Check stop
            if low <= stop:
                sl_hit = True
                break

            # If all TPs hit, we're done
            if tp3_hit:
                break

        elif direction == "short":
            candle_r = (entry - low) / r_distance
            max_price_r = max(max_price_r, candle_r)

            if not tp1_hit and low <= tp1:
                tp1_hit    = True
                tp1_candle = i + 1

            if tp1_hit and not tp2_hit and low <= tp2:
                tp2_hit = True

            if tp2_hit and not tp3_hit and low <= tp3:
                tp3_hit = True

            if high >= stop:
                sl_hit = True
                break

            if tp3_hit:
                break

    # Build outcome string
    if tp3_hit:
        outcome = "TP3_HIT"
    elif tp2_hit and sl_hit:
        outcome = "TP2_THEN_SL"
    elif tp2_hit:
        outcome = "TP2_HIT"
    elif tp1_hit and sl_hit:
        outcome = "TP1_THEN_SL"
    elif tp1_hit:
        outcome = "TP1_HIT"
    elif sl_hit:
        outcome = "SL_HIT"
    else:
        outcome = "OPEN"   # Didn't resolve within forward window

    # Calculate final R
    if tp3_hit:
        final_r = TP3_R
    elif tp2_hit:
        final_r = TP2_R if not sl_hit else TP1_R * 0.4 + TP2_R * 0.4 - 1.0
    elif tp1_hit:
        final_r = TP1_R if not sl_hit else TP1_R * 0.4 - 0.6
    elif sl_hit:
        final_r = -1.0
    else:
        final_r = round(max_price_r, 2)

    return {
        "outcome":    outcome,
        "tp1_hit":    tp1_hit,
        "tp2_hit":    tp2_hit,
        "tp3_hit":    tp3_hit,
        "sl_hit":     sl_hit,
        "tp1_candle": tp1_candle,
        "max_r":      round(max_price_r, 2),
        "final_r":    round(final_r, 2),
    }


def _empty_outcome() -> dict:
    return {
        "outcome": "ERROR", "tp1_hit": False, "tp2_hit": False,
        "tp3_hit": False, "sl_hit": False, "tp1_candle": None,
        "max_r": 0.0, "final_r": 0.0,
    }


# =============================================================================
# RESULTS CSV
# =============================================================================

RESULT_HEADERS = [
    "timestamp", "symbol", "direction", "score", "regime",
    "entry", "stop", "tp1", "tp2", "tp3", "r_pct",
    "outcome", "tp1_hit", "tp2_hit", "tp3_hit", "sl_hit",
    "tp1_candle", "max_r", "final_r",
    "l1_score", "l2_score", "l3_score",
    "l4_score", "l5_score", "l6_score",
]


def init_results_csv():
    with open(RESULTS_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RESULT_HEADERS)
        writer.writeheader()


def save_result(signal: dict, outcome: dict, timestamp: str):
    layers = signal.get("layer_scores", [])
    lmap   = {r["layer"]: r for r in layers}

    def ls(name):
        return lmap.get(name, {}).get("score", 0)

    levels = signal.get("levels", {})

    row = {
        "timestamp": timestamp,
        "symbol":    signal["symbol"],
        "direction": signal["direction"],
        "score":     signal["score"],
        "regime":    signal["regime"],
        "entry":     levels.get("entry", ""),
        "stop":      levels.get("stop",  ""),
        "tp1":       levels.get("tp1",   ""),
        "tp2":       levels.get("tp2",   ""),
        "tp3":       levels.get("tp3",   ""),
        "r_pct":     levels.get("r_pct", ""),
        "outcome":   outcome["outcome"],
        "tp1_hit":   outcome["tp1_hit"],
        "tp2_hit":   outcome["tp2_hit"],
        "tp3_hit":   outcome["tp3_hit"],
        "sl_hit":    outcome["sl_hit"],
        "tp1_candle":outcome["tp1_candle"],
        "max_r":     outcome["max_r"],
        "final_r":   outcome["final_r"],
        "l1_score":  ls("L1_structure"),
        "l2_score":  ls("L2_order_flow"),
        "l3_score":  ls("L3_zones"),
        "l4_score":  ls("L4_macro"),
        "l5_score":  ls("L5_momentum"),
        "l6_score":  ls("L6_sentiment"),
    }

    with open(RESULTS_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RESULT_HEADERS)
        writer.writerow(row)


# =============================================================================
# REPORT GENERATOR
# =============================================================================

def generate_report(results: list) -> str:
    """Generates a human readable performance report."""

    if not results:
        return "No signals found in backtest period."

    total     = len(results)
    closed    = [r for r in results if r["outcome"] != "OPEN"]
    wins      = [r for r in closed  if "TP" in r["outcome"]]
    losses    = [r for r in closed  if r["outcome"] == "SL_HIT"]
    partial   = [r for r in closed  if "THEN_SL" in r["outcome"]]
    open_     = [r for r in results if r["outcome"] == "OPEN"]

    win_rate  = round(len(wins) / len(closed) * 100, 1) if closed else 0
    avg_r     = round(sum(float(r["final_r"]) for r in closed) / len(closed), 2) \
                if closed else 0
    avg_max_r = round(sum(float(r["max_r"]) for r in closed) / len(closed), 2) \
                if closed else 0

    # By symbol
    symbols = list(set(r["symbol"] for r in results))
    by_sym  = {}
    for sym in sorted(symbols):
        sc = [r for r in closed if r["symbol"] == sym]
        sw = [r for r in sc    if "TP" in r["outcome"]]
        by_sym[sym] = {
            "total":    len([r for r in results if r["symbol"] == sym]),
            "closed":   len(sc),
            "wins":     len(sw),
            "win_rate": round(len(sw) / len(sc) * 100, 1) if sc else 0,
            "avg_r":    round(sum(float(r["final_r"]) for r in sc) / len(sc), 2) if sc else 0,
        }

    # By direction
    longs  = [r for r in closed if r["direction"] == "long"]
    shorts = [r for r in closed if r["direction"] == "short"]
    long_wins  = [r for r in longs  if "TP" in r["outcome"]]
    short_wins = [r for r in shorts if "TP" in r["outcome"]]

    # By regime
    regimes = list(set(r["regime"] for r in closed))
    by_reg  = {}
    for reg in sorted(regimes):
        rc = [r for r in closed if r["regime"] == reg]
        rw = [r for r in rc    if "TP" in r["outcome"]]
        by_reg[reg] = {
            "total":    len(rc),
            "wins":     len(rw),
            "win_rate": round(len(rw) / len(rc) * 100, 1) if rc else 0,
        }

    # By score tier
    standard = [r for r in closed
                if 65 <= float(r["score"]) < 80]
    high_conv = [r for r in closed
                 if 80 <= float(r["score"]) < 90]
    max_size  = [r for r in closed
                 if float(r["score"]) >= 90]

    std_wins = [r for r in standard  if "TP" in r["outcome"]]
    hc_wins  = [r for r in high_conv if "TP" in r["outcome"]]
    ms_wins  = [r for r in max_size  if "TP" in r["outcome"]]

    # Outcome distribution
    tp1_only  = len([r for r in closed if r["outcome"] == "TP1_HIT"])
    tp2_only  = len([r for r in closed if r["outcome"] == "TP2_HIT"])
    tp3_only  = len([r for r in closed if r["outcome"] == "TP3_HIT"])
    tp1_sl    = len([r for r in closed if r["outcome"] == "TP1_THEN_SL"])
    tp2_sl    = len([r for r in closed if r["outcome"] == "TP2_THEN_SL"])
    sl_only   = len([r for r in closed if r["outcome"] == "SL_HIT"])

    lines = [
        "=" * 60,
        "APEX SYSTEM — BACKTEST REPORT",
        "SilerTrades · A Division of 96 Bulls Financial Group",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}",
        f"Period: {BACKTEST_DAYS} days",
        "=" * 60,
        "",
        "OVERALL PERFORMANCE",
        "-" * 40,
        f"Total signals:      {total}",
        f"Closed:             {len(closed)}",
        f"Open (unresolved):  {len(open_)}",
        f"Winners:            {len(wins)}",
        f"Losers (full SL):   {len(losses)}",
        f"Partial (TP→SL):    {len(partial)}",
        f"Win rate:           {win_rate}%",
        f"Avg R per trade:    {avg_r}R",
        f"Avg max R reached:  {avg_max_r}R",
        "",
        "OUTCOME BREAKDOWN",
        "-" * 40,
        f"TP3 hit (full run):    {tp3_only}",
        f"TP2 hit:               {tp2_only}",
        f"TP2 then SL:           {tp2_sl}",
        f"TP1 hit:               {tp1_only}",
        f"TP1 then SL:           {tp1_sl}",
        f"SL hit (no TP):        {sl_only}",
        "",
        "BY DIRECTION",
        "-" * 40,
        f"Longs:   {len(longs)} trades | "
        f"{round(len(long_wins)/len(longs)*100,1) if longs else 0}% win rate",
        f"Shorts:  {len(shorts)} trades | "
        f"{round(len(short_wins)/len(shorts)*100,1) if shorts else 0}% win rate",
        "",
        "BY SYMBOL",
        "-" * 40,
    ]

    for sym, stats in by_sym.items():
        lines.append(
            f"{sym:<12} {stats['total']:>3} signals | "
            f"{stats['closed']:>3} closed | "
            f"{stats['win_rate']:>5}% win | "
            f"{stats['avg_r']:>5}R avg"
        )

    lines += [
        "",
        "BY REGIME",
        "-" * 40,
    ]
    for reg, stats in by_reg.items():
        lines.append(
            f"{reg:<20} {stats['total']:>3} trades | "
            f"{stats['win_rate']:>5}% win rate"
        )

    lines += [
        "",
        "BY SCORE TIER",
        "-" * 40,
        f"Standard  (65-79): {len(standard):>3} trades | "
        f"{round(len(std_wins)/len(standard)*100,1) if standard else 0}% win",
        f"High conv (80-89): {len(high_conv):>3} trades | "
        f"{round(len(hc_wins)/len(high_conv)*100,1) if high_conv else 0}% win",
        f"Max size  (90+):   {len(max_size):>3} trades | "
        f"{round(len(ms_wins)/len(max_size)*100,1) if max_size else 0}% win",
        "",
        "=" * 60,
        "KEY INSIGHTS",
        "-" * 40,
    ]

    # Auto insights
    if win_rate >= 55:
        lines.append(f"✅ System has positive edge — {win_rate}% win rate")
    elif win_rate >= 45:
        lines.append(f"⚠️  Marginal edge — {win_rate}% win rate, monitor closely")
    else:
        lines.append(f"❌ Below 50% win rate — review layer weights")

    if avg_r > 0:
        lines.append(f"✅ Positive expectancy — avg {avg_r}R per closed trade")
    else:
        lines.append(f"❌ Negative expectancy — losing money on average")

    best_sym = max(by_sym.items(), key=lambda x: x[1]["win_rate"]) \
               if by_sym else None
    if best_sym:
        lines.append(
            f"🏆 Best symbol: {best_sym[0]} "
            f"({best_sym[1]['win_rate']}% win rate)"
        )

    best_reg = max(by_reg.items(), key=lambda x: x[1]["win_rate"]) \
               if by_reg else None
    if best_reg:
        lines.append(
            f"🏆 Best regime: {best_reg[0]} "
            f"({best_reg[1]['win_rate']}% win rate)"
        )

    if len(high_conv) > 0 and len(standard) > 0:
        hc_wr  = round(len(hc_wins) /len(high_conv)*100, 1)
        std_wr = round(len(std_wins)/len(standard)*100,  1)
        if hc_wr > std_wr:
            lines.append(
                f"✅ High conviction signals outperform standard "
                f"({hc_wr}% vs {std_wr}%)"
            )

    lines += [
        "",
        "FILES",
        "-" * 40,
        f"Full results: {RESULTS_CSV}",
        f"This report:  {REPORT_TXT}",
        "=" * 60,
    ]

    return "\n".join(lines)


# =============================================================================
# MAIN BACKTEST LOOP
# =============================================================================

def run_backtest():
    log.info("=" * 60)
    log.info("APEX BACKTEST ENGINE STARTING")
    log.info(f"Period: {BACKTEST_DAYS} days")
    log.info(f"Symbols: {CRYPTO_SYMBOLS}")
    log.info(f"Score threshold: {BACKTEST_SCORE_THRESHOLD} (backtest mode)")
    log.info("=" * 60)

    # Step 1: Fetch all historical data
    log.info("Fetching historical data...")
    all_data = {}

    for symbol in CRYPTO_SYMBOLS:
        all_data[symbol] = {}
        for tf_name, interval in TF_INTERVALS.items():
            df = fetch_historical(symbol, interval, BACKTEST_DAYS + 30)
            if not df.empty:
                all_data[symbol][tf_name] = df
            time.sleep(0.3)

    # Step 2: Initialize results CSV
    init_results_csv()
    all_results = []
    total_signals = 0

    # Step 3: Walk through history symbol by symbol
    for symbol in CRYPTO_SYMBOLS:
        if "MTF" not in all_data[symbol]:
            log.warning(f"No MTF data for {symbol} — skipping")
            continue

        mtf_df     = all_data[symbol]["MTF"]
        n_candles  = len(mtf_df)
        signals_found = 0

        log.info(f"Running backtest for {symbol} "
                 f"({n_candles} candles)...")

        # Step through candles with warmup offset
        for i in range(WARMUP_CANDLES, n_candles - FORWARD_CANDLES, STEP_CANDLES):

            # Build candles dict as bot would see at this point
            candles = build_candles_at_point(all_data, symbol, i, mtf_df)

            if len(candles) < 2:
                continue

            # Score this point in time
            signal = score_at_point(candles, symbol)

            if signal is None:
                continue

            # Signal found — check outcome
            forward_df = mtf_df.iloc[i:i + FORWARD_CANDLES]
            levels     = signal["levels"]
            outcome    = check_outcome(
                direction = signal["direction"],
                entry     = levels["entry"],
                stop      = levels["stop"],
                tp1       = levels["tp1"],
                tp2       = levels["tp2"],
                tp3       = levels["tp3"],
                forward_df= forward_df,
            )

            timestamp = str(mtf_df.index[i])[:19]
            save_result(signal, outcome, timestamp)
            all_results.append({**signal, **outcome, "timestamp": timestamp})
            signals_found += 1
            total_signals += 1

            log.info(
                f"  {symbol} {timestamp} | "
                f"{signal['direction'].upper()} | "
                f"Score: {signal['score']} | "
                f"Outcome: {outcome['outcome']} | "
                f"R: {outcome['final_r']}"
            )

            # Skip forward to avoid overlapping signals
            # (don't fire another signal while the first is still open)
            if outcome["outcome"] != "OPEN":
                i += outcome.get("tp1_candle", 10) or 10

        log.info(f"{symbol}: {signals_found} signals found.")

    # Step 4: Generate report
    log.info(f"Backtest complete. Total signals: {total_signals}")
    report = generate_report(all_results)

    with open(REPORT_TXT, "w") as f:
        f.write(report)

    print("\n" + report)
    log.info(f"Results saved to {RESULTS_CSV}")
    log.info(f"Report saved to {REPORT_TXT}")


# =============================================================================
# RUN
# =============================================================================

if __name__ == "__main__":
    run_backtest()
