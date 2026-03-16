# =============================================================================
# APEX SYSTEM — config.py
# =============================================================================
# This is the ONLY file you need to edit to configure the bot.
# Never modify the other files unless you know what you're doing.
# =============================================================================

import os

# -----------------------------------------------------------------------------
# TELEGRAM ALERTS
# -----------------------------------------------------------------------------
# These are loaded from Railway environment variables — never hardcode here
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# -----------------------------------------------------------------------------
# SYMBOLS TO MONITOR
# -----------------------------------------------------------------------------
FUTURES_SYMBOLS = []
CRYPTO_SYMBOLS  = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "AVAXUSDT", "XRPUSDT"]
# -----------------------------------------------------------------------------
# TIMEFRAMES
# -----------------------------------------------------------------------------
TIMEFRAMES = {
    "HTF": "1D",
    "MTF": "4H",
    "ITF": "1H",
    "LTF": "15m",
}

# Data source mode — "binance" or "yfinance"
DATA_SOURCE = "binance"

# -----------------------------------------------------------------------------
# SCORING THRESHOLDS
# -----------------------------------------------------------------------------
SCORE_THRESHOLD_STANDARD        = 65
SCORE_THRESHOLD_HIGH_CONVICTION = 80
SCORE_THRESHOLD_MAX_SIZE        = 90

# -----------------------------------------------------------------------------
# LAYER WEIGHTS (must sum to 100)
# -----------------------------------------------------------------------------
LAYER_WEIGHTS = {
    "L1_structure":  20,
    "L2_order_flow": 20,
    "L3_zones":      15,
    "L4_macro":      15,
    "L5_momentum":   15,
    "L6_sentiment":  15,
}
assert sum(LAYER_WEIGHTS.values()) == 100, \
    f"Layer weights must sum to 100. Currently: {sum(LAYER_WEIGHTS.values())}"

# -----------------------------------------------------------------------------
# RISK PARAMETERS
# -----------------------------------------------------------------------------
ATR_STOP_MULTIPLIER = 1.8
ATR_PERIOD          = 14
TP1_R               = 1.1
TP2_R               = 2.2
TP3_R               = 4.1
MAX_POSITION_PCT    = 0.02
KELLY_FRACTION      = 0.25

# -----------------------------------------------------------------------------
# ORDER FLOW SETTINGS
# -----------------------------------------------------------------------------
CVD_LOOKBACK              = 20
CVD_DIVERGENCE_THRESHOLD  = 0.015
WS_RECONNECT_SECONDS      = 30

# -----------------------------------------------------------------------------
# MACRO SETTINGS
# -----------------------------------------------------------------------------
VIX_RISK_OFF_THRESHOLD = 25.0
DXY_MOMENTUM_PERIOD    = 10

# -----------------------------------------------------------------------------
# MOMENTUM SETTINGS
# -----------------------------------------------------------------------------
EMA_FAST   = 9
EMA_MID    = 21
EMA_SLOW   = 50
EMA_ANCHOR = 200

RSI_PERIOD     = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD   = 30

MACD_FAST   = 12
MACD_SLOW   = 26
MACD_SIGNAL = 9

TF_ALIGNMENT_MIN = 3

# -----------------------------------------------------------------------------
# SENTIMENT SETTINGS
# -----------------------------------------------------------------------------
FUNDING_EXTREME_LONG  =  0.05
FUNDING_EXTREME_SHORT = -0.03
PCR_EXTREME_HIGH      =  1.3
PCR_EXTREME_LOW       =  0.6
COT_EXTREME_PCT       =  0.65

# -----------------------------------------------------------------------------
# BOT BEHAVIOR
# -----------------------------------------------------------------------------
SCAN_INTERVAL_SECONDS      = 60
MIN_ALERT_COOLDOWN_MINUTES = 30
DEBUG_MODE                 = True
DRY_RUN                    = False
LOG_FILE                   = "apex_bot.log"
