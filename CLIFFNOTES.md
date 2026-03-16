APEX SYSTEM — CLIFF NOTES
SilerTrades · A Division of 96 Bulls Financial Group
=====================================================

THE BIG IDEA
6 independent signal engines scan the market every 60 seconds. A trade 
alert only fires when enough of them agree. One indicator can be fooled. 
Six independent ones agreeing simultaneously is edge.

-----------------------------------------------------

THE DATA
Pulls 500 candles across 4 timeframes (15m, 1H, 4H, Daily) from Binance 
every 60 seconds. A permanent live WebSocket streams every single trade 
in real time for order flow. All free.

-----------------------------------------------------

L1 — MARKET STRUCTURE (20pts)
Reads the wave pattern. Is the market making higher highs and higher lows 
(bullish) or lower highs and lower lows (bearish)? Detects BOS (trend 
continuing) and CHoCH (trend potentially reversing). Every trade must 
align with the big picture trend.

L2 — ORDER FLOW (20pts)
Watches every trade on Binance in real time. Builds a running score of 
aggressive buying vs aggressive selling (CVD). When price moves one way 
but CVD moves the other — that's institutions moving quietly. The 
divergence is the signal.

L3 — INSTITUTIONAL ZONES (15pts)
Maps where institutions placed their orders by finding Order Blocks (last 
candle before a big move), Fair Value Gaps (price inefficiencies markets 
return to fill), and Liquidity Pools (stop clusters institutions hunt 
before reversing). Scores how close price is to these zones.

L4 — MACRO + VOL REGIME (15pts)
Checks the weather before going outside. Is volatility low (trend), medium 
(normal), high (careful), or extreme (stay out)? Is the market trending or 
choppy? Is the dollar strengthening or weakening? Sets the trade mode — 
trend, mean-reversion, or breakout — which determines the exit strategy.

L5 — MULTI-TF MOMENTUM (15pts)
Are all four timeframes pushing in the same direction? Checks EMA stack 
alignment across 15m/1H/4H/Daily. Looks for RSI hidden divergence (trend 
continuation). Detects MACD momentum bursts and Bollinger/Keltner squeeze 
— the coiling before an explosive move.

L6 — SENTIMENT + POSITIONING (15pts)
Reads the crowd and fades the extremes. Funding rate extremes reveal 
overcrowded longs or shorts about to get squeezed. Open interest vs price 
reveals whether real money is entering or weak hands are covering. 
Fear/Greed proxy catches market euphoria and panic — both contrarian signals.

-----------------------------------------------------

THE SCORE
Each layer scores points. All six combine into a weighted 0-100 total.
Direction determined by weighted consensus vote across all layers.

65-79  — Standard alert. Normal size.
80-89  — High conviction. 1.5x size.
90+    — Maximum size. Rare. Career-defining setup.

Below 65 or no direction consensus — bot stays silent.

-----------------------------------------------------

KNOWN LIMITATIONS RIGHT NOW
- L4 yield curve is a placeholder — not real data yet
- L4 DXY uses BTC momentum as a proxy — not real DXY yet
- Futures (ES, NQ, CL) disabled — no data source confirmed yet
- Layer weights are defaults — not yet tuned against real outcomes

-----------------------------------------------------

THE STACK
Python · Binance API · WebSocket · Railway.app · Telegram · GitHub
Cost: ~$6-10/month. Everything else is free.

-----------------------------------------------------
