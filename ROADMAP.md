# APEX Bot — Roadmap & Known Issues
**SilerTrades · A Division of 96 Bulls Financial Group**

This document tracks all known limitations, planned fixes, and future upgrades.
Updated every development session. Never trade real money on a known limitation
without understanding the impact.

---

## 🔴 Known Limitations (Fix Before Scaling)

### L4 — Yield Curve is a Placeholder
- **Issue:** The yield curve check returns a fixed neutral value (1.0) every scan.
  It is not pulling real yield data.
- **Impact:** L4 score is slightly inflated in risk-off environments where an
  inverted curve would otherwise reduce the score.
- **Fix:** Connect a real macro data source (Polygon.io, FRED API, or Quandl)
  to pull live 10Y and 2Y treasury yields.
- **Priority:** Medium — affects score accuracy but doesn't break the system.

### L4 — DXY is a BTC Proxy, Not Real Data
- **Issue:** Dollar strength is estimated by inverting BTC's 10-day momentum.
  The bot is not pulling actual DXY price data.
- **Impact:** The BTC/DXY inverse correlation is real but imperfect. In
  decoupled environments (BTC up AND dollar up simultaneously) this signal
  will be wrong.
- **Fix:** Connect real DXY feed via Polygon.io or yfinance once a reliable
  source is confirmed.
- **Priority:** Medium.

### L2 — Futures Order Flow Not Connected
- **Issue:** CVD and order flow only works for crypto (Binance WebSocket).
  Futures symbols (ES, NQ, CL) have no order flow data currently.
- **Impact:** If futures symbols are added back, L2 will score 0 for all
  futures signals. The system will still work but without its most powerful layer.
- **Fix:** Connect Databento or Tradovate WebSocket for CME tick data.
  Discussed with trading partner — deep futures order flow data is increasingly
  restricted by institutions. Databento is the current best candidate.
- **Priority:** High — needed before futures trading goes live.

### Futures Symbols Currently Disabled
- **Issue:** ES, NQ, CL are set to empty list in config.py. The system
  only scans BTCUSDT and ETHUSDT.
- **Impact:** No futures signals at all currently.
- **Fix:** Re-enable once a real-time futures data source is confirmed
  and L2 futures order flow is connected.
- **Priority:** High — core part of the original system design.

### tvdatafeed Removed (Python 3.13 Incompatibility)
- **Issue:** tvdatafeed does not support Python 3.13 which Railway deploys
  by default. Removed from requirements.txt. System falls back to
  Binance REST API for all OHLCV data.
- **Impact:** For crypto this is fine — Binance data is actually better.
  For futures this would have been the TradingView data source.
- **Fix:** Either pin Python to 3.11 in Railway and re-add tvdatafeed,
  or replace permanently with Databento/Polygon for futures OHLCV.
- **Priority:** Low for crypto. High once futures are added.

---

## 🟡 Improvements (Do Soon)

### Layer Weight Tuning
- **Issue:** Layer weights in config.py are set to reasonable defaults
  but have not been validated against real signal performance data.
- **Plan:** After 30+ signals have fired and outcomes are tracked,
  analyze which layers most accurately predicted profitable trades
  and increase their weights accordingly.
- **Priority:** Medium — do after 1 month of live signals.

### Signal Performance Log
- **Issue:** Currently no record of which signals fired, what the outcome
  was, or which layers contributed most.
- **Plan:** Build a logging system that records every alert to a CSV or
  database with entry price, SL hit or TP hit, score, and layer breakdown.
  This is how we tune the system over time.
- **Priority:** High — without this we are flying blind on performance.

### Score Threshold Validation
- **Issue:** The 65/80/90 thresholds were set based on logic, not backtesting.
- **Plan:** Once signal log is built, analyze score distribution vs outcomes
  and adjust thresholds if needed.
- **Priority:** Medium.

### DRY_RUN Safety Check
- **Issue:** DRY_RUN is currently set to False (live alerts firing).
  If the bot is ever redeployed carelessly this could send confusing
  alerts during testing.
- **Plan:** Add an environment variable for DRY_RUN in Railway so it
  never gets accidentally committed as False in the code.
- **Priority:** Low but clean practice.

---

## 🟢 Planned Upgrades (Scale Up)

### Add More Crypto Symbols
- Add SOL, AVAX, BNB, XRP to CRYPTO_SYMBOLS in config.py
- All use Binance WebSocket — zero extra cost or complexity
- Can be done any time — 15 minute task

### Add Futures Data (Databento)
- Connect Databento API for ES, NQ, CL real-time OHLCV
- Re-enable FUTURES_SYMBOLS in config.py
- Build futures-specific CVD from Databento tick feed
- Coordinate with trading partner on data access and cost

### Add Real Macro Data Feed
- Connect FRED API (free) for treasury yield data
- Fix L4 yield curve from placeholder to real signal
- Connect real DXY feed for L4 dollar regime

### Build Execution Layer
- Auto-place orders when signal fires above 80+ score
- Start with paper trading to validate
- Exchange: Bybit or Binance Futures (accessible from EU server)
- Position sizing from scoring_engine.py already built — just needs
  the order placement function added to alert_manager.py

### Build Signal Performance Dashboard
- Web dashboard showing all historical signals
- Win rate by layer combination
- Average R multiple by regime
- Score distribution over time
- Can be built as a simple Railway web service alongside the bot

### Backtest Engine
- Run the 6-layer scoring engine against historical data
- Validate edge before going full size live
- Requires storing historical signals and outcomes first

### COT Data Integration (L6 Enhancement)
- Add real Commitments of Traders data for futures
- Currently L6 uses funding rate and OI as proxies
- COT data is free from CFTC website, published weekly
- Would significantly strengthen L6 for futures signals

---

## 📋 Session Log

| Date | What We Built |
|------|--------------|
| Mar 15 2026 | Full system built and deployed — config, data feed, all 6 layers, scoring engine, alert manager, main loop. Live on Railway. Telegram alerts firing. |
| Mar 15 2026 | Professional brochure created for SilerTrades / 96 Bulls Financial Group |
| Mar 15 2026 | Walked through system understanding — L1 through L4 explained |

---

## 💡 Ideas Parking Lot
*Things worth exploring but not yet committed to*

- Multi-exchange CVD (combine Binance + Bybit order flow for stronger signal)
- Options flow integration for crypto (Deribit open interest and put/call)
- On-chain data layer — whale wallet movements, exchange inflows/outflows
- Machine learning layer — train a model on historical signal outcomes
- Alerts for when score is *building* (e.g. notify at 50+ so you're heads up)
- Telegram command interface — text the bot to get current scores on demand

---

*Last updated: March 15, 2026*
*Maintained by SilerTrades — A Division of 96 Bulls Financial Group*
