# =============================================================================
# APEX SYSTEM — run.py
# =============================================================================
# Entry point that checks RUN_MODE environment variable
# and launches either the live bot or the backtest engine.
#
# To switch modes — go to Railway → Variables → RUN_MODE
#   RUN_MODE=live      → runs main.py (default)
#   RUN_MODE=backtest  → runs backtest.py
#
# Never need to touch the Procfile again.
# =============================================================================

import os
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("run")

mode = os.getenv("RUN_MODE", "live").lower().strip()

log.info(f"RUN_MODE = {mode}")

if mode == "backtest":
    log.info("Starting APEX backtest engine...")
    from backtest import run_backtest
    run_backtest()
else:
    log.info("Starting APEX live bot...")
    from main import main
    main()
