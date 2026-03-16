# =============================================================================
# APEX SYSTEM — data_feed.py (Binance real-time version)
# =============================================================================

import time
import json
import logging
import threading
import requests
import numpy as np
import pandas as pd

try:
    import websocket
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False

from config import (
    CRYPTO_SYMBOLS, TIMEFRAMES,
    CVD_LOOKBACK, WS_RECONNECT_SECONDS, DEBUG_MODE
)
from l4_macro import MacroFeed

logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("data_feed")

BINANCE_REST = "https://api.binance.com"

BINANCE_INTERVAL_MAP = {
    "1D":  "1d",
    "4H":  "4h",
    "1H":  "1h",
    "15m": "15m",
    "5m":  "5m",
    "1m":  "1m",
}

CANDLE_COUNT = 500


# =============================================================================
# OHLCV FEED — Binance REST API
# =============================================================================

class OHLCVFeed:

    def get_candles(self, symbol: str, timeframe: str,
                    n_bars: int = CANDLE_COUNT) -> pd.DataFrame:
        interval = BINANCE_INTERVAL_MAP.get(timeframe, "1h")
        try:
            url    = f"{BINANCE_REST}/api/v3/klines"
            params = {"symbol": symbol, "interval": interval, "limit": n_bars}
            resp   = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            raw = resp.json()

            df = pd.DataFrame(raw, columns=[
                "timestamp", "open", "high", "low", "close", "volume",
                "close_time", "quote_volume", "trades",
                "taker_buy_base", "taker_buy_quote", "ignore"
            ])

            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df.set_index("timestamp", inplace=True)
            df = df[["open", "high", "low", "close", "volume"]].astype(float)
            df.dropna(inplace=True)
            log.debug(f"{symbol} {timeframe}: {len(df)} candles from Binance.")
            return df

        except Exception as e:
            log.error(f"Binance OHLCV failed for {symbol} {timeframe}: {e}")
            return pd.DataFrame()

    def get_all_timeframes(self, symbol: str) -> dict:
        result = {}
        for tf_name, tf_str in TIMEFRAMES.items():
            df = self.get_candles(symbol, tf_str)
            if not df.empty and len(df) > 50:
                result[tf_name] = df
            else:
                log.warning(f"{symbol} {tf_name}: insufficient data.")
        return result


# =============================================================================
# ORDER FLOW FEED — Binance WebSocket (live CVD)
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

    def get_cvd_series(self, symbol: str,
                       lookback: int = CVD_LOOKBACK) -> np.ndarray:
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

    def get_cvd_divergence(self, symbol: str,
                           price_series: np.ndarray) -> dict:
        cvd = self.get_cvd_series(symbol, CVD_LOOKBACK)
        if len(cvd) < 5 or len(price_series) < 5:
            return {"divergence": "none", "strength": 0.0,
                    "description": "Insufficient data"}

        n      = min(len(cvd), len(price_series))
        cvd    = cvd[-n:]
        prices = price_series[-n:]
        mid    = n // 2

        price_moved_dn = prices[mid:].mean() < prices[:mid].mean()
        price_moved_up = prices[mid:].mean() > prices[:mid].mean()
        cvd_moved_up   = cvd[mid:].mean()    > cvd[:mid].mean()
        cvd_moved_dn   = cvd[mid:].mean()    < cvd[:mid].mean()

        if price_moved_dn and cvd_moved_up:
            strength = min(1.0, abs(prices[-1] - prices[0]) /
                           (prices[0] + 1e-9) * 10)
            return {"divergence": "bullish", "strength": round(strength, 3),
                    "description": "Bullish CVD div: price down, CVD up"}

        if price_moved_up and cvd_moved_dn:
            strength = min(1.0, abs(prices[-1] - prices[0]) /
                           (prices[0] + 1e-9) * 10)
            return {"divergence": "bearish", "strength": round(strength, 3),
                    "description": "Bearish CVD div: price up, CVD down"}

        return {"divergence": "none", "strength": 0.0,
                "description": "No divergence"}


# =============================================================================
# CRYPTO SENTIMENT FEED
# =============================================================================

class CryptoSentimentFeed:

    BINANCE_FAPI = "https://fapi.binance.com"
    CACHE_TTL    = 300

    def __init__(self):
        self._cache      = {}
        self._cache_time = {}

    def _is_fresh(self, key: str) -> bool:
        return (key in self._cache and
                time.time() - self._cache_time.get(key, 0) < self.CACHE_TTL)

    def get_funding_rate(self, symbol: str) -> float:
        key = f"funding_{symbol}"
        if self._is_fresh(key):
            return self._cache[key]
        try:
            resp = requests.get(
                f"{self.BINANCE_FAPI}/fapi/v1/premiumIndex",
                params={"symbol": symbol}, timeout=5
            )
            resp.raise_for_status()
            rate                  = float(resp.json()["lastFundingRate"])
            self._cache[key]      = rate
            self._cache_time[key] = time.time()
            return rate
        except Exception as e:
            log.error(f"Funding rate failed for {symbol}: {e}")
            return 0.0

    def get_open_interest(self, symbol: str) -> dict:
        key = f"oi_{symbol}"
        if self._is_fresh(key):
            return self._cache[key]
        try:
            resp = requests.get(
                f"{self.BINANCE_FAPI}/fapi/v1/openInterest",
                params={"symbol": symbol}, timeout=5
            )
            resp.raise_for_status()
            current_oi = float(resp.json()["openInterest"])

            resp2 = requests.get(
                f"{self.BINANCE_FAPI}/futures/data/openInterestHist",
                params={"symbol": symbol, "period": "1h", "limit": 24},
                timeout=5
            )
            resp2.raise_for_status()
            hist       = resp2.json()
            oi_chg_pct = 0.0
            if len(hist) >= 2:
                old_oi     = float(hist[0]["sumOpenInterest"])
                oi_chg_pct = (current_oi - old_oi) / (old_oi + 1e-9)

            result                = {"oi": current_oi,
                                     "oi_change_pct": oi_chg_pct}
            self._cache[key]      = result
            self._cache_time[key] = time.time()
            return result
        except Exception as e:
            log.error(f"OI fetch failed for {symbol}: {e}")
            return {"oi": 0.0, "oi_change_pct": 0.0}


# =============================================================================
# UNIFIED DATA MANAGER
# =============================================================================

class DataManager:

    def __init__(self):
        log.info("Initializing DataManager (Binance mode)...")
        self.ohlcv      = OHLCVFeed()
        self.order_flow = OrderFlowFeed()
        self.macro      = MacroFeed()
        self.sentiment  = CryptoSentimentFeed()
        log.info("DataManager ready.")

    def get_all(self, symbol: str) -> dict:
        log.debug(f"Fetching all data for {symbol}...")

        candles        = self.ohlcv.get_all_timeframes(symbol)
        cvd_divergence = {"divergence": "none", "strength": 0.0,
                          "description": "N/A"}

        if "LTF" in candles:
            close_prices   = candles["LTF"]["close"].values
            cvd_divergence = self.order_flow.get_cvd_divergence(
                symbol, close_prices)

        macro = {
            "vix":               self.macro.get_vix(),
            "dxy_momentum":      self.macro.get_dxy_momentum(),
            "yield_curve_slope": self.macro.get_yield_curve_slope(),
        }

        sentiment = {
            "funding_rate": self.sentiment.get_funding_rate(symbol),
            "oi":           self.sentiment.get_open_interest(symbol),
        }

        return {
            "symbol":         symbol,
            "candles":        candles,
            "cvd_divergence": cvd_divergence,
            "macro":          macro,
            "sentiment":      sentiment,
            "timestamp":      pd.Timestamp.now(),
        }
