# =============================================================================
# APEX SYSTEM — main.py
# =============================================================================
# The main loop. Runs continuously, scanning all symbols
# every SCAN_INTERVAL_SECONDS and firing alerts when
# the scoring engine finds a high-probability setup.
# Also runs the web dashboard in a background thread.
# =============================================================================

import time
import logging
import threading
import pandas as pd

from data_feed      import DataManager
from scoring_engine import run as score_symbol
from alert_manager  import (send_alert, send_startup_message,
                             send_error_alert, send_telegram,
                             send_building_alert)
from signal_tracker import ensure_csv_exists, get_daily_summary, check_open_signals
from dashboard      import start_dashboard, update_scores

from config import (
    CRYPTO_SYMBOLS,
    FUTURES_SYMBOLS,
    SCAN_INTERVAL_SECONDS,
    DEBUG_MODE,
    DRY_RUN,
    LAYER_WEIGHTS,
)

logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("main")

ALL_SYMBOLS = CRYPTO_SYMBOLS + FUTURES_SYMBOLS


def build_score_update(symbol: str, signal_result, data: dict) -> dict:
    """
    Builds the score dict for the dashboard from a scoring result.
    Works whether a signal fired or not — always updates dashboard.
    """
    candles = data.get("candles", {})
    layers  = []
    score   = 0
    direction = "neutral"
    regime    = "neutral"

    if signal_result:
        layers    = signal_result.get("layer_scores", [])
        score     = signal_result.get("score", 0)
        direction = signal_result.get("direction", "neutral")
        regime    = signal_result.get("regime", "neutral")
    else:
        try:
            import l1_structure, l2_order_flow, l3_zones
            import l4_macro, l5_momentum, l6_sentiment
            from scoring_engine import get_direction_consensus, get_trade_regime

            for layer_fn in [l1_structure, l2_order_flow, l3_zones,
                             l4_macro, l5_momentum, l6_sentiment]:
                try:
                    layers.append(layer_fn.score(data))
                except Exception as e:
                    log.debug(f"Layer error for dashboard: {e}")

            total = 0.0
            for r in layers:
                w = LAYER_WEIGHTS.get(r["layer"], 10)
                total += (r["score"] / r["max"] * 100) * (w / 100) \
                         if r["max"] > 0 else 0
            score     = round(min(100.0, total), 1)
            consensus = get_direction_consensus(layers)
            direction = consensus["direction"]
            regime    = get_trade_regime(layers)

        except Exception as e:
            log.debug(f"Dashboard score build failed: {e}")

    # Build layer dict for dashboard
    layer_dict = {}
    for r in layers:
        layer_dict[r["layer"]] = {
            "score":     r.get("score", 0),
            "max":       r.get("max", 0),
            "direction": r.get("direction", "neutral"),
        }

    return {
        "score":     score,
        "direction": direction,
        "regime":    regime,
        "layers":    layer_dict,
    }


def scan_symbol(dm: DataManager, symbol: str,
                current_prices: dict, dashboard_scores: dict):
    """
    Runs the full APEX pipeline for one symbol.
    Fetches data → scores all 6 layers → fires alert if threshold met.
    Updates dashboard scores and current prices.
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

        # 4. Update dashboard scores FIRST so building alert can read them
        dashboard_scores[symbol] = build_score_update(symbol, signal, data)

        # 5. Fire alert if signal exists
        if signal:
            log.info(
                f"SIGNAL: {symbol} | {signal['direction'].upper()} | "
                f"Score: {signal['score']} | Tier: {signal['tier']}"
            )
            send_alert(signal)

        # 6. Fire building alert if score is 50+ but below threshold
        elif dashboard_scores.get(symbol):
            sym_score     = dashboard_scores[symbol].get("score", 0)
            sym_direction = dashboard_scores[symbol].get("direction", "neutral")
            sym_layers    = dashboard_scores[symbol].get("layers", {})

            # Convert layers dict to list format for alert
            layer_list = [
                {"layer": k, "score": v["score"], "max": v["max"]}
                for k, v in sym_layers.items()
            ]

            if sym_score >= 50 and sym_direction != "neutral":
                send_building_alert(
                    symbol, sym_score, sym_direction, layer_list)

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

    # Start dashboard in background thread
    dashboard_thread = threading.Thread(
        target=start_dashboard,
        daemon=True,
        name="dashboard"
    )
    dashboard_thread.start()
    log.info("Dashboard started in background thread.")

    # Initialize signal tracker
    ensure_csv_exists()

    # Initialize data manager
    dm = DataManager()

    # Give WebSockets time to connect
    log.info("Waiting 10s for WebSocket connections to stabilize...")
    time.sleep(10)

    # Send startup notification
    send_startup_message()

    scan_count = 0

    while True:
        scan_count += 1
        log.info(f"--- Scan #{scan_count} | {len(ALL_SYMBOLS)} symbols ---")

        current_prices   = {}
        dashboard_scores = {}

        for symbol in ALL_SYMBOLS:
            scan_symbol(dm, symbol, current_prices, dashboard_scores)
            time.sleep(2)

        # Update dashboard with all latest scores
        if dashboard_scores:
            update_scores(dashboard_scores)

        # Check open signals against current prices
        check_open_signals(current_prices)

        # Send daily summary at midnight UTC
        if scan_count % 1440 == 0:
            summary = get_daily_summary()
            send_telegram(summary)

        log.info(
            f"Scan #{scan_count} complete. "
            f"Next scan in {SCAN_INTERVAL_SECONDS}s..."
        )
        time.sleep(SCAN_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
