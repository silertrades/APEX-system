# APEX Bot — Full Context Document
**SilerTrades · A Division of 96 Bulls Financial Group**

Paste this file at the start of any new conversation to give Claude
full context on the system. Updated every session.

---

## What This System Is

APEX (Adaptive Predictive Edge Execution) is a 6-layer crypto trading
signal bot. It scans 6 cryptocurrency pairs every 60 seconds, scores
market conditions across 6 independent signal engines, and fires
Telegram alerts when confluence score reaches 65+.

Built in Python. Deployed on Railway. Data from Binance. Alerts via Telegram.
Code stored on GitHub (private repo: apex-bot).

---

## Tech Stack

| Component | Technology | Notes |
|-----------|-----------|-------|
| Language | Python 3.13 | |
| Hosting | Railway.app | ~$6-10/month, auto-deploys from GitHub |
| OHLCV data | Binance REST API | Free, real-time, no delay |
| Order flow | Binance WebSocket | Live aggTrade stream, CVD calculation |
| Macro data | yfinance | VIX, DXY, yield curve — falls back to proxies |
| Alerts | Telegram Bot API | Instant push to phone |
| Code storage | GitHub | Private repo: apex-bot |
| Signal logging | CSV file | /app/signals.csv on Railway |

---

## File Structure

apex-bot/
├── config.py           — ALL settings (symbols, thresholds, weights)
├── data_feed.py        — All data ingestion (Binance REST + WebSocket)
├── l1_structure.py     — Layer 1: Market structure (BOS, CHoCH, HTF bias)
├── l2_order_flow.py    — Layer 2: CVD divergence, volume analysis
├── l3_zones.py         — Layer 3: Order blocks, FVGs, liquidity pools
├── l4_macro.py         — Layer 4: VIX, DXY, yield curve, regime classifier
├── l5_momentum.py      — Layer 5: EMA stack, RSI, MACD, squeeze
├── l6_sentiment.py     — Layer 6: Funding rates, OI, fear/greed
├── scoring_engine.py   — Combines all 6 layers into 0-100 score
├── alert_manager.py    — Formats and sends Telegram alerts
├── signal_tracker.py   — Logs signals to CSV, auto-tracks outcomes
├── backtest.py         — Historical backtesting engine
├── main.py             — Main loop (runs everything)
├── requirements.txt    — Python dependencies
├── Procfile            — Railway start command
├── CONTEXT.md          — This file
├── ROADMAP.md          — Known issues and planned upgrades
├── HOWTO.md            — How to use and maintain the bot
└── CLIFFNOTES.md       — Plain English system summary

---

## The 6 Layers

### L1 — Market Structure (max 20 pts)
Detects HTF trend bias using swing highs/lows. Identifies BOS (Break of
Structure — trend continuation) and CHoCH (Change of Character — earliest
reversal signal). Swing lookback = 8 candles, minimum swing size = 0.8%.
BOS requires candle close beyond level (not just wick).

### L2 — Order Flow (max 20 pts)
Live Binance WebSocket aggregated trade stream. Builds Cumulative Volume
Delta (CVD) in real time. Detects CVD divergence from price (institutional
footprint). Also scores volume delta bias, absorption, and price/volume
divergence.

### L3 — Institutional Zones (max 15 pts)
Maps Order Blocks (last opposing candle before impulse move), Fair Value
Gaps (price inefficiencies that act as magnets), and Liquidity Pools
(equal highs/lows where stops cluster). Scores proximity to unmitigated
zones and detects liquidity sweeps.

### L4 — Macro + Vol Regime (max 15 pts)
Real VIX via yfinance (^VIX) — falls back to BTC realized vol proxy.
Real DXY via yfinance (DX-Y.NYB) — falls back to inverse BTC momentum.
Real yield curve via yfinance (^TNX minus ^FVX) — falls back to approximation.
Trending threshold: 0.45 efficiency (lowered from 0.6 based on backtest).
Sets overall trade mode: trend / mean_reversion / breakout / avoid.

### L5 — Multi-TF Momentum (max 15 pts)
EMA stack alignment (9/21/50/200) across 4 timeframes (15m/1H/4H/Daily).
RSI hidden divergence (trend continuation signal).
MACD histogram compression + expansion detection.
Bollinger/Keltner channel squeeze firing detection.

### L6 — Sentiment + Positioning (max 15 pts)
Binance perpetual funding rates — extremes signal overcrowded positioning.
Open interest vs price analysis — reveals smart money intent.
Proprietary Fear/Greed proxy from price momentum + vol + volume.
Long/short ratio estimation from funding rate.

---

## Scoring System

Each layer returns a score. All combine into weighted 0-100 total.

### Layer Weights (must sum to 100)
- L1 Market Structure:  20
- L2 Order Flow:        20
- L3 Zones:             15
- L4 Macro:             15
- L5 Momentum:          15
- L6 Sentiment:         15

### Signal Tiers
- Score 65-79:  Standard alert — normal position size
- Score 80-89:  High conviction — 1.5x position size
- Score 90+:    Maximum size — rare, career-defining setup
- Below 65:     Bot stays silent

### Direction Consensus
Direction determined by weighted vote across all layers.
Requires 60%+ weighted agreement to fire a signal.
Mixed signals = no alert regardless of total score.

---

## Active Symbols

CRYPTO_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT",
                  "BNBUSDT", "AVAXUSDT", "XRPUSDT"]
FUTURES_SYMBOLS = []   # Disabled — awaiting Databento integration

---

## Timeframes

| Label | Timeframe | Purpose |
|-------|-----------|---------|
| HTF | Daily (1D) | Trend bias, structure |
| MTF | 4 Hour (4H) | Zone identification, scoring |
| ITF | 1 Hour (1H) | Entry confirmation |
| LTF | 15 Minute (15m) | Trigger, order flow |

---

## Trade Levels

- Entry: Current price at signal fire
- Stop: ATR x 1.8 below/above entry
- TP1: 1.1R (take 40% off)
- TP2: 2.2R (take 40% off)
- TP3: 4.1R (trail remaining 20%)

---

## Signal Tracking

Every signal logged to /app/signals.csv on Railway.
Bot automatically detects when price hits TP1, TP2, TP3, or SL.
Fires Telegram notification at each level hit.

Outcome strings:
- TP3_HIT        — all targets hit
- TP2_THEN_SL    — hit TP1+TP2, stopped out on remainder
- TP1_THEN_SL    — hit TP1, stopped out on remainder
- TP2_HIT        — hit TP1+TP2, still open
- TP1_HIT        — hit TP1 only, still open
- SL_HIT         — stopped out immediately
- OPEN           — signal active, no levels hit yet

To download CSV: Railway dashboard → service → Files tab → /app/signals.csv

---

## Railway Environment Variables

| Variable | Value | Notes |
|----------|-------|-------|
| TELEGRAM_BOT_TOKEN | your token | Never commit to GitHub |
| TELEGRAM_CHAT_ID | your chat id | Never commit to GitHub |

---

## Backtest Results (March 16 2026)

Run with threshold 25 (live threshold is 65).
Note: L2 CVD and L6 funding rate = 0 in backtest (no live feeds).
Scores are lower than live system would produce.

| Metric | Value |
|--------|-------|
| Period | 1 year |
| Total signals | 374 |
| Win rate | 44.9% |
| Avg R per trade | +0.21R |
| Avg max R reached | 1.67R |
| Best symbol | BNB (55.8% win, +0.67R) |
| Best regime | Trend (69.2% win) |
| Worst symbol | BTC (36.5% win, -0.12R) |

Key finding: Trend regime wins 69.2% vs mean-reversion 44.0%.
Regime classifier tuned as a result (threshold 0.6 to 0.45).

---

## Known Issues

1. VIX falling back to BTC proxy on Railway EU server
2. Futures symbols disabled — no data source yet
3. Layer weights not tuned against real outcomes yet
4. Daily summary not yet verified in production
5. BTC underperforms other symbols in backtest

Full details in ROADMAP.md.

---

## How to Start a New Dev Session

Paste this entire file at the start of the conversation, then say
what you want to build or fix. Claude will have full context.

If editing a specific file, also paste the current contents of
that file from GitHub so Claude can see the exact current state.

---

## Session Log

| Date | Work Done |
|------|-----------|
| Mar 15 2026 | Full system built and deployed. All 6 layers, scoring engine, alert manager, signal tracker, main loop. Live on Railway with Telegram alerts. |
| Mar 15 2026 | Professional brochure created for SilerTrades / 96 Bulls Financial Group. |
| Mar 15 2026 | Full system walkthrough — all components explained in plain English. |
| Mar 16 2026 | Added SOL, BNB, AVAX, XRP symbols. Built auto outcome tracking in signal_tracker.py. |
| Mar 16 2026 | Built and ran backtest engine. 374 signals, 44.9% win rate, +0.21R avg. |
| Mar 16 2026 | Fixed regime classifier (0.6 to 0.45), L1 structure detection, connected real macro data via yfinance. |
| Mar 16 2026 | Created CONTEXT.md, ROADMAP.md, HOWTO.md, CLIFFNOTES.md documentation. |

---

## Next Session Priorities

1. Web dashboard — live scores, signal history, win rate by symbol
2. Score-building alert — Telegram notification when symbol hits 50+
3. RUN_MODE environment variable — switch backtest/live without touching Procfile
4. Futures data — Databento integration with trading partner
5. Tune layer weights after 30+ live signals collected

---

Last updated: March 16 2026
SilerTrades · A Division of 96 Bulls Financial Group
