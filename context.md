
# APEX Bot — Full Context Document
**SilerTrades · A Division of 96 Bulls Financial Group**

Paste this file at the start of any new conversation to give Claude
full context on the system. Updated every session.

---

## What This System Is

APEX (Adaptive Predictive Edge Execution) is a 6-layer crypto trading
signal bot. It scans 6 cryptocurrency pairs every 60 seconds, scores
market conditions across 6 independent signal engines, and fires
Telegram alerts when confluence score reaches the threshold.

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
| Macro data | yfinance | Real VIX, DXY, yield curve with fallbacks |
| Alerts | Telegram Bot API | Instant push to phone |
| Dashboard | Flask web app | Live scores, signal history, how-to guide |
| Code storage | GitHub | Private repo: apex-bot |
| Signal logging | CSV file | /app/signals.csv on Railway |

---

## File Structure

apex-bot/
├── run.py              — Entry point (checks RUN_MODE, starts bot or backtest)
├── main.py             — Live bot loop
├── config.py           — ALL settings (symbols, thresholds, weights)
├── data_feed.py        — All data ingestion (Binance REST + WebSocket)
├── l1_structure.py     — Layer 1: Market structure (BOS, CHoCH, HTF bias)
├── l2_order_flow.py    — Layer 2: CVD divergence, volume analysis
├── l3_zones.py         — Layer 3: Order blocks, FVGs, liquidity pools
├── l4_macro.py         — Layer 4: VIX, DXY, yield curve, regime classifier
├── l5_momentum.py      — Layer 5: EMA stack, RSI, MACD, squeeze
├── l6_sentiment.py     — Layer 6: Funding rates, OI, fear/greed
├── scoring_engine.py   — Combines all 6 layers, applies filters
├── alert_manager.py    — Formats and sends Telegram alerts
├── signal_tracker.py   — Logs signals to CSV, auto-tracks outcomes
├── backtest.py         — Historical backtesting engine
├── dashboard.py        — Flask web dashboard
├── requirements.txt    — Python dependencies
├── Procfile            — Railway start command (web: python run.py)
├── CONTEXT.md          — This file
├── ROADMAP.md          — Known issues and planned upgrades
├── HOWTO.md            — How to use and maintain the bot
└── CLIFFNOTES.md       — Plain English system summary

---

## Switching Between Live and Backtest

Go to Railway → Variables → RUN_MODE
- RUN_MODE=live      → runs main.py (live bot)
- RUN_MODE=backtest  → runs backtest.py (historical test)
Never touch the Procfile.

---

## The 6 Layers

### L1 — Market Structure (max 20 pts)
Graduated scoring based on swing structure quality.
Uses vote-based system — counts bullish vs bearish swing comparisons.
Swing lookback = 6, minimum swing size = 0.5%.
BOS awards 6pts (full) or 3pts (approaching within 0.5%).
MTF agreement uses 60% threshold across 4 timeframes.
Confluence bonus +2 if BOS + CHoCH both fire.

### L2 — Order Flow (max 20 pts)
Live Binance WebSocket aggregated trade stream.
Builds CVD in real time. Detects divergence from price.
Also scores volume delta bias, absorption, price/volume divergence.

### L3 — Institutional Zones (max 15 pts)
Lookback increased to 75 candles for more zone discovery.
Proximity scoring widened — 3% now scores points (was 0.5%).
Checks MTF and HTF zones for confluence bonus.
Inside zone = full points. Tolerance increased to 0.3%.

### L4 — Macro + Vol Regime (max 15 pts)
Real VIX via yfinance (^VIX) — falls back to BTC realized vol.
Real DXY via yfinance (DX-Y.NYB) — falls back to inverse BTC momentum.
Real yield curve via yfinance (^TNX minus ^FVX).
Trending threshold: 0.45 efficiency (lowered from 0.6).
Sets trade mode: trend / mean_reversion / breakout / avoid.

### L5 — Multi-TF Momentum (max 15 pts)
EMA stack: 4pts for 4/4, 4pts for 3/4, 2pts for 2/4 alignment.
RSI trending-aware: overbought in trend = +2pts (not penalty).
Regime detected from price efficiency (matches L4 method).
MACD max 2pts. Squeeze max 2pts.

### L6 — Sentiment + Positioning (max 15 pts)
Binance perpetual funding rates — extremes signal crowding.
Open interest vs price analysis.
Proprietary Fear/Greed proxy from price momentum + vol + volume.
Long/short ratio estimation from funding rate.

---

## Scoring System

### Layer Weights (must sum to 100)
- L1 Market Structure:  20
- L2 Order Flow:        20
- L3 Zones:             15
- L4 Macro:             15
- L5 Momentum:          15
- L6 Sentiment:         15

### Signal Filters (data-driven from backtest)
1. Long signals only — backtest showed 53.6% win rate vs 47.7% shorts
2. Symbol thresholds:
   - BTCUSDT: 75 (underperforms at lower scores)
   - All others: 65
3. Regime thresholds:
   - trend: 65
   - mean_reversion: 75 (less reliable, higher bar)
   - breakout: 65
   - avoid: never fire

### Signal Tiers
- Score 65-79:  Standard alert — normal position size
- Score 80-89:  High conviction — 1.5x position size
- Score 90+:    Maximum size — rare, career-defining setup
- Score 50-64:  Building alert — heads up on Telegram, watch this symbol

### Direction Consensus
Requires 60%+ weighted agreement across all layers.
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
- Stop: ATR x 1.8 below entry
- TP1: 1.1R — take 40% off
- TP2: 2.2R — take 40% off
- TP3: 4.1R — trail remaining 20%
- Move stop to breakeven after TP1 hit

---

## Signal Tracking

Every signal logged to /app/signals.csv on Railway.
Bot automatically detects TP1, TP2, TP3, SL hits.
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

## Dashboard

URL: worker-production-ee74.up.railway.app
Username: apex
Password: set in Railway environment variable DASHBOARD_PASSWORD

Features:
- Live scores for all 6 symbols with layer bars
- Score tier indicators (Watching / Building / Signal / High Conviction / Max)
- Signal history table with outcomes
- Performance stats by symbol
- How to read this dashboard guide for trading buddies

---

## Railway Environment Variables

| Variable | Value | Notes |
|----------|-------|-------|
| TELEGRAM_BOT_TOKEN | your token | Never commit to GitHub |
| TELEGRAM_CHAT_ID | your chat id | Never commit to GitHub |
| DASHBOARD_PASSWORD | your password | Never commit to GitHub |
| RUN_MODE | live or backtest | Switch without touching Procfile |

---

## Backtest Results

### Run 1 (March 16 2026) — Original scoring
Threshold: 25 | No live CVD or funding data

| Metric | Value |
|--------|-------|
| Total signals | 374 |
| Win rate | 44.9% |
| Avg R | +0.21R |
| Best symbol | BNB 55.8% |
| Best regime | Trend 69.2% |

### Run 2 (March 17 2026) — Improved scoring
Threshold: 25 | Improved L1, L3, L5 scoring

| Metric | Value |
|--------|-------|
| Total signals | 946 |
| Win rate | 50.4% |
| Avg R | +0.45R |
| Best symbol | BNB 59.6% |
| Best regime | Trend 62.3% |
| Longs win rate | 53.6% |
| Shorts win rate | 47.7% |

Key finding: Longs outperform shorts. Trend regime
significantly outperforms mean-reversion (62.3% vs 48%).
Live system now filters: longs only, BTC threshold 75,
mean-reversion threshold 75.

---

## Known Issues

1. Backtest doesn't apply live scoring_engine filters (longs only, thresholds)
2. VIX falling back to BTC proxy on Railway EU server
3. Futures symbols disabled — no data source yet
4. Layer weights not yet tuned against live signal outcomes
5. L2 consistently scoring low (0-7) — CVD needs more history to build

Full details in ROADMAP.md.

---

## Current Market Conditions (March 17 2026)

Market is in extended rally with overbought conditions.
RSI 70-83 across all symbols. Fear/Greed 69-78.
CVD showing bearish divergence on most symbols.
Bot correctly staying silent — waiting for pullback.
First bullish CVD divergence appearing on SOL.
Scores currently 40-53/100. Need pullback for signals to fire.

---

## How to Start a New Dev Session

Paste this entire file at the start of the conversation then say
what you want to build or fix. Claude will have full context.

If editing a specific file also paste the current contents of
that file from GitHub so Claude can see the exact current state.

---

## Session Log

| Date | Work Done |
|------|-----------|
| Mar 15 2026 | Full system built and deployed. All 6 layers, scoring engine, alert manager, signal tracker, main loop. Live on Railway with Telegram alerts. |
| Mar 15 2026 | Professional brochure created for SilerTrades / 96 Bulls Financial Group. |
| Mar 15 2026 | Full system walkthrough — all components explained in plain English. |
| Mar 16 2026 | Added SOL, BNB, AVAX, XRP. Built auto outcome tracking. Built backtest engine. Run 1: 374 signals, 44.9% win rate, +0.21R. |
| Mar 16 2026 | Fixed regime classifier (0.6 to 0.45). Fixed L1 structure. Connected real macro data via yfinance. |
| Mar 16 2026 | Built web dashboard with live scores, signal history, layer bars, how-to guide. Password protected. |
| Mar 17 2026 | Full scoring audit. Improved L1 (graduated scoring, 6 lookback), L3 (widened proximity to 3%), L5 (RSI trending-aware). Run 2: 946 signals, 50.4% win rate, +0.45R avg. |
| Mar 17 2026 | Added score-building alert (50+ fires Telegram heads-up). Added RUN_MODE switch. Updated scoring_engine with longs-only filter, BTC threshold 75, mean-reversion threshold 75. |

---

## Next Session Priorities

1. Fix backtest to apply longs-only and threshold filters properly
2. Improve L2 order flow scoring — consistently too low
3. Futures data — Databento integration with trading partner
4. Tune layer weights after 30+ live signals collected
5. Consider adding SOL and ETH to high-priority watch (showing bullish CVD)

---

Last updated: March 17 2026
SilerTrades · A Division of 96 Bulls Financial Group
