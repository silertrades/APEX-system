# =============================================================================
# APEX SYSTEM — signal_tracker.py
# =============================================================================
# Logs every signal and automatically tracks outcomes.
#
# How it works:
#   - Every signal fires → logged to CSV as OPEN
#   - Bot keeps a watchlist of all open signals
#   - Every scan, check_open_signals() is called
#   - When price hits TP1 → logs TP1_HIT, keeps watching
#   - When price hits TP2 → logs TP2_HIT, keeps watching
#   - When price hits TP3 → logs TP3_HIT, signal closed
#   - When price hits SL  → logs SL_HIT (or TP1_THEN_SL etc)
#   - Full journey recorded automatically, zero manual work
#
# CSV lives at /app/signals.csv on Railway
# Download from Railway dashboard: Files tab → /app/signals.csv
# =============================================================================

import csv
import os
import logging
from datetime import datetime
from copy import deepcopy

log = logging.getLogger("signal_tracker")

CSV_PATH = "/app/signals.csv"

HEADERS = [
    # Signal info
    "timestamp",
    "symbol",
    "direction",
    "score",
    "tier",
    "regime",

    # Levels
    "entry",
    "stop",
    "tp1",
    "tp2",
    "tp3",
    "r_pct",

    # Layer scores
    "l1_score",
    "l2_score",
    "l3_score",
    "l4_score",
    "l5_score",
    "l6_score",

    # Layer directions
    "l1_direction",
    "l2_direction",
    "l3_direction",
    "l4_direction",
    "l5_direction",
    "l6_direction",

    # Top reason from each layer
    "l1_reason",
    "l2_reason",
    "l3_reason",
    "l4_reason",
    "l5_reason",
    "l6_reason",

    # Outcome tracking
    "outcome",           # Final outcome string e.g. TP2_THEN_SL
    "tp1_hit",           # True/False
    "tp1_hit_time",      # Timestamp when TP1 was hit
    "tp2_hit",           # True/False
    "tp2_hit_time",
    "tp3_hit",           # True/False
    "tp3_hit_time",
    "sl_hit",            # True/False
    "sl_hit_time",
    "outcome_notes",
]


# =============================================================================
# IN-MEMORY WATCHLIST
# =============================================================================
# Tracks all open signals between scans.
# Each entry is a dict with the signal data plus tracking state.

_watchlist = []


# =============================================================================
# SETUP
# =============================================================================

def ensure_csv_exists():
    """Creates CSV with headers if it doesn't exist."""
    if not os.path.exists(CSV_PATH):
        try:
            os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
            with open(CSV_PATH, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=HEADERS)
                writer.writeheader()
            log.info(f"Signal tracker CSV created at {CSV_PATH}")
        except Exception as e:
            log.error(f"Could not create CSV: {e}")
    else:
        log.info(f"Signal tracker CSV found — appending to existing log.")
        _load_open_signals()


def _load_open_signals():
    """
    On startup, reload any open signals from CSV into watchlist.
    This means the bot survives restarts without losing open trades.
    """
    signals = get_all_signals()
    open_signals = [s for s in signals if not _is_closed(s)]
    for s in open_signals:
        _watchlist.append(s)
    if open_signals:
        log.info(f"Reloaded {len(open_signals)} open signals into watchlist.")


def _is_closed(row: dict) -> bool:
    """A signal is closed when SL is hit OR all 3 TPs are hit."""
    sl_hit  = str(row.get("sl_hit",  "")).lower() == "true"
    tp3_hit = str(row.get("tp3_hit", "")).lower() == "true"
    return sl_hit or tp3_hit


# =============================================================================
# LOG A NEW SIGNAL
# =============================================================================

def log_signal(signal: dict):
    """
    Logs a new signal to CSV and adds it to the watchlist.
    Called by alert_manager every time an alert fires.
    """
    try:
        levels = signal.get("levels", {})
        layers = signal.get("layer_scores", [])
        layer_lookup = {r["layer"]: r for r in layers}

        def get_layer(name, field, default=""):
            layer = layer_lookup.get(name, {})
            if field == "reason":
                reasons = layer.get("reasons", [])
                return reasons[0][:100] if reasons else ""
            return layer.get(field, default)

        row = {
            "timestamp":     signal.get("timestamp", str(datetime.now()))[:19],
            "symbol":        signal.get("symbol", ""),
            "direction":     signal.get("direction", ""),
            "score":         signal.get("score", 0),
            "tier":          signal.get("tier", ""),
            "regime":        signal.get("regime", ""),
            "entry":         levels.get("entry", ""),
            "stop":          levels.get("stop", ""),
            "tp1":           levels.get("tp1", ""),
            "tp2":           levels.get("tp2", ""),
            "tp3":           levels.get("tp3", ""),
            "r_pct":         levels.get("r_pct", ""),
            "l1_score":      get_layer("L1_structure",  "score", 0),
            "l2_score":      get_layer("L2_order_flow", "score", 0),
            "l3_score":      get_layer("L3_zones",      "score", 0),
            "l4_score":      get_layer("L4_macro",      "score", 0),
            "l5_score":      get_layer("L5_momentum",   "score", 0),
            "l6_score":      get_layer("L6_sentiment",  "score", 0),
            "l1_direction":  get_layer("L1_structure",  "direction", ""),
            "l2_direction":  get_layer("L2_order_flow", "direction", ""),
            "l3_direction":  get_layer("L3_zones",      "direction", ""),
            "l4_direction":  get_layer("L4_macro",      "direction", ""),
            "l5_direction":  get_layer("L5_momentum",   "direction", ""),
            "l6_direction":  get_layer("L6_sentiment",  "direction", ""),
            "l1_reason":     get_layer("L1_structure",  "reason"),
            "l2_reason":     get_layer("L2_order_flow", "reason"),
            "l3_reason":     get_layer("L3_zones",      "reason"),
            "l4_reason":     get_layer("L4_macro",      "reason"),
            "l5_reason":     get_layer("L5_momentum",   "reason"),
            "l6_reason":     get_layer("L6_sentiment",  "reason"),
            "outcome":       "OPEN",
            "tp1_hit":       "False",
            "tp1_hit_time":  "",
            "tp2_hit":       "False",
            "tp2_hit_time":  "",
            "tp3_hit":       "False",
            "tp3_hit_time":  "",
            "sl_hit":        "False",
            "sl_hit_time":   "",
            "outcome_notes": "",
        }

        _append_row(row)
        _watchlist.append(row)
        log.info(f"Signal logged: {row['symbol']} {row['direction']} "
                 f"score:{row['score']} entry:{row['entry']}")

    except Exception as e:
        log.error(f"Failed to log signal: {e}")


# =============================================================================
# AUTOMATIC OUTCOME TRACKING
# =============================================================================

def check_open_signals(current_prices: dict):
    """
    Called every scan with current prices for all symbols.
    Checks each open signal against its TP and SL levels.
    Updates CSV automatically when levels are hit.

    current_prices = { "BTCUSDT": 84250.0, "ETHUSDT": 3180.0, ... }
    """
    if not _watchlist:
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for row in list(_watchlist):
        symbol    = row.get("symbol", "")
        direction = row.get("direction", "")
        price     = current_prices.get(symbol)

        if price is None:
            continue

        try:
            entry = float(row.get("entry", 0))
            stop  = float(row.get("stop",  0))
            tp1   = float(row.get("tp1",   0))
            tp2   = float(row.get("tp2",   0))
            tp3   = float(row.get("tp3",   0))
        except (ValueError, TypeError):
            continue

        if entry == 0:
            continue

        changed = False

        if direction == "long":
            # Check TPs (price needs to go UP)
            if str(row.get("tp1_hit")) != "True" and price >= tp1:
                row["tp1_hit"]      = "True"
                row["tp1_hit_time"] = now
                changed = True
                log.info(f"TP1 HIT: {symbol} @ {price:.2f} (target: {tp1:.2f})")
                _send_outcome_alert(symbol, "TP1 HIT", price, row)

            if str(row.get("tp1_hit")) == "True" and \
               str(row.get("tp2_hit")) != "True" and price >= tp2:
                row["tp2_hit"]      = "True"
                row["tp2_hit_time"] = now
                changed = True
                log.info(f"TP2 HIT: {symbol} @ {price:.2f} (target: {tp2:.2f})")
                _send_outcome_alert(symbol, "TP2 HIT", price, row)

            if str(row.get("tp2_hit")) == "True" and \
               str(row.get("tp3_hit")) != "True" and price >= tp3:
                row["tp3_hit"]      = "True"
                row["tp3_hit_time"] = now
                changed = True
                log.info(f"TP3 HIT: {symbol} @ {price:.2f} (target: {tp3:.2f})")
                _send_outcome_alert(symbol, "TP3 HIT ✅✅✅", price, row)

            # Check SL (price needs to go DOWN)
            if str(row.get("sl_hit")) != "True" and price <= stop:
                row["sl_hit"]      = "True"
                row["sl_hit_time"] = now
                changed = True
                log.info(f"SL HIT: {symbol} @ {price:.2f} (stop: {stop:.2f})")
                _send_outcome_alert(symbol, "STOP LOSS HIT", price, row)

        elif direction == "short":
            # Check TPs (price needs to go DOWN)
            if str(row.get("tp1_hit")) != "True" and price <= tp1:
                row["tp1_hit"]      = "True"
                row["tp1_hit_time"] = now
                changed = True
                log.info(f"TP1 HIT: {symbol} @ {price:.2f} (target: {tp1:.2f})")
                _send_outcome_alert(symbol, "TP1 HIT", price, row)

            if str(row.get("tp1_hit")) == "True" and \
               str(row.get("tp2_hit")) != "True" and price <= tp2:
                row["tp2_hit"]      = "True"
                row["tp2_hit_time"] = now
                changed = True
                log.info(f"TP2 HIT: {symbol} @ {price:.2f} (target: {tp2:.2f})")
                _send_outcome_alert(symbol, "TP2 HIT", price, row)

            if str(row.get("tp2_hit")) == "True" and \
               str(row.get("tp3_hit")) != "True" and price <= tp3:
                row["tp3_hit"]      = "True"
                row["tp3_hit_time"] = now
                changed = True
                log.info(f"TP3 HIT: {symbol} @ {price:.2f} (target: {tp3:.2f})")
                _send_outcome_alert(symbol, "TP3 HIT ✅✅✅", price, row)

            # Check SL (price needs to go UP)
            if str(row.get("sl_hit")) != "True" and price >= stop:
                row["sl_hit"]      = "True"
                row["sl_hit_time"] = now
                changed = True
                log.info(f"SL HIT: {symbol} @ {price:.2f} (stop: {stop:.2f})")
                _send_outcome_alert(symbol, "STOP LOSS HIT", price, row)

        if changed:
            # Update the outcome summary string
            row["outcome"] = _build_outcome_string(row)
            _update_csv_row(row)

            # Remove from watchlist if closed
            if _is_closed(row):
                _watchlist.remove(row)
                log.info(f"Signal closed: {symbol} | Final outcome: {row['outcome']}")


def _build_outcome_string(row: dict) -> str:
    """
    Builds a human readable outcome string from the tracking flags.

    Examples:
        TP3_HIT                  (hit all three targets)
        TP2_THEN_SL              (hit TP1 and TP2, then stopped out)
        TP1_THEN_SL              (hit TP1, then stopped out)
        SL_HIT                   (stopped out immediately)
        OPEN                     (still active)
    """
    tp1 = str(row.get("tp1_hit")) == "True"
    tp2 = str(row.get("tp2_hit")) == "True"
    tp3 = str(row.get("tp3_hit")) == "True"
    sl  = str(row.get("sl_hit"))  == "True"

    if tp3:
        return "TP3_HIT"
    if tp2 and sl:
        return "TP2_THEN_SL"
    if tp2:
        return "TP2_HIT"
    if tp1 and sl:
        return "TP1_THEN_SL"
    if tp1:
        return "TP1_HIT"
    if sl:
        return "SL_HIT"
    return "OPEN"


# =============================================================================
# CSV OPERATIONS
# =============================================================================

def _append_row(row: dict):
    """Appends a new row to the CSV."""
    try:
        with open(CSV_PATH, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=HEADERS)
            writer.writerow(row)
    except Exception as e:
        log.error(f"CSV append failed: {e}")


def _update_csv_row(updated_row: dict):
    """
    Updates an existing row in the CSV by matching timestamp + symbol.
    Rewrites the entire file — fine for the volume we're dealing with.
    """
    try:
        all_rows = get_all_signals()
        with open(CSV_PATH, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=HEADERS)
            writer.writeheader()
            for row in all_rows:
                if (row.get("timestamp") == updated_row.get("timestamp") and
                        row.get("symbol")    == updated_row.get("symbol")):
                    writer.writerow(updated_row)
                else:
                    writer.writerow(row)
    except Exception as e:
        log.error(f"CSV update failed: {e}")


def _send_outcome_alert(symbol: str, event: str, price: float, row: dict):
    """Sends a Telegram notification when a TP or SL is hit."""
    try:
        from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DRY_RUN
        import requests

        direction = row.get("direction", "").upper()
        entry     = row.get("entry", "")
        outcome   = _build_outcome_string(row)

        emoji = "✅" if "TP" in event else "❌"
        message = (
            f"{emoji} *{event}*\n"
            f"{direction} {symbol}\n"
            f"Price: `{price:,.2f}`\n"
            f"Entry was: `{entry}`\n"
            f"Journey so far: {outcome}"
        )

        if DRY_RUN:
            log.info(f"DRY RUN outcome alert: {message}")
            return

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       message,
            "parse_mode": "Markdown",
        }, timeout=5)

    except Exception as e:
        log.error(f"Outcome alert failed: {e}")


# =============================================================================
# READ SIGNALS
# =============================================================================

def get_all_signals() -> list:
    """Returns all logged signals as a list of dicts."""
    if not os.path.exists(CSV_PATH):
        return []
    try:
        with open(CSV_PATH, "r") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception as e:
        log.error(f"Failed to read CSV: {e}")
        return []


def get_todays_signals() -> list:
    today = datetime.now().strftime("%Y-%m-%d")
    return [s for s in get_all_signals()
            if s.get("timestamp", "").startswith(today)]


def get_open_signals() -> list:
    return [s for s in get_all_signals()
            if s.get("outcome") == "OPEN"]


# =============================================================================
# DAILY SUMMARY
# =============================================================================

def get_daily_summary() -> str:
    """Generates a daily Telegram summary of all signals and outcomes."""
    signals     = get_todays_signals()
    all_signals = get_all_signals()

    if not signals:
        return "📊 *Daily Signal Summary*\nNo signals fired today."

    lines = [
        "📊 *Daily Signal Summary*",
        f"_{datetime.now().strftime('%B %d, %Y')}_",
        "",
        f"Signals today: *{len(signals)}*",
        f"Total logged:  *{len(all_signals)}*",
        "",
    ]

    for s in signals:
        direction = s.get("direction", "").upper()
        symbol    = s.get("symbol", "")
        score     = s.get("score", "")
        outcome   = s.get("outcome", "OPEN")
        entry     = s.get("entry", "")
        time_str  = s.get("timestamp", "")[11:16]

        emoji = {
            "TP3_HIT":    "✅✅✅",
            "TP2_HIT":    "✅✅",
            "TP2_THEN_SL":"✅✅❌",
            "TP1_HIT":    "✅",
            "TP1_THEN_SL":"✅❌",
            "SL_HIT":     "❌",
            "OPEN":       "🔵",
        }.get(outcome, "🔵")

        lines.append(
            f"{emoji} {direction} {symbol} | "
            f"Score:{score} | Entry:{entry} | {time_str}"
        )

    # All time stats
    closed = [s for s in all_signals if s.get("outcome") not in ["OPEN", ""]]
    if closed:
        wins     = [s for s in closed if "TP" in s.get("outcome", "")]
        losses   = [s for s in closed if s.get("outcome") == "SL_HIT"]
        partial  = [s for s in closed if "THEN_SL" in s.get("outcome", "")]
        win_rate = round(len(wins) / len(closed) * 100, 1) if closed else 0
        lines += [
            "",
            "─────────────────",
            "*All-time record*",
            f"Closed: {len(closed)} | Wins: {len(wins)} | "
            f"Losses: {len(losses)} | Partial: {len(partial)}",
            f"Win rate: {win_rate}%",
        ]

    return "\n".join(lines)


# =============================================================================
# PERFORMANCE STATS
# =============================================================================

def get_stats() -> dict:
    """Returns performance stats for weight tuning."""
    all_signals = get_all_signals()
    closed      = [s for s in all_signals
                   if s.get("outcome") not in ["OPEN", ""]]

    if not closed:
        return {"message": "No closed signals yet."}

    wins    = [s for s in closed if "TP"      in s.get("outcome", "")]
    losses  = [s for s in closed if s.get("outcome") == "SL_HIT"]
    partial = [s for s in closed if "THEN_SL" in s.get("outcome", "")]

    symbols = list(set(s["symbol"] for s in closed))
    by_symbol = {}
    for sym in symbols:
        sc = [s for s in closed if s["symbol"] == sym]
        sw = [s for s in sc if "TP" in s.get("outcome", "")]
        by_symbol[sym] = {
            "trades":   len(sc),
            "wins":     len(sw),
            "win_rate": round(len(sw) / len(sc) * 100, 1)
        }

    return {
        "total":      len(all_signals),
        "closed":     len(closed),
        "open":       len([s for s in all_signals if s.get("outcome") == "OPEN"]),
        "wins":       len(wins),
        "losses":     len(losses),
        "partial":    len(partial),
        "win_rate":   round(len(wins) / len(closed) * 100, 1),
        "by_symbol":  by_symbol,
    }
