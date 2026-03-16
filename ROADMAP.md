# APEX Bot — Roadmap & Known Issues
**SilerTrades · A Division of 96 Bulls Financial Group**

This document tracks all known limitations, planned fixes, and future upgrades.
Updated every development session. Never trade real money on a known limitation
without understanding the impact.

---

## ✅ Completed

### Real DXY Data (L4)
- Connected yfinance DXY feed (DX-Y.NYB)
- Falls back to inverse BTC momentum proxy if unavailable
- Completed: March 16 2026

### Real VIX Data (L4)
- Connected yfinance VIX feed (^VIX)
- Falls back to BTC realized vol proxy if unavailable
- Note: Railway EU server VIX fetch currently falling back to proxy
- Completed: March 16 2026

### Real Yield Curve Data (L4)
- Connected yfinance 10Y (^TNX) and 5Y (^FVX) yields
- Falls back to 10Y minus fixed estimate if unavailable
- Completed: March 16 2026

### Regime Classifier Tuning (L4)
- Trending threshold lowered from 0.6 to 0.45
- Backtest showed original threshold almost never classified trend mode
- Result: more signals firing in trend conditions
- Completed: March 16 2026

### L1 Structure Detection Tuning
- Swing lookback increased from 5 to 8 candles
- Added minimum swing size filter (0.8% minimum move)
- Requires candle close for BOS confirmation (not just wick)
- Result: cleaner structure signals, reduced noise on BTC
- Completed: March 16 2026

### Signal Tracker with Auto Outcome Detection
- Every signal logged to /app/signals.csv on Railway
- Bot automatically detects TP1, TP2, TP3, SL hits
- Full journey tracked (e.g. TP1_THEN_SL)
- Telegram notification when each level is hit
- Completed: March 16 2026

### Backtest Engine
- 1 year of historical data across all 6 symbols
- Walks candle by candle, scores all 6 layers
- Checks outcomes forward in time automatically
- Results: 374 signals, 44.9% win rate, +0.21R avg
- Completed: March 16 2026

### 6 Crypto Symbols Added
- BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, AVAXUSDT, XRPUSDT
- All scanning live with Binance WebSocket order flow
- Completed: March 16 2026

---

## 🔴 Known Limitations (Fix Before Trading Real Money)

### VIX Falling Back to Proxy on Railway EU Server
- **Issue:** Real VIX fetch via yfinance failing from Railway's
  European server. Currently using BTC realized vol proxy.
- **Impact:** Minor — BTC vol proxy is well correlated with VIX.
  Doesn't materially affect scoring.
- **Fix:** Investigate yfinance ^VIX availability from EU IP.
  Alternative: use Alpha Vantage or FRED API for VIX data.
- **Priority:** Low.

### Futures Symbols Currently Disabled
- **Issue:** ES, NQ, CL set to empty list in config.py.
  No futures signals firing.
- **Impact:** Missing entire futures market opportunity.
- **Fix:** Connect Databento for CME tick data.
  Coordinate with trading partner on data access.
- **Priority:** High — needed before full system is live.

### Backtest Score Tiers All Zero
- **Issue:** Live score thresholds (65/80/90) never reached
  in backtest because L2 and L6 can't run without live feeds.
  Backtest ran at threshold 25 instead.
- **Impact:** Backtest results are directionally correct but
  not directly comparable to live system scoring.
- **Fix:** Build a backtest-specific scoring mode that
  simulates L2 and L6 from historical data where possible.
- **Priority:** Medium.

### Layer Weights Not Yet Tuned
- **Issue:** Layer weights in config.py are logical defaults,
  not validated against real signal outcomes.
- **Plan:** After 30+ live signals with tracked outcomes,
  analyze which layers most accurately predicted winners
  and increase their weights accordingly.
- **Priority:** Medium — do after 1 month of live signals.

---

## 🟡 Improvements (Do Soon)

### RUN_MODE Environment Variable
- Add Railway environment variable to switch between
  live bot and backtest without touching Procfile
- RUN_MODE=live → runs main.py
- RUN_MODE=backtest → runs backtest.py
- Priority: Medium — quality of life improvement

### Score-Building Alert
- Notify via Telegram when any symbol hits 50+ score
- Gives heads-up before signal fires
- Useful for manual confirmation before entry
- Priority: Medium

### BTC Scoring Investigation
- BTC was the only losing symbol in backtest (-0.12R)
- Worth deeper analysis — is it noise in structure detection
  or a fundamental issue with BTC's market microstructure?
- Priority: Medium

### Daily Summary Bug Verification
- Daily summary fires at scan 1440 (24hrs)
- Not yet verified in production
- Priority: Low — will self-verify after 24hrs of running

---

## 🟢 Planned Upgrades (Scale Up)

### Web Dashboard
- Live score display for all 6 symbols
- Signal history with outcomes
- Win rate by symbol and regime
- Backtest results visualization
- Host on Railway alongside bot — no extra cost

### Futures Data (Databento)
- Connect Databento API for ES, NQ, CL real-time OHLCV
- Re-enable FUTURES_SYMBOLS in config.py
- Build futures CVD from Databento tick feed
- Coordinate with trading partner on data access

### Execution Layer
- Auto-place orders when score hits 80+
- Start with paper trading to validate
- Exchange: Bybit or Binance Futures
- Position sizing already built in scoring_engine.py

### COT Data Integration (L6 Enhancement)
- Real Commitments of Traders data for futures
- Free from CFTC website, published weekly
- Would significantly strengthen L6 for futures signals

### On-Chain Data Layer
- Whale wallet movements
- Exchange inflows/outflows
- Miner selling pressure
- Free via Glassnode free tier or CryptoQuant

### Backtest Enhancement
- Simulate L2 CVD from historical tick data
- Simulate L6 funding rates from historical Binance data
- Would allow full 6-layer backtest at live score thresholds
- More accurate win rate projection

---

## 📋 Session Log

| Date | What We Built |
|------|--------------|
| Mar 15 2026 | Full system built and deployed — config, data feed, all 6 layers, scoring engine, alert manager, main loop. Live on Railway. Telegram alerts firing. |
| Mar 15 2026 | Professional brochure created for SilerTrades / 96 Bulls Financial Group |
| Mar 15 2026 | Walked through full system understanding — all 6 layers explained |
| Mar 16 2026 | Added 4 new crypto symbols (SOL, BNB, AVAX, XRP) |
| Mar 16 2026 | Built signal tracker with automatic TP/SL outcome detection |
| Mar 16 2026 | Built and ran backtest engine — 374 signals, 44.9% win rate, +0.21R |
| Mar 16 2026 | Fixed regime classifier — trending threshold 0.6 → 0.45 |
| Mar 16 2026 | Fixed L1 structure — tighter swing detection, BOS requires close |
| Mar 16 2026 | Connected real DXY, VIX, yield curve data via yfinance |

---

## 💡 Ideas Parking Lot

- Multi-exchange CVD (combine Binance + Bybit order flow)
- Options flow integration (Deribit OI and put/call ratio)
- Alerts for score building (notify at 50+ as early warning)
- Telegram command interface — text bot to get current scores
- Machine learning layer trained on signal outcomes
- Weekly performance email summary
- Backtesting on 2+ years once enhanced backtest is built

---

## 📊 Backtest Results Summary (March 16 2026)

**Period:** 1 year | **Symbols:** ETH, SOL, BNB, AVAX, XRP (BTC partial)
**Note:** Run with threshold 25, no live CVD or funding data

| Metric | Value |
|--------|-------|
| Total signals | 374 |
| Win rate | 44.9% |
| Avg R per trade | +0.21R |
| Avg max R reached | 1.67R |
| Best symbol | BNB (55.8% win, +0.67R) |
| Best regime | Trend (69.2% win rate) |
| Worst symbol | BTC (36.5% win, -0.12R) |

**Key finding:** System performs significantly better in trend
regime (69.2%) vs mean-reversion (44.0%). Regime classifier
tuning is the highest priority improvement.

---

*Last updated: March 16, 2026*
*Maintained by SilerTrades — A Division of 96 Bulls Financial Group*
