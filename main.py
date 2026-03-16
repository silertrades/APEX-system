# =============================================================================
# APEX SYSTEM — main.py
# =============================================================================
# The main loop. Runs continuously, scanning all symbols
# every SCAN_INTERVAL_SECONDS and firing alerts when
# the scoring engine finds a high-probability setup.
# =============================================================================

import time
import logging
from data_feed      import DataManager
from scoring_engine import run as score_symbol
from alert_manager  import send_alert, send_startup_message, send_error_alert, send_telegram
from signal_tracker import ensure_csv_exists, get_daily_summary, check_open_signals
import pandas as pd

from config import (
    CRYPTO_SYMBOLS,
    FUTURES_SYMBOLS,
    SCAN_INTERVAL_SECONDS,
    DEBUG_MODE,
    DRY_RUN,
)

logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("main")

ALL_SYMBOLS = CRYPTO_SYMBOLS + FUTURES_SYMBOLS


def scan_symbol(dm: DataManager, symbol: str, current_prices: dict):
    """
    Runs the full APEX pipeline for one symbol.
    Fetches data → scores all 6 layers → fires alert if threshold met.
    Also updates current price in the prices dict for outcome tracking.
    """
    try:
        # 1. Fetch all data
        data = dm.get_all(symbol)

        # 2. Store current price for outcome tracker
        candles = data.get("candles", {})
        ltf_df  = candles.get("LTF", pd.DataFrame())
        if not ltf_df.empty:
            current_prices[symbol] = float(ltf_df["close"].iloc[-1])

        # 3. Run scoring engine
        signal = score_symbol(data)

        # 4. Fire alert if signal exists
        if signal:
            log.info(
                f"SIGNAL: {symbol} | {signal['direction'].upper()} | "
                f"Score: {signal['score']} | Tier: {signal['tier']}"
            )
            send_alert(signal)
        else:
            log.debug(f"{symbol} — no signal this scan")

    except Exception as e:
        log.error(f"Error scanning {symbol}: {e}")
        send_error_alert(f"Scan error on {symbol}: {e}")

def main():
    log.info("=" * 60)
    log.info("APEX BOT STARTING — ALL 6 LAYERS ACTIVE")
    log.info(f"DRY_RUN    : {DRY_RUN}")
    log.info(f"Symbols    : {ALL_SYMBOLS}")
    log.info(f"Scan every : {SCAN_INTERVAL_SECONDS}s")
    log.info("=" * 60)

    # Initialize data manager
    ensure_csv_exists()
    dm = DataManager()

    # Give WebSockets time to connect and
    # receive initial trade data for CVD
    log.info("Waiting 10s for WebSocket connections to stabilize...")
    time.sleep(10)

    # Send startup notification
    send_startup_message()

    scan_count = 0

    while True:
        scan_count += 1
        log.info(f"--- Scan #{scan_count} | {len(ALL_SYMBOLS)} symbols ---")

        # Track current prices for outcome monitoring
        current_prices = {}

        for symbol in ALL_SYMBOLS:
            scan_symbol(dm, symbol, current_prices)
            time.sleep(2)

        # Check open signals against current prices
        check_open_signals(current_prices)

        log.info(
            f"Scan #{scan_count} complete. "
            f"Next scan in {SCAN_INTERVAL_SECONDS}s..."
        )

        # Send daily summary at midnight UTC (scan #1440 = 24hrs at 60s intervals)
        if scan_count % 1440 == 0:
            summary = get_daily_summary()
            send_telegram_summary(summary)

        time.sleep(SCAN_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
