# =============================================================================
# APEX SYSTEM — main.py (startup test)
# =============================================================================
# Confirms data feed is working on Railway.
# Full scoring engine will be added once all layers are built.
# =============================================================================

import time
import logging
from data_feed import DataManager
from config import CRYPTO_SYMBOLS, FUTURES_SYMBOLS, DEBUG_MODE, DRY_RUN

logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("main")

def main():
    log.info("=" * 50)
    log.info("APEX BOT STARTING...")
    log.info(f"DRY_RUN = {DRY_RUN}")
    log.info(f"Crypto symbols: {CRYPTO_SYMBOLS}")
    log.info(f"Futures symbols: {FUTURES_SYMBOLS}")
    log.info("=" * 50)

    dm = DataManager()

    log.info("Waiting for WebSocket connections...")
    time.sleep(5)

    test_symbol = CRYPTO_SYMBOLS[0]
    log.info(f"Testing data feed for {test_symbol}...")

    data = dm.get_all(test_symbol)

    log.info(f"Timeframes loaded: {list(data['candles'].keys())}")
    for tf, df in data["candles"].items():
        if not df.empty:
            log.info(f"  {tf}: {len(df)} candles | last close: {df['close'].iloc[-1]:.2f}")

    log.info(f"VIX: {data['macro']['vix']:.1f}")
    log.info(f"CVD divergence: {data['cvd_divergence']['divergence']}")
    log.info(f"Funding rate: {data['sentiment']['funding_rate']*100:.4f}%")
    log.info("Data feed confirmed. Awaiting full layer build...")

    while True:
        time.sleep(60)
        log.info("Bot alive — awaiting scoring engine...")

if __name__ == "__main__":
    main()
