# =============================================================================
# APEX SYSTEM — alert_manager.py
# =============================================================================
# Formats and sends trade signals to Telegram.
#
# What this does:
#   - Formats the signal dict into a clean Telegram message
#   - Sends the alert via Telegram Bot API
#   - Tracks cooldowns per symbol (no spam)
#   - Logs all alerts to file
# =============================================================================

import time
import logging
import requests

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    MIN_ALERT_COOLDOWN_MINUTES,
    DRY_RUN,
)
from signal_tracker import log_signal

log = logging.getLogger("alert_manager")

# =============================================================================
# COOLDOWN TRACKER
# =============================================================================

class CooldownTracker:
    """
    Prevents alert spam by enforcing a minimum time
    between alerts for the same symbol.
    """

    def __init__(self):
        self._last_alert = {}   # { symbol: timestamp }

    def can_alert(self, symbol: str) -> bool:
        """Returns True if enough time has passed since last alert."""
        last = self._last_alert.get(symbol, 0)
        elapsed_minutes = (time.time() - last) / 60
        return elapsed_minutes >= MIN_ALERT_COOLDOWN_MINUTES

    def record_alert(self, symbol: str):
        """Records that an alert was just sent for this symbol."""
        self._last_alert[symbol] = time.time()

    def time_until_next(self, symbol: str) -> float:
        """Returns minutes until next alert is allowed."""
        last    = self._last_alert.get(symbol, 0)
        elapsed = (time.time() - last) / 60
        return max(0.0, MIN_ALERT_COOLDOWN_MINUTES - elapsed)


# =============================================================================
# MESSAGE FORMATTER
# =============================================================================

def format_signal(signal: dict) -> str:
    """
    Formats a signal dict into a clean Telegram message.

    Example output:
    ⚡ LONG | BTCUSDT | HIGH CONVICTION

    Score: 82/100
    Regime: TREND MODE
    Entry:  84,250.00
    Stop:   83,180.00  (1.27% | 1,070 pts)
    TP1:    85,427.00  (1.1R)
    TP2:    86,604.00  (2.2R)
    TP3:    88,639.00  (4.1R)
    Size:   1.5% of account

    Signals firing:
    L1 ✅ HTF bullish structure confirmed
    L2 ✅ Bullish CVD divergence detected
    L3 ✅ Price at unmitigated bullish OB
    L4 ✅ Low vol trending conditions
    L5 ✅ Bullish EMA stack 4/4 TFs
    L6 ✅ Extreme negative funding
    """
    emoji     = signal.get("emoji", "✅")
    direction = signal.get("direction", "").upper()
    symbol    = signal.get("symbol", "")
    score     = signal.get("score", 0)
    tier_desc = signal.get("tier_desc", "")
    regime    = signal.get("regime", "trend").upper().replace("_", " ")
    levels    = signal.get("levels", {})
    sizing    = signal.get("sizing", {})
    layers    = signal.get("layer_scores", [])

    entry  = levels.get("entry",  0)
    stop   = levels.get("stop",   0)
    tp1    = levels.get("tp1",    0)
    tp2    = levels.get("tp2",    0)
    tp3    = levels.get("tp3",    0)
    r      = levels.get("r",      0)
    r_pct  = levels.get("r_pct",  0)

    size_pct = sizing.get("size_pct", 0)

    # Header
    lines = [
        f"{emoji} *{direction} | {symbol}*",
        f"_{tier_desc}_",
        f"",
        f"*Score:* {score}/100",
        f"*Regime:* {regime} MODE",
        f"",
        f"*Entry:*  `{entry:,.2f}`",
        f"*Stop:*   `{stop:,.2f}`  ({r_pct:.2f}% | {r:,.0f} pts)",
        f"*TP1:*    `{tp1:,.2f}`  ({TP1_R_label()})",
        f"*TP2:*    `{tp2:,.2f}`  ({TP2_R_label()})",
        f"*TP3:*    `{tp3:,.2f}`  ({TP3_R_label()})",
        f"*Size:*   {size_pct}% of account",
        f"",
        f"*Signals firing:*",
    ]

    # Layer breakdown
    layer_icons = {
        "L1_structure":  "L1",
        "L2_order_flow": "L2",
        "L3_zones":      "L3",
        "L4_macro":      "L4",
        "L5_momentum":   "L5",
        "L6_sentiment":  "L6",
    }

    for layer in layers:
        name    = layer.get("layer", "")
        lscore  = layer.get("score", 0)
        lmax    = layer.get("max", 0)
        reasons = layer.get("reasons", [])
        label   = layer_icons.get(name, name)
        icon    = "✅" if lscore >= lmax * 0.5 else "⬜"
        reason  = reasons[0][:60] if reasons else "No signal"
        lines.append(f"{icon} *{label}* ({lscore}/{lmax}) {reason}")

    # Footer
    ts = signal.get("timestamp", "")[:19]
    lines.append(f"")
    lines.append(f"_{ts} UTC_")

    return "\n".join(lines)


def TP1_R_label():
    from config import TP1_R
    return f"{TP1_R}R — take 40%"

def TP2_R_label():
    from config import TP2_R
    return f"{TP2_R}R — take 40%"

def TP3_R_label():
    from config import TP3_R
    return f"{TP3_R}R — trail 20%"


# =============================================================================
# TELEGRAM SENDER
# =============================================================================

def send_telegram(message: str) -> bool:
    """
    Sends a message via Telegram Bot API.
    Returns True if successful, False if failed.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("Telegram credentials not set — check Railway variables")
        return False

    url     = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       message,
        "parse_mode": "Markdown",
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        log.info("Telegram alert sent successfully.")
        return True
    except Exception as e:
        log.error(f"Telegram send failed: {e}")
        return False


# =============================================================================
# MAIN ALERT FUNCTION
# =============================================================================

# Global cooldown tracker
_cooldown = CooldownTracker()


def send_alert(signal: dict) -> bool:
    """
    Main entry point — called by main.py when a signal fires.

    Checks cooldown, formats message, sends to Telegram.
    In DRY_RUN mode, prints to console instead of sending.

    Returns True if alert was sent.
    """
    symbol = signal.get("symbol", "UNKNOWN")

    # Check cooldown
    if not _cooldown.can_alert(symbol):
        mins = _cooldown.time_until_next(symbol)
        log.info(f"{symbol} on cooldown — {mins:.0f} min until next alert")
        return False

    # Format message
    message = format_signal(signal)

    if DRY_RUN:
        # Print to console instead of sending
        log.info(f"DRY RUN — alert NOT sent to Telegram:")
        print("\n" + "="*60)
        print(message)
        print("="*60 + "\n")
        _cooldown.record_alert(symbol)
        return True
    else:
        # Send for real
        sent = send_telegram(message)
        if sent:
            _cooldown.record_alert(symbol)
        return sent


def send_startup_message():
    """
    Sends a startup notification to Telegram
    so you know the bot is live.
    """
    message = (
        "🤖 *APEX Bot Online*\n"
        "All 6 layers loaded and scanning.\n"
        f"_DRY RUN: {DRY_RUN}_"
    )

    if DRY_RUN:
        print("\nDRY RUN — startup message:")
        print(message)
    else:
        send_telegram(message)


def send_error_alert(error: str):
    """Sends an error notification to Telegram."""
    message = f"⚠️ *APEX Bot Error*\n`{error[:200]}`"
    if not DRY_RUN:
        send_telegram(message)
    log.error(f"Error alert: {error}")
