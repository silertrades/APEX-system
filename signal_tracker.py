# =============================================================================
# APEX SYSTEM — signal_tracker.py
# =============================================================================
# Logs every signal that fires to a CSV file.
# This is how the system learns over time.
#
# What gets logged:
#   - Timestamp, symbol, direction, score, tier, regime
#   - Entry, stop, TP1, TP2, TP3 levels
#   - Which layers fired and their individual scores
#   - Outcome (filled in manually or via update function)
#
# CSV lives on Railway's filesystem at /app/signals.csv
# Download it anytime from Railway dashboard to analyze in Excel/Sheets
# =============================================================================

import csv
import os
import logging
from datetime import datetime

log = logging.getLogger("signal_tracker")

# Path to CSV file on Railway
CSV_PATH = "/app/signals.csv"

# CSV column headers
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

    # Outcome — filled in later manually
    # Values: "TP1_HIT", "TP2_HIT", "TP3_HIT", "SL_HIT", "OPEN", "MISSED"
    "outcome",
    "outcome_price",
    "outcome_notes",
]


# =============================================================================
# SETUP
# =============================================================================

def ensure_csv_exists():
    """
    Creates the CSV file with headers if it doesn't exist yet.
    Called once on startup.
    """
    if not os.path.exists(CSV_PATH):
        try:
            with open(CSV_PATH, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=HEADERS)
                writer.writeheader()
            log.info(f"Signal tracker CSV created at {CSV_PATH}")
        except Exception as e:
            log.error(f"Could not create signal tracker CSV: {e}")
    else:
        log.info(f"Signal tracker CSV found at {CSV_PATH} — appending to existing log.")


# =============================================================================
# LOG A SIGNAL
# =============================================================================

def log_signal(signal: dict):
    """
    Logs a fired signal to the CSV.
    Called by alert_manager.py every time an alert fires.

    Extracts all relevant data from the signal dict and
    writes one row to the CSV.
    """
    try:
        levels  = signal.get("levels", {})
        layers  = signal.get("layer_scores", [])

        # Build a lookup by layer name for easy access
        layer_lookup = {r["layer"]: r for r in layers}

        def get_layer(name, field, default=""):
            layer = layer_lookup.get(name, {})
            if field == "reason":
                reasons = layer.get("reasons", [])
                # Clean the first reason — strip to 100 chars max
                return reasons[0][:100] if reasons else ""
            return layer.get(field, default)

        row = {
            # Signal info
            "timestamp":     signal.get("timestamp", str(datetime.now()))[:19],
            "symbol":        signal.get("symbol", ""),
            "direction":     signal.get("direction", ""),
            "score":         signal.get("score", 0),
            "tier":          signal.get("tier", ""),
            "regime":        signal.get("regime", ""),

            # Levels
            "entry":         levels.get("entry", ""),
            "stop":          levels.get("stop", ""),
            "tp1":           levels.get("tp1", ""),
            "tp2":           levels.get("tp2", ""),
            "tp3":           levels.get("tp3", ""),
            "r_pct":         levels.get("r_pct", ""),

            # Layer scores
            "l1_score":      get_layer("L1_structure",  "score", 0),
            "l2_score":      get_layer("L2_order_flow", "score", 0),
            "l3_score":      get_layer("L3_zones",      "score", 0),
            "l4_score":      get_layer("L4_macro",      "score", 0),
            "l5_score":      get_layer("L5_momentum",   "score", 0),
            "l6_score":      get_layer("L6_sentiment",  "score", 0),

            # Layer directions
            "l1_direction":  get_layer("L1_structure",  "direction", ""),
            "l2_direction":  get_layer("L2_order_flow", "direction", ""),
            "l3_direction":  get_layer("L3_zones",      "direction", ""),
            "l4_direction":  get_layer("L4_macro",      "direction", ""),
            "l5_direction":  get_layer("L5_momentum",   "direction", ""),
            "l6_direction":  get_layer("L6_sentiment",  "direction", ""),

            # Top reason from each layer
            "l1_reason":     get_layer("L1_structure",  "reason"),
            "l2_reason":     get_layer("L2_order_flow", "reason"),
            "l3_reason":     get_layer("L3_zones",      "reason"),
            "l4_reason":     get_layer("L4_macro",      "reason"),
            "l5_reason":     get_layer("L5_momentum",   "reason"),
            "l6_reason":     get_layer("L6_sentiment",  "reason"),

            # Outcome — blank until you fill it in
            "outcome":       "OPEN",
            "outcome_price": "",
            "outcome_notes": "",
        }

        with open(CSV_PATH, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=HEADERS)
            writer.writerow(row)

        log.info(f"Signal logged to CSV: {row['symbol']} {row['direction']} "
                 f"score:{row['score']} @ {row['entry']}")

    except Exception as e:
        log.error(f"Failed to log signal to CSV: {e}")


# =============================================================================
# GET SIGNAL HISTORY
# =============================================================================

def get_all_signals() -> list:
    """
    Returns all logged signals as a list of dicts.
    Useful for the daily summary and performance analysis.
    """
    if not os.path.exists(CSV_PATH):
        return []
    try:
        with open(CSV_PATH, "r") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception as e:
        log.error(f"Failed to read signal CSV: {e}")
        return []


def get_todays_signals() -> list:
    """Returns only signals from today."""
    today  = datetime.now().strftime("%Y-%m-%d")
    all_s  = get_all_signals()
    return [s for s in all_s if s.get("timestamp", "").startswith(today)]


def get_open_signals() -> list:
    """Returns all signals with outcome = OPEN."""
    all_s = get_all_signals()
    return [s for s in all_s if s.get("outcome") == "OPEN"]


# =============================================================================
# DAILY SUMMARY
# =============================================================================

def get_daily_summary() -> str:
    """
    Generates a daily summary message for Telegram.
    Shows all signals that fired today with their current outcome.

    Called by main.py once per day (e.g. at midnight UTC).
    """
    signals = get_todays_signals()
    all_signals = get_all_signals()

    if not signals:
        return "📊 *Daily Signal Summary*\nNo signals fired today."

    lines = [
        "📊 *Daily Signal Summary*",
        f"_{datetime.now().strftime('%B %d, %Y')}_",
        "",
        f"Signals today: *{len(signals)}*",
        f"Total logged: *{len(all_signals)}*",
        "",
    ]

    for s in signals:
        direction = s.get("direction", "").upper()
        symbol    = s.get("symbol", "")
        score     = s.get("score", "")
        outcome   = s.get("outcome", "OPEN")
        entry     = s.get("entry", "")
        time_str  = s.get("timestamp", "")[-8:-3]  # HH:MM

        # Outcome emoji
        outcome_emoji = {
            "TP1_HIT": "✅",
            "TP2_HIT": "✅✅",
            "TP3_HIT": "✅✅✅",
            "SL_HIT":  "❌",
            "OPEN":    "🔵",
            "MISSED":  "⏭️",
        }.get(outcome, "🔵")

        lines.append(
            f"{outcome_emoji} {direction} {symbol} | "
            f"Score: {score} | Entry: {entry} | {time_str} UTC"
        )

    # Performance stats if we have outcomes
    closed = [s for s in all_signals if s.get("outcome") not in ["OPEN", "MISSED", ""]]
    if closed:
        wins  = [s for s in closed if "TP" in s.get("outcome", "")]
        losses = [s for s in closed if s.get("outcome") == "SL_HIT"]
        win_rate = len(wins) / len(closed) * 100 if closed else 0
        lines += [
            "",
            "─────────────────",
            f"*All-time performance*",
            f"Closed signals: {len(closed)}",
            f"Winners: {len(wins)} | Losers: {len(losses)}",
            f"Win rate: {win_rate:.0f}%",
        ]

    lines.append("")
    lines.append("_Update outcomes in signals.csv on Railway_")

    return "\n".join(lines)


# =============================================================================
# STATS SUMMARY
# =============================================================================

def get_stats() -> dict:
    """
    Returns performance stats across all logged signals.
    Used for tuning layer weights over time.
    """
    all_signals = get_all_signals()
    closed      = [s for s in all_signals
                   if s.get("outcome") not in ["OPEN", "MISSED", ""]]

    if not closed:
        return {"message": "No closed signals yet — keep running the bot."}

    wins   = [s for s in closed if "TP"       in s.get("outcome", "")]
    losses = [s for s in closed if "SL_HIT"   == s.get("outcome", "")]

    # Win rate by symbol
    symbols = list(set(s["symbol"] for s in closed))
    by_symbol = {}
    for sym in symbols:
        sym_closed = [s for s in closed if s["symbol"] == sym]
        sym_wins   = [s for s in sym_closed if "TP" in s.get("outcome", "")]
        by_symbol[sym] = {
            "trades":   len(sym_closed),
            "wins":     len(sym_wins),
            "win_rate": round(len(sym_wins) / len(sym_closed) * 100, 1)
        }

    # Win rate by regime
    regimes = list(set(s["regime"] for s in closed))
    by_regime = {}
    for reg in regimes:
        reg_closed = [s for s in closed if s["regime"] == reg]
        reg_wins   = [s for s in reg_closed if "TP" in s.get("outcome", "")]
        by_regime[reg] = {
            "trades":   len(reg_closed),
            "wins":     len(reg_wins),
            "win_rate": round(len(reg_wins) / len(reg_closed) * 100, 1)
        }

    return {
        "total_signals":  len(all_signals),
        "closed":         len(closed),
        "open":           len([s for s in all_signals if s.get("outcome") == "OPEN"]),
        "wins":           len(wins),
        "losses":         len(losses),
        "win_rate":       round(len(wins) / len(closed) * 100, 1),
        "by_symbol":      by_symbol,
        "by_regime":      by_regime,
    }
