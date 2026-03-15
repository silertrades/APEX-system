# =============================================================================
# APEX SYSTEM — data_feed.py
# =============================================================================

import time
import json
import logging
import threading
import requests
import numpy as np
import pandas as pd
import yfinance as yf

try:
    from tvdatafeed import TvDatafeed, Interval
    TV_AVAILABLE = True
except ImportError:
    TV_AVAILABLE = False

try:
    import websocket
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False

from config import (
    FUTURES_SYMBOLS, CRYPTO_SYMBOLS, TIMEFRAMES,
    CVD_LOOKBACK, WS_RECONNECT_SECONDS, DEBUG_MODE
)

logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("data_feed")

CANDLE_COUNT = 500

YF_INTERVAL_MAP = {
    "1D":  "1d",
    "4H":  "4h",
    "1H":  "1h",
    "15m": "15m",
    "5m":  "5m",
    "1m":  "1m",
}


# =============================================================================
# OHLCV FEED
# =============================================================================

class OHLCVFeed:

    def __init__(self):
        if TV_AVAILABLE:
            try:
                self.tv = TvDatafeed()
                self.use_tv = True
                log.info("TvDatafeed connected.")
            except Exception as e:
                log.warning(f"TvDatafeed failed ({e}). Using yfinance.")
                self.use_tv = False
        else:
            self.use_tv = False

    def get_candles(self, symbol: str, timeframe: str, n_bars: int = CANDLE_COUNT) -> pd.DataFrame:
        return self._fetch_yf(symbol, timeframe, n_bars)

    def get_all_timeframes(self, symbol: str) -> dict:
        result = {}
        for tf_name, tf_str in TIMEFRAMES.items():
            try:
                df = self.get_candles(symbol, tf_str)
                if df is not None and len(df) > 50:
                    result[tf_name] = df
                    log.debug(f"{symbol} {tf_name}: {len(df)} candles loaded.")
                else:
                    log.warning(f"{symbol} {tf_name}: insufficient data.")
            except Exception as e:
                log.error(f"Failed to fetch {symbol} {tf_name}: {e}")
        return result

    def _fetch_yf(self, symbol: str, timeframe: str, n_bars: int) -> pd.DataFrame:
        yf_interval = YF_INTERVAL_MAP.get(timeframe, "1h")

        if symbol == "ES":
            yf_symbol = "ES=F"
        elif symbol == "NQ":
            yf_symbol = "NQ=F"
        elif symbol == "CL":
            yf_symbol = "CL=F"
        elif symbol.endswith("USDT"):
            yf_symbol = symbol.replace("USDT", "-USD")
        else:
            yf_symbol = symbol

        period_map = {
            "1D": "2y", "4H": "60d", "1H": "30d",
            "15m": "8d", "5m": "5d", "1m": "1d"
        }
        period = period_map.get(timeframe, "30d")

        try:
            ticker = yf.Ticker(yf_symbol)
            df = ticker.history(period=period, interval=yf_interval)
            if df.empty:
                return pd.DataFrame()
            df.columns = [c.lower() for c in df.columns]
            df = df[["open", "high", "low", "close", "volume"]].copy()
            df.dropna(inplace=True)
            return df.tail(n_bars)
        except Exception as e:
            log.error(f"yfinance fetch failed for {symbol} {timeframe}: {e}")
            return pd.DataFrame()


# =============================================================================
# ORDER FLOW FEED
# =============================================================================

class OrderFlowFeed:

    def __init__(self):
        self.cvd_data   = {s: [] for s in CRYPTO_SYMBOLS}
        self.last_price = {s: None for s in CRYPTO_SYMBOLS}
        self._lock      = threading.Lock()

        if WS_AVAILABLE:
            self._start_all_streams()
        else:
            log.warning("websocket-client unavailable — CVD disabled.")

    def _start_all_streams(self):
        for symbol in CRYPTO_SYMBOLS:
            t = threading.Thread(
                target=self._run_ws,
                args=(symbol,),
                daemon=True,
                name=f"ws_{symbol}"
            )
            t.start()
            log.info(f"Order flow WebSocket started for {symbol}.")

    def _run_ws(self, symbol: str):
        url = f"wss://stream.binance.com:9443/ws/{symbol.lower()}@aggTrade"
        while True:
            try:
                ws = websocket.WebSocketApp(
                    url,
                    on_message=lambda ws, msg: self._on_message(symbol, msg),
                    on_error=lambda ws, err: log.error(f"WS error {symbol}: {err}"),
                    on_close=lambda ws, c, m: log.warning(f"WS closed {symbol}"),
                )
                ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                log.error(f"WS crashed for {symbol}: {e}")
            log.info(f"Reconnecting {symbol} in {WS_RECONNECT_SECONDS}s...")
            time.sleep(WS_RECONNECT_SECONDS)

    def _on_message(self, symbol: str, message: str):
        try:
            data    = json.loads(message)
            qty     = float(data["q"])
            is_sell = data["m"]
            delta   = -qty if is_sell else qty
            with self._lock:
                self.cvd_data[symbol].append(delta)
                self.last_price[symbol] = float(data["p"])
                if len(self.cvd_data[symbol]) > 10000:
                    self.cvd_data[symbol] = self.cvd_data[symbol][-5000:]
        except Exception as e:
            log.debug(f"aggTrade parse error {symbol}: {e}")

    def get_cvd_series(self, symbol: str, lookback: int = CVD_LOOKBACK) -> np.ndarray:
        with self._lock:
            deltas = self.cvd_data.get(symbol, [])
        if len(deltas) < 10:
            return np.array([])
        recent      = deltas[-lookback * 100:]
        bucket_size = max(1, len(recent) // lookback)
        bucketed    = []
        for i in range(0, len(recent), bucket_size):
            bucketed.append(sum(recent[i:i + bucket_size]))
        return np.cumsum(bucketed[-lookback:])

    def get_cvd_divergence(self, symbol: str, price_series: np.ndarray) -> dict:
        cvd = self.get_cvd_series(symbol, CVD_LOOKBACK)
        if len(cvd) < 5 or len(price_series) < 5:
            return {"divergence": "none", "strength": 0.0, "description": "Insufficient data"}

        n      = min(len(cvd), len(price_series))
        cvd    = cvd[-n:]
        prices = price_series[-n:]
        mid    = n // 2

        price_moved_dn = prices[mid:].mean() < prices[:mid].mean()
        price_moved_up = prices[mid:].mean() > prices[:mid].mean()
        cvd_moved_up
