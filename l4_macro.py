# =============================================================================
# APEX SYSTEM — l4_macro.py
# =============================================================================
# Layer 4: Macro + Volatility Regime
#
# What this does:
#   - Reads real VIX from yfinance (falls back to BTC vol proxy)
#   - Reads real DXY from yfinance (falls back to inverse BTC momentum)
#   - Reads real yield curve from yfinance (10Y - 5Y spread)
#   - Determines risk-on vs risk-off regime
#   - Classifies trending vs mean-reverting conditions
#     (threshold lowered from 0.6 to 0.45 based on backtest results)
#
# Score: 0–15 points
# =============================================================================

import time
import logging
import yfinance as yf
import numpy as np
import pandas as pd

from config import (
    VIX_RISK_OFF_THRESHOLD,
    DXY_MOMENTUM_PERIOD,
)

log = logging.getLogger("l4_macro")


# =============================================================================
# VOLATILITY REGIME
# =============================================================================

def classify_vol_regime(vix: float) -> dict:
    if vix < 15:
        return {
            "regime":      "low",
            "risk_on":     True,
            "description": f"Low vol ({vix:.1f}) — trending conditions, "
                           f"momentum strategies favored"
        }
    elif vix < VIX_RISK_OFF_THRESHOLD:
        return {
            "regime":      "mid",
            "risk_on":     True,
            "description": f"Mid vol ({vix:.1f}) — normal conditions, "
                           f"all strategies viable"
        }
    elif vix < 35:
        return {
            "regime":      "high",
            "risk_on":     False,
            "description": f"High vol ({vix:.1f}) — risk-off, "
                           f"reduce size, mean reversion favored"
        }
    else:
        return {
            "regime":      "extreme",
            "risk_on":     False,
            "description": f"Extreme vol ({vix:.1f}) — crisis conditions, "
                           f"cash or short only"
        }


# =============================================================================
# TREND VS MEAN REVERSION REGIME
# =============================================================================

def classify_market_regime(df: pd.DataFrame, period: int = 20) -> dict:
    """
    Determines if the market is trending or mean-reverting.
    Threshold lowered from 0.6 to 0.45 based on backtest results —
    the original threshold almost never classified trend mode.
    """
    if len(df) < period * 2:
        return {
            "regime":      "neutral",
            "strength":    0.5,
            "description": "Insufficient data for regime classification"
        }

    recent     = df["close"].tail(period).values
    net_move   = abs(recent[-1] - recent[0])
    total_path = sum(abs(recent[i] - recent[i-1])
                     for i in range(1, len(recent)))

    if total_path == 0:
        return {
            "regime":      "neutral",
            "strength":    0.5,
            "description": "No price movement"
        }

    efficiency = net_move / total_path

    if efficiency >= 0.45:
        return {
            "regime":      "trending",
            "strength":    round(efficiency, 3),
            "description": f"Trending market (efficiency: {efficiency:.2f}) "
                           f"— momentum strategies favored"
        }
    elif efficiency <= 0.25:
        return {
            "regime":      "mean_reverting",
            "strength":    round(1 - efficiency, 3),
            "description": f"Mean-reverting market (efficiency: {efficiency:.2f}) "
                           f"— fading strategies favored"
        }
    else:
        return {
            "regime":      "neutral",
            "strength":    round(efficiency, 3),
            "description": f"Neutral regime (efficiency: {efficiency:.2f}) "
                           f"— selective entries only"
        }


# =============================================================================
# DXY REGIME
# =============================================================================

def classify_dxy_regime(dxy_momentum: float) -> dict:
    if dxy_momentum < -0.02:
        return {
            "regime":      "risk_on",
            "description": f"Dollar weakening ({dxy_momentum*100:.1f}%) "
                           f"— tailwind for crypto longs"
        }
    elif dxy_momentum > 0.02:
        return {
            "regime":      "risk_off",
            "description": f"Dollar strengthening ({dxy_momentum*100:.1f}%) "
                           f"— headwind for crypto longs"
        }
    else:
        return {
            "regime":      "neutral",
            "description": f"Dollar neutral ({dxy_momentum*100:.1f}%) "
                           f"— no macro bias"
        }


# =============================================================================
# YIELD CURVE
# =============================================================================

def classify_yield_curve(slope: float) -> dict:
    if slope > 1.0:
        return {
            "regime":      "normal",
            "description": f"Normal yield curve (+{slope:.2f}) "
                           f"— growth environment"
        }
    elif slope > 0:
        return {
            "regime":      "flat",
            "description": f"Flat yield curve ({slope:.2f}) "
                           f"— caution, slowdown risk"
        }
    else:
        return {
            "regime":      "inverted",
            "description": f"Inverted yield curve ({slope:.2f}) "
                           f"— recession risk, risk-off"
        }


# =============================================================================
# OVERALL REGIME
# =============================================================================

def get_overall_regime(vol_regime: dict,
                       market_regime: dict,
                       dxy_regime: dict,
                       yield_regime: dict) -> dict:
    is_risk_on   = vol_regime["risk_on"]
    is_trending  = market_regime["regime"] == "trending"
    is_mean_rev  = market_regime["regime"] == "mean_reverting"
    is_crisis    = vol_regime["regime"] == "extreme"
    dxy_risk_off = dxy_regime["regime"] == "risk_off"

    if is_crisis:
        return {
            "mode":        "avoid",
            "risk_level":  "high",
            "description": "Crisis conditions — avoid longs, reduce all exposure"
        }

    if is_risk_on and is_trending and not dxy_risk_off:
        return {
            "mode":        "trend",
            "risk_level":  "low",
            "description": "Ideal trend conditions — full size momentum entries"
        }

    if is_risk_on and is_mean_rev:
        return {
            "mode":        "mean_reversion",
            "risk_level":  "medium",
            "description": "Mean reversion conditions — fade extremes, "
                           "tight targets"
        }

    if not is_risk_on and is_trending:
        return {
            "mode":        "breakout",
            "risk_level":  "medium",
            "description": "High vol trend — breakout entries only, "
                           "wider stops"
        }

    return {
        "mode":        "mean_reversion",
        "risk_level":  "medium",
        "description": "Mixed conditions — selective entries, reduced size"
    }


# =============================================================================
# MACRO DATA FETCHER
# =============================================================================

class MacroFeed:
    """
    Fetches macro data via yfinance with intelligent fallbacks.
    Cached for 15 minutes — macro data moves slowly.
    """

    CACHE_TTL = 900

    def __init__(self):
        self._cache      = {}
        self._cache_time = {}

    def _is_fresh(self, key: str) -> bool:
        return (key in self._cache and
                time.time() - self._cache_time.get(key, 0) < self.CACHE_TTL)

    def get_vix(self) -> float:
        """
        Real VIX from yfinance. Falls back to BTC realized vol proxy.
        """
        if self._is_fresh("vix"):
            return self._cache["vix"]

        # Try real VIX
        try:
            vix = yf.Ticker("^VIX").fast_info["last_price"]
            self._cache["vix"]      = float(vix)
            self._cache_time["vix"] = time.time()
            log.debug(f"VIX (real): {self._cache['vix']:.1f}")
            return self._cache["vix"]
        except Exception as e:
            log.debug(f"Real VIX unavailable ({e}) — using BTC proxy")

        # Fall back to BTC realized vol proxy
        try:
            df = yf.Ticker("BTC-USD").history(period="30d", interval="1d")
            if not df.empty:
                returns   = df["Close"].pct_change().dropna()
                realized  = returns.std() * (365 ** 0.5) * 100
                vix_proxy = realized / 3.0
                self._cache["vix"]      = float(vix_proxy)
                self._cache_time["vix"] = time.time()
                log.debug(f"VIX (BTC proxy): {vix_proxy:.1f}")
                return self._cache["vix"]
        except Exception as e2:
            log.error(f"VIX proxy failed: {e2}")

        return 20.0

    def get_dxy_momentum(self, period: int = DXY_MOMENTUM_PERIOD) -> float:
        """
        Real DXY momentum from yfinance. Falls back to inverse BTC momentum.
        """
        if self._is_fresh("dxy"):
            return self._cache["dxy"]

        # Try real DXY
        try:
            df = yf.Ticker("DX-Y.NYB").history(period="30d", interval="1d")
            if len(df) >= period:
                momentum = (df["Close"].iloc[-1] - df["Close"].iloc[-period]) \
                           / df["Close"].iloc[-period]
                self._cache["dxy"]      = float(momentum)
                self._cache_time["dxy"] = time.time()
                log.debug(f"DXY (real): {momentum*100:.2f}%")
                return self._cache["dxy"]
        except Exception as e:
            log.debug(f"Real DXY unavailable ({e}) — using BTC proxy")

        # Fall back to inverse BTC momentum
        try:
            df = yf.Ticker("BTC-USD").history(period="30d", interval="1d")
            if len(df) >= period:
                btc_mom   = (df["Close"].iloc[-1] - df["Close"].iloc[-period]) \
                            / df["Close"].iloc[-period]
                dxy_proxy = -btc_mom
                self._cache["dxy"]      = float(dxy_proxy)
                self._cache_time["dxy"] = time.time()
                log.debug(f"DXY (BTC proxy): {dxy_proxy*100:.2f}%")
                return self._cache["dxy"]
        except Exception as e:
            log.error(f"DXY proxy failed: {e}")

        return 0.0

    def get_yield_curve_slope(self) -> float:
        """
        Real yield curve (10Y - 5Y) from yfinance.
        Slightly delayed but yield curve moves slowly — acceptable.
        Falls back to 10Y minus fixed estimate if 5Y unavailable.
        """
        if self._is_fresh("yield_curve"):
            return self._cache["yield_curve"]

        try:
            t10    = yf.Ticker("^TNX").fast_info["last_price"]
            t5     = yf.Ticker("^FVX").fast_info["last_price"]
            spread = float(t10) - float(t5)
            self._cache["yield_curve"]      = spread
            self._cache_time["yield_curve"] = time.time()
            log.debug(f"Yield curve: {spread:.2f} "
                      f"(10Y:{float(t10):.2f} 5Y:{float(t5):.2f})")
            return spread
        except Exception as e:
            log.debug(f"Yield curve fetch failed ({e}) — trying fallback")

        try:
            t10    = yf.Ticker("^TNX").fast_info["last_price"]
            spread = float(t10) - 4.0
            self._cache["yield_curve"]      = spread
            self._cache_time["yield_curve"] = time.time()
            log.debug(f"Yield curve (approx): {spread:.2f}")
            return spread
        except Exception as e2:
            log.error(f"Yield curve fallback failed: {e2}")

        return 1.0


# =============================================================================
# MAIN SCORER
# =============================================================================

def score(data: dict) -> dict:
    """
    Main entry point — called by scoring_engine.py

    Score breakdown (max 15):
        Vol regime supports trade:    +5
        Market regime matches mode:   +4
        DXY regime supports trade:    +3
        Yield curve supports trade:   +3
    """
    macro   = data.get("macro", {})
    candles = data.get("candles", {})
    mtf_df  = candles.get("MTF", pd.DataFrame())

    vix      = macro.get("vix", 20.0)
    dxy_mom  = macro.get("dxy_momentum", 0.0)
    yc_slope = macro.get("yield_curve_slope", 1.0)

    vol_regime    = classify_vol_regime(vix)
    market_regime = classify_market_regime(mtf_df) if not mtf_df.empty else \
                    {"regime": "neutral", "strength": 0.5,
                     "description": "No data"}
    dxy_regime    = classify_dxy_regime(dxy_mom)
    yield_regime  = classify_yield_curve(yc_slope)
    overall       = get_overall_regime(vol_regime, market_regime,
                                       dxy_regime, yield_regime)

    points    = 0
    reasons   = []
    direction = "neutral"

    # Vol regime (max 5)
    if vol_regime["regime"] == "low":
        points += 5
        reasons.append(f"Vol regime: {vol_regime['description']}")
    elif vol_regime["regime"] == "mid":
        points += 3
        reasons.append(f"Vol regime: {vol_regime['description']}")
    elif vol_regime["regime"] == "high":
        points += 1
        reasons.append(f"Vol regime: {vol_regime['description']}")
    else:
        reasons.append(f"Vol regime: {vol_regime['description']}")

    # Market regime (max 4)
    if overall["mode"] == "trend":
        points += 4
        reasons.append(f"Market regime: {market_regime['description']}")
    elif overall["mode"] == "mean_reversion":
        points += 2
        reasons.append(f"Market regime: {market_regime['description']}")
    elif overall["mode"] == "breakout":
        points += 3
        reasons.append(f"Market regime: {market_regime['description']}")

    # DXY regime (max 3)
    if dxy_regime["regime"] == "risk_on":
        points   += 3
        direction = "long"
        reasons.append(f"DXY: {dxy_regime['description']}")
    elif dxy_regime["regime"] == "neutral":
        points += 2
        reasons.append(f"DXY: {dxy_regime['description']}")
    else:
        reasons.append(f"DXY: {dxy_regime['description']}")

    # Yield curve (max 3)
    if yield_regime["regime"] == "normal":
        points += 3
        reasons.append(f"Yield curve: {yield_regime['description']}")
    elif yield_regime["regime"] == "flat":
        points += 1
        reasons.append(f"Yield curve: {yield_regime['description']}")
    else:
        reasons.append(f"Yield curve: {yield_regime['description']}")

    points = min(15, points)

    log.debug(f"L4 score: {points}/15 | regime: {overall['mode']} | "
              f"{' | '.join(reasons)}")

    return {
        "layer":     "L4_macro",
        "score":     points,
        "max":       15,
        "direction": direction,
        "reasons":   reasons,
        "details": {
            "vol_regime":    vol_regime,
            "market_regime": market_regime,
            "dxy_regime":    dxy_regime,
            "yield_regime":  yield_regime,
            "overall":       overall,
        }
    }


def _empty_score(reason: str) -> dict:
    return {
        "layer":     "L4_macro",
        "score":     0,
        "max":       15,
        "direction": "neutral",
        "reasons":   [reason],
        "details":   {}
    }
