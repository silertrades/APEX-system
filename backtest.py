# =============================================================================
# APEX SYSTEM — backtest.py
# =============================================================================
# Walks through 1 year of historical data candle by candle,
# runs all 6 scoring layers at each point, logs signals,
# and checks forward to see if TP or SL was hit.
#
# Uses scoring_engine.run() directly so ALL live filters apply.
#
# Historical data simulation:
#   - Funding rates: pulled from Binance historical API (exact data)
#   - CVD: approximated from kline taker_buy_base volume
#     (taker buy volume - taker sell volume = net delta per candle)
#
# HOW TO RUN:
#   Set RUN_MODE=backtest in Railway variables
# =============================================================================

import os
import csv
import time
import logging
import numpy as np
import pandas as pd
import requests
from datetime import datetime, timedelta

from scoring_engine import run as score_symbol
from config import (
    CRYPTO_SYMBOLS,
    TIMEFRAMES,
    CVD_LOOKBACK,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("backtest")

# =============================================================================
# SETTINGS
# =============================================================================

BACKTEST_DAYS   = 365
WARMUP_CANDLES  = 250
STEP_CANDLES    = 4
FORWARD_CANDLES = 100
RESULTS_CSV     = "backtest_results.csv"
REPORT_TXT      = "backtest_report.txt"
BINANCE_REST    = "https://api.binance.com"
BINANCE_FAPI    = "https://fapi.binance.com"

TF_INTERVALS = {
    "HTF": "1d",
    "MTF": "4h",
    "ITF": "1h",
    "LTF": "15m",
}


# =============================================================================
# DATA FETCHING
# =============================================================================

def fetch_historical(symbol: str, interval: str, days: int,
                     include_taker: bool = False) -> pd.DataFrame:
    """
    Fetches OHLCV from Binance.
    If include_taker=True, also returns taker_buy_base volume
    which we use to approximate CVD.
    """
    log.info(f"Fetching {symbol} {interval} — {days} days...")

    all_candles = []
    end_time    = int(datetime.now().timestamp() * 1000)
    start_time  = int((datetime.now() -
                       timedelta(days=days)).timestamp() * 1000)

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

    # Always keep taker_buy_base for CVD approximation
    df["taker_buy_base"]  = df["taker_buy_base"].astype(float)
    df["taker_sell_base"] = df["volume"].astype(float) - \
                            df["taker_buy_base"]

    df = df[["open", "high", "low", "close", "volume",
             "taker_buy_base", "taker_sell_base"]].astype(float)
    df.dropna(inplace=True)

    log.info(f"  {symbol} {interval}: {len(df)} candles loaded.")
    return df


def fetch_funding_rates(symbol: str, days: int) -> pd.DataFrame:
    """
    Fetches historical funding rates from Binance perpetual futures API.
    Returns DataFrame indexed by timestamp with 'funding_rate' column.
    Funding rates are published every 8 hours.
    """
    log.info(f"Fetching funding rates for {symbol}...")

    all_rates  = []
    end_time   = int(datetime.now().timestamp() * 1000)
    start_time = int((datetime.now() -
                      timedelta(days=days)).timestamp() * 1000)

    while start_time < end_time:
        try:
            resp = requests.get(
                f"{BINANCE_FAPI}/fapi/v1/fundingRate",
                params={
                    "symbol":    symbol,
                    "startTime": start_time,
                    "limit":     1000,
                },
                timeout=15
            )
            resp.raise_for_status()
            rates = resp.json()

            if not rates:
                break

            all_rates.extend(rates)
            start_time = rates[-1]["fundingTime"] + 1
            time.sleep(0.3)

        except Exception as e:
            log.error(f"Funding rate fetch error {symbol}: {e}")
            time.sleep(3)
            break

    if not all_rates:
        log.warning(f"No funding rate data for {symbol}")
        return pd.DataFrame()

    df = pd.DataFrame(all_rates)
    df["timestamp"]    = pd.to_datetime(df["fundingTime"], unit="ms")
    df["funding_rate"] = df["fundingRate"].astype(float)
    df.set_index("timestamp", inplace=True)
    df = df[["funding_rate"]]

    log.info(f"  {symbol}: {len(df)} funding rate records loaded.")
    return df


def get_funding_rate_at(funding_df: pd.DataFrame,
                        timestamp: pd.Timestamp) -> float:
    """
    Returns the most recent funding rate at or before a given timestamp.
    Funding rates are published every 8 hours so we find the nearest one.
    """
    if funding_df.empty:
        return 0.0
    try:
        # Get all rates up to this timestamp
        available = funding_df[funding_df.index <= timestamp]
        if available.empty:
            return 0.0
        return float(available["funding_rate"].iloc[-1])
    except Exception:
        return 0.0


# =============================================================================
# CVD APPROXIMATION FROM KLINE DATA
# =============================================================================

def build_cvd_from_klines(df: pd.DataFrame,
                           lookback: int = CVD_LOOKBACK) -> dict:
    """
    Approximates CVD divergence from kline taker volume data.

    Each kline has:
    - taker_buy_base:  volume of buyer-initiated trades
    - taker_sell_base: volume of seller-initiated trades (total - buy)

    Delta per candle = taker_buy_base - taker_sell_base
    CVD = cumulative sum of deltas

    Then we detect divergence the same way the live system does:
    price moving one way, CVD moving the other.

    Returns a dict matching the format of live cvd_divergence.
    """
    if len(df) < lookback + 5:
        return {"divergence": "none", "strength": 0.0,
                "description": "Insufficient data for CVD"}

    recent = df.tail(lookback).copy()

    # Calculate delta per candle
    recent["delta"] = recent["taker_buy_base"] - recent["taker_sell_base"]

    # Cumulative sum = CVD
    cvd    = recent["delta"].cumsum().values
    prices = recent["close"].values

    if len(cvd) < 5 or len(prices) < 5:
        return {"divergence": "none", "strength": 0.0,
                "description": "Insufficient data"}

    mid = len(cvd) // 2

    price_moved_dn = prices[mid:].mean() < prices[:mid].mean()
    price_moved_up = prices[mid:].mean() > prices[:mid].mean()
    cvd_moved_up   = cvd[mid:].mean()    > cvd[:mid].mean()
    cvd_moved_dn   = cvd[mid:].mean()    < cvd[:mid].mean()

    # Bullish divergence: price down, CVD up
    if price_moved_dn and cvd_moved_up:
        strength = min(1.0, abs(prices[-1] - prices[0]) /
                       (prices[0] + 1e-9) * 10)
        return {
            "divergence":  "bullish",
            "strength":    round(strength, 3),
            "description": "Bullish CVD div (kline approx): "
                           "price down, CVD up"
        }

    # Bearish divergence: price up, CVD down
    if price_moved_up and cvd_moved_dn:
        strength = min(1.0, abs(prices[-1] - prices[0]) /
                       (prices[0] + 1e-9) * 10)
        return {
            "divergence":  "bearish",
            "strength":    round(strength, 3),
            "description": "Bearish CVD div (kline approx): "
                           "price up, CVD down"
        }

    return {"divergence": "none", "strength": 0.0,
            "description": "No CVD divergence"}


# =============================================================================
# BUILD DATA DICT AT POINT IN TIME
# =============================================================================

def build_candles_at_point(all_data: dict, symbol: str,
                            mtf_idx: int,
                            mtf_df: pd.DataFrame) -> dict:
    current_time = mtf_df.index[mtf_idx]
    candles = {}

    for tf_name, tf_df in all_data[symbol].items():
        available = tf_df[tf_df.index <= current_time]
        if len(available) >= 50:
            candles[tf_name] = available.tail(500).copy()

    return candles


def build_data_dict(symbol: str, candles: dict,
                    funding_df: pd.DataFrame,
                    current_time: pd.Timestamp) -> dict:
    """
    Builds the full data dict that scoring_engine.run() expects.
    Uses real historical funding rates and kline-based CVD approximation.
    """
    # Get funding rate at this point in time
    funding_rate = get_funding_rate_at(funding_df, current_time)

    # Build CVD from LTF kline data
    ltf_df         = candles.get("LTF", pd.DataFrame())
    cvd_divergence = {"divergence": "none", "strength": 0.0,
                      "description": "No LTF data"}

    if not ltf_df.empty and "taker_buy_base" in ltf_df.columns:
        cvd_divergence = build_cvd_from_klines(ltf_df, CVD_LOOKBACK)

    # Get OI change — use 0 for backtest (not available historically)
    oi_data = {"oi": 0.0, "oi_change_pct": 0.0}

    return {
        "symbol":         symbol,
        "candles":        candles,
        "cvd_divergence": cvd_divergence,
        "macro": {
            "vix":               20.0,  # Neutral — VIX history not pulled
            "dxy_momentum":      0.0,
            "yield_curve_slope": 1.0,
        },
        "sentiment": {
            "funding_rate": funding_rate,   # Real historical data
            "oi":           oi_data,
        },
        "timestamp": str(current_time),
    }


# =============================================================================
# OUTCOME CHECKING
# =============================================================================

def check_outcome(direction: str, entry: float, stop: float,
                  tp1: float, tp2: float, tp3: float,
                  forward_df: pd.DataFrame) -> dict:
    from config import TP1_R, TP2_R, TP3_R

    tp1_hit     = False
    tp2_hit     = False
    tp3_hit     = False
    sl_hit      = False
    tp1_candle  = None
    max_price_r = 0.0
    r_distance  = abs(entry - stop)

    if r_distance == 0:
        return _empty_outcome()

    for i, (idx, row) in enumerate(forward_df.iterrows()):
        high = row["high"]
        low  = row["low"]

        if direction == "long":
            candle_r    = (high - entry) / r_distance
            max_price_r = max(max_price_r, candle_r)

            if not tp1_hit and high >= tp1:
                tp1_hit    = True
                tp1_candle = i + 1
            if tp1_hit and not tp2_hit and high >= tp2:
                tp2_hit = True
            if tp2_hit and not tp3_hit and high >= tp3:
                tp3_hit = True
            if low <= stop:
                sl_hit = True
                break
            if tp3_hit:
                break

        elif direction == "short":
            candle_r    = (entry - low) / r_distance
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
        outcome = "OPEN"

    if tp3_hit:
        final_r = TP3_R
    elif tp2_hit and not sl_hit:
        final_r = TP2_R
    elif tp2_hit and sl_hit:
        final_r = TP1_R * 0.4 + TP2_R * 0.4 - 1.0
    elif tp1_hit and not sl_hit:
        final_r = TP1_R
    elif tp1_hit and sl_hit:
        final_r = TP1_R * 0.4 - 0.6
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
    "funding_rate", "cvd_divergence",
]


def init_results_csv():
    with open(RESULTS_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RESULT_HEADERS)
        writer.writeheader()


def save_result(signal: dict, outcome: dict,
                timestamp: str, data: dict):
    layers = signal.get("layer_scores", [])
    lmap   = {r["layer"]: r for r in layers}

    def ls(name):
        return lmap.get(name, {}).get("score", 0)

    levels = signal.get("levels", {})

    row = {
        "timestamp":      timestamp,
        "symbol":         signal["symbol"],
        "direction":      signal["direction"],
        "score":          signal["score"],
        "regime":         signal["regime"],
        "entry":          levels.get("entry", ""),
        "stop":           levels.get("stop",  ""),
        "tp1":            levels.get("tp1",   ""),
        "tp2":            levels.get("tp2",   ""),
        "tp3":            levels.get("tp3",   ""),
        "r_pct":          levels.get("r_pct", ""),
        "outcome":        outcome["outcome"],
        "tp1_hit":        outcome["tp1_hit"],
        "tp2_hit":        outcome["tp2_hit"],
        "tp3_hit":        outcome["tp3_hit"],
        "sl_hit":         outcome["sl_hit"],
        "tp1_candle":     outcome["tp1_candle"],
        "max_r":          outcome["max_r"],
        "final_r":        outcome["final_r"],
        "l1_score":       ls("L1_structure"),
        "l2_score":       ls("L2_order_flow"),
        "l3_score":       ls("L3_zones"),
        "l4_score":       ls("L4_macro"),
        "l5_score":       ls("L5_momentum"),
        "l6_score":       ls("L6_sentiment"),
        "funding_rate":   data.get("sentiment", {}).get("funding_rate", 0),
        "cvd_divergence": data.get("cvd_divergence", {}).get("divergence", "none"),
    }

    with open(RESULTS_CSV, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RESULT_HEADERS)
        writer.writerow(row)


# =============================================================================
# REPORT GENERATOR
# =============================================================================

def generate_report(results: list) -> str:
    if not results:
        return "No signals found in backtest period."

    total   = len(results)
    closed  = [r for r in results if r["outcome"] != "OPEN"]
    wins    = [r for r in closed  if "TP"       in r["outcome"]]
    losses  = [r for r in closed  if r["outcome"] == "SL_HIT"]
    partial = [r for r in closed  if "THEN_SL"  in r["outcome"]]
    open_   = [r for r in results if r["outcome"] == "OPEN"]

    win_rate  = round(len(wins) / len(closed) * 100, 1) if closed else 0
    avg_r     = round(sum(float(r["final_r"]) for r in closed) /
                      len(closed), 2) if closed else 0
    avg_max_r = round(sum(float(r["max_r"]) for r in closed) /
                      len(closed), 2) if closed else 0

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
            "avg_r":    round(sum(float(r["final_r"]) for r in sc) /
                              len(sc), 2) if sc else 0,
        }

    longs      = [r for r in closed if r["direction"] == "long"]
    long_wins  = [r for r in longs  if "TP" in r["outcome"]]

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

    standard  = [r for r in closed if 65 <= float(r["score"]) < 80]
    high_conv = [r for r in closed if 80 <= float(r["score"]) < 90]
    max_size  = [r for r in closed if float(r["score"]) >= 90]
    std_wins  = [r for r in standard  if "TP" in r["outcome"]]
    hc_wins   = [r for r in high_conv if "TP" in r["outcome"]]
    ms_wins   = [r for r in max_size  if "TP" in r["outcome"]]

    tp3_only = len([r for r in closed if r["outcome"] == "TP3_HIT"])
    tp2_only = len([r for r in closed if r["outcome"] == "TP2_HIT"])
    tp2_sl   = len([r for r in closed if r["outcome"] == "TP2_THEN_SL"])
    tp1_only = len([r for r in closed if r["outcome"] == "TP1_HIT"])
    tp1_sl   = len([r for r in closed if r["outcome"] == "TP1_THEN_SL"])
    sl_only  = len([r for r in closed if r["outcome"] == "SL_HIT"])

    lines = [
        "=" * 60,
        "APEX SYSTEM — BACKTEST REPORT",
        "SilerTrades · A Division of 96 Bulls Financial Group",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}",
        f"Period: {BACKTEST_DAYS} days",
        "Filters: Long only | BTC=75 | Mean-reversion=75",
        "Data: Real funding rates | Kline CVD approximation",
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

    lines += ["", "BY REGIME", "-" * 40]
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

    if win_rate >= 55:
        lines.append(f"✅ System has positive edge — {win_rate}% win rate")
    elif win_rate >= 45:
        lines.append(f"⚠️  Marginal edge — {win_rate}% win rate, "
                     f"monitor closely")
    else:
        lines.append(f"❌ Below 50% win rate — review layer weights")

    if avg_r > 0:
        lines.append(f"✅ Positive expectancy — avg {avg_r}R per trade")
    else:
        lines.append(f"❌ Negative expectancy — losing money on average")

    best_sym = max(by_sym.items(),
                   key=lambda x: x[1]["win_rate"]) if by_sym else None
    if best_sym:
        lines.append(f"🏆 Best symbol: {best_sym[0]} "
                     f"({best_sym[1]['win_rate']}% win rate)")

    best_reg = max(by_reg.items(),
                   key=lambda x: x[1]["win_rate"]) if by_reg else None
    if best_reg:
        lines.append(f"🏆 Best regime: {best_reg[0]} "
                     f"({best_reg[1]['win_rate']}% win rate)")

    if len(high_conv) > 0 and len(standard) > 0:
        hc_wr  = round(len(hc_wins)  / len(high_conv) * 100, 1)
        std_wr = round(len(std_wins) / len(standard)  * 100, 1)
        if hc_wr > std_wr:
            lines.append(f"✅ High conviction outperforms standard "
                         f"({hc_wr}% vs {std_wr}%)")

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
    log.info("Filters: Long only | BTC=75 | Mean-reversion=75")
    log.info("Data: Real funding rates + kline CVD approximation")
    log.info("=" * 60)

    # Step 1: Fetch all historical data
    log.info("Fetching historical OHLCV data...")
    all_data     = {}
    funding_data = {}

    for symbol in CRYPTO_SYMBOLS:
        all_data[symbol] = {}

        for tf_name, interval in TF_INTERVALS.items():
            df = fetch_historical(symbol, interval,
                                  BACKTEST_DAYS + 30,
                                  include_taker=True)
            if not df.empty:
                all_data[symbol][tf_name] = df
            time.sleep(0.3)

        # Fetch historical funding rates
        funding_data[symbol] = fetch_funding_rates(
            symbol, BACKTEST_DAYS + 30)
        time.sleep(0.3)

    # Step 2: Initialize results
    init_results_csv()
    all_results   = []
    total_signals = 0

    # Step 3: Walk through history symbol by symbol
    for symbol in CRYPTO_SYMBOLS:
        if "MTF" not in all_data[symbol]:
            log.warning(f"No MTF data for {symbol} — skipping")
            continue

        mtf_df        = all_data[symbol]["MTF"]
        n_candles     = len(mtf_df)
        signals_found = 0
        funding_df    = funding_data.get(symbol, pd.DataFrame())

        log.info(f"Running backtest for {symbol} ({n_candles} candles)...")

        i = WARMUP_CANDLES
        while i < n_candles - FORWARD_CANDLES:

            current_time = mtf_df.index[i]

            # Build candles dict
            candles = build_candles_at_point(
                all_data, symbol, i, mtf_df)

            if len(candles) < 2:
                i += STEP_CANDLES
                continue

            # Build full data dict with real funding + CVD
            data = build_data_dict(
                symbol, candles, funding_df, current_time)

            # Run through live scoring engine with all filters
            signal = score_symbol(data)

            if signal is None:
                i += STEP_CANDLES
                continue

            # Signal fired — check outcome
            forward_df = mtf_df.iloc[i:i + FORWARD_CANDLES]
            levels     = signal["levels"]
            outcome    = check_outcome(
                direction  = signal["direction"],
                entry      = levels["entry"],
                stop       = levels["stop"],
                tp1        = levels["tp1"],
                tp2        = levels["tp2"],
                tp3        = levels["tp3"],
                forward_df = forward_df,
            )

            timestamp = str(mtf_df.index[i])[:19]
            save_result(signal, outcome, timestamp, data)
            all_results.append({**signal, **outcome,
                                 "timestamp": timestamp})
            signals_found += 1
            total_signals += 1

            # Log signal
            funding_at_point = data.get("sentiment", {}).get(
                "funding_rate", 0)
            cvd_at_point     = data.get("cvd_divergence", {}).get(
                "divergence", "none")

            log.info(
                f"  {symbol} {timestamp} | "
                f"LONG | Score: {signal['score']} | "
                f"Regime: {signal['regime']} | "
                f"Funding: {funding_at_point*100:.3f}% | "
                f"CVD: {cvd_at_point} | "
                f"Outcome: {outcome['outcome']} | "
                f"R: {outcome['final_r']}"
            )

            skip = outcome.get("tp1_candle", STEP_CANDLES) or STEP_CANDLES
            i += max(STEP_CANDLES, skip)

        log.info(f"{symbol}: {signals_found} signals found.")

    # Step 4: Generate report
    log.info(f"Backtest complete. Total signals: {total_signals}")
    report = generate_report(all_results)

    with open(REPORT_TXT, "w") as f:
        f.write(report)

    print("\n" + report)
    log.info(f"Results saved to {RESULTS_CSV}")
    log.info(f"Report saved to {REPORT_TXT}")


if __name__ == "__main__":
    run_backtest()
