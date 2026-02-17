"""Market data providers for the Dashboard tab.

Prices and VIX via yfinance; Fear & Greed via JM Bullion (gold) and
Alternative.me (crypto); Bitcoin indicators (RSI, CBBI, etc.) via
yfinance price data and free APIs.

IMPORTANT: yfinance is NOT thread-safe.  All yfinance calls MUST run
on the same thread.  The ``fetch_all()`` method bundles every data
request into a single sequential call so the GUI can dispatch it in
one background Worker without race conditions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple

import pandas as pd
import requests
import yfinance as yf

import fear_and_greed

from insider_scanner.core.coinmetrics_client import CoinMetricsClient
from insider_scanner.core.coinmetrics_indicators_service import (
    CoinMetricsIndicatorsService,
    CoinMetricsIndicatorsConfig,
)

log = logging.getLogger(__name__)

# Symbols shown in the top price row
PRICE_SYMBOLS: List[str] = ["GC=F", "SI=F", "CL=F", "ES=F", "NQ=F"]


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _extract_close(df: pd.DataFrame, symbol: str) -> pd.Series:
    """Extract 'Close' prices from a yfinance DataFrame.

    Handles both flat columns (single-ticker download) and MultiIndex
    columns (multi-ticker / group_by='column').
    """
    if df is None or df.empty:
        return pd.Series(dtype=float)

    if isinstance(df.columns, pd.MultiIndex):
        if ("Close", symbol) in df.columns:
            s = df[("Close", symbol)]
        elif ("Adj Close", symbol) in df.columns:
            s = df[("Adj Close", symbol)]
        else:
            close_cols = [c for c in df.columns if "Close" in c]
            if not close_cols:
                return pd.Series(dtype=float)
            s = df[close_cols[0]]
    else:
        s = df.get("Close")
        if s is None:
            s = df.get("Adj Close")
        if s is None:
            return pd.Series(dtype=float)

    s = pd.to_numeric(s, errors="coerce").dropna()
    s.index = pd.to_datetime(s.index, utc=True)
    return s.sort_index()


# -------------------------------------------------------------------
# Bitcoin indicator math
# -------------------------------------------------------------------

def calculate_rsi(close: pd.Series, period: int = 14) -> Optional[float]:
    """Calculate the latest RSI value from a close-price series.

    Uses the standard exponential-moving-average (Wilder) smoothing.
    Returns None if there isn't enough data.
    """
    if close is None or len(close) < period + 1:
        return None

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    # Wilder smoothing (equivalent to EMA with alpha=1/period)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period).mean()

    last_gain = avg_gain.iloc[-1]
    last_loss = avg_loss.iloc[-1]

    if last_loss == 0:
        return 100.0
    rs = last_gain / last_loss
    return round(100.0 - 100.0 / (1.0 + rs), 1)


def price_vs_lth_rp_pct(price: float, lth_rp: float) -> float | None:
    if price <= 0 or lth_rp <= 0:
        return None
    return (price / lth_rp - 1.0) * 100.0


# -------------------------------------------------------------------
# In-memory TTL cache
# -------------------------------------------------------------------

@dataclass
class CacheEntry:
    value: Any
    expires_at: datetime


class TTLCache:
    """Simple in-memory key→value cache with per-entry expiration."""

    def __init__(self):
        self._store: Dict[str, CacheEntry] = {}

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if entry and _utcnow() < entry.expires_at:
            return entry.value
        return None

    def set(self, key: str, value: Any, ttl: timedelta) -> None:
        self._store[key] = CacheEntry(
            value=value, expires_at=_utcnow() + ttl,
        )

    def clear(self) -> None:
        self._store.clear()


# -------------------------------------------------------------------
# Fear & Greed classification
# -------------------------------------------------------------------

def classify_fng(v: int) -> str:
    """Classify a 0–100 Fear & Greed score into a label."""
    if v < 25:
        return "Extreme Fear"
    if v < 50:
        return "Fear"
    if v < 75:
        return "Greed"
    return "Extreme Greed"


# -------------------------------------------------------------------
# Fear & Greed clients
# -------------------------------------------------------------------

class StockFearGreedClient:

    def __init__(
            self,
            cache: TTLCache,
            ttl_minutes: int = 60,
            timeout_sec: int = 10,
    ):
        self.cache = cache
        self.ttl = timedelta(minutes=ttl_minutes)
        self.timeout_sec = timeout_sec

    def get_latest(self) -> Optional[Tuple[int, str]]:
        cache_key = "stock_fng_latest"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        latest: Optional[Tuple[int, str]] = None
        try:
            score = int(fear_and_greed.get().value)
            latest = (score, classify_fng(score))
        except Exception:
            latest = None

        self.cache.set(cache_key, latest, self.ttl)
        return latest

class GoldFearGreedClient:
    """JM Bullion JSON: {"YYYY-MM-DD": score, ...}"""

    URL = "https://cdn.jmbullion.com/fearandgreed/fearandgreed.json"

    def __init__(
            self,
            cache: TTLCache,
            ttl_minutes: int = 60,
            timeout_sec: int = 10,
    ):
        self.cache = cache
        self.ttl = timedelta(minutes=ttl_minutes)
        self.timeout_sec = timeout_sec

    def get_latest(self) -> Optional[Tuple[int, str]]:
        cache_key = "gold_fng_latest"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        latest: Optional[Tuple[int, str]] = None
        try:
            r = requests.get(self.URL, timeout=self.timeout_sec)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and data:
                latest_date = max(data.keys())
                score = int(data[latest_date])
                latest = (score, classify_fng(score))
        except Exception:
            latest = None

        self.cache.set(cache_key, latest, self.ttl)
        return latest


class CryptoFearGreedClient:
    """Alternative.me FNG: https://api.alternative.me/fng/"""

    URL = "https://api.alternative.me/fng/"

    def __init__(
            self,
            cache: TTLCache,
            ttl_minutes: int = 30,
            timeout_sec: int = 10,
    ):
        self.cache = cache
        self.ttl = timedelta(minutes=ttl_minutes)
        self.timeout_sec = timeout_sec

    def get_latest(self) -> Optional[Tuple[int, str]]:
        cache_key = "crypto_fng_latest"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        latest: Optional[Tuple[int, str]] = None
        try:
            r = requests.get(self.URL, timeout=self.timeout_sec)
            r.raise_for_status()
            data = r.json()
            item = (data.get("data") or [None])[0]
            if isinstance(item, dict):
                score = int(item.get("value"))
                label = str(
                    item.get("value_classification")
                    or classify_fng(score),
                )
                latest = (score, label)
        except Exception:
            latest = None

        self.cache.set(cache_key, latest, self.ttl)
        return latest


# -------------------------------------------------------------------
# CBBI client (Colin Talks Crypto Bitcoin Bull Run Index)
# -------------------------------------------------------------------

class CBBIClient:
    """Fetch the latest CBBI confidence score.

    The CBBI is a composite of ~9 on-chain indicators (MVRV, RHODL,
    Puell Multiple, etc.) that outputs a 0–100 "confidence we're at
    the cycle top" score.

    Source: https://colintalkscrypto.com/cbbi/
    """

    URL = "https://colintalkscrypto.com/cbbi/data/latest/cbbi"

    def __init__(
            self,
            cache: TTLCache,
            ttl_minutes: int = 60,
            timeout_sec: int = 10,
    ):
        self.cache = cache
        self.ttl = timedelta(minutes=ttl_minutes)
        self.timeout_sec = timeout_sec

    def get_latest(self) -> Optional[float]:
        cache_key = "cbbi_latest"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        value: Optional[float] = None
        try:
            r = requests.get(self.URL, timeout=self.timeout_sec)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict):
                if "Confidence" in data:
                    value = round(float(data["Confidence"]) * 100, 1)
                else:
                    latest_key = max(data.keys())
                    raw = data[latest_key]
                    v = float(raw) if not isinstance(raw, dict) else float(
                        raw.get("Confidence", raw.get("confidence", 0)),
                    )
                    # Normalize: if value is 0–1, scale to 0–100
                    value = round(v * 100, 1) if v <= 1.0 else round(v, 1)
        except Exception as exc:
            log.debug("CBBI fetch failed: %s", exc)
            value = None

        self.cache.set(cache_key, value, self.ttl)
        return value


# -------------------------------------------------------------------
# Concrete provider
# -------------------------------------------------------------------

class MarketProvider:
    """Fetch prices (yfinance), VIX, Fear & Greed, and BTC indicators.

    IMPORTANT: All yfinance calls are made sequentially on the calling
    thread (yfinance is NOT thread-safe).  Use ``fetch_all()`` from a
    single background Worker.
    """

    def __init__(self):
        self._cache = TTLCache()
        self._stock_fng = StockFearGreedClient(self._cache, ttl_minutes=60)
        self._gold_fng = GoldFearGreedClient(self._cache, ttl_minutes=60)
        self._crypto_fng = CryptoFearGreedClient(self._cache, ttl_minutes=30)
        self._cbbi = CBBIClient(self._cache, ttl_minutes=5)
        cm_cache_dir = Path("cache") / "coinmetrics"
        self._cm = CoinMetricsClient()
        self._cm_svc = CoinMetricsIndicatorsService(
            self._cm,
            CoinMetricsIndicatorsConfig(
                cache_dir=cm_cache_dir,
                ttl_sec=6 * 3600,
                frequency="1d",
            ),
        )

        # External indicator values (set at runtime by caller)
        self.latest_indicator_values: Dict[str, float] = {}

    # -- yfinance wrappers (NOT thread-safe — call sequentially) ------

    def get_daily_close(
            self, symbol: str, lookback_days: int,
    ) -> pd.Series:
        cache_key = f"daily_close:{symbol}:{lookback_days}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        # Extra buffer for weekends/holidays
        period_days = max(lookback_days + 10, 30)
        df = yf.download(
            symbol,
            period=f"{period_days}d",
            interval="1d",
            auto_adjust=False,
            progress=False,
        )
        if df is None or df.empty:
            s = pd.Series(dtype=float)
        else:
            s = _extract_close(df, symbol).tail(lookback_days)

        self._cache.set(cache_key, s, timedelta(minutes=10))
        return s

    def get_vix_daily(self, lookback_days: int = 45) -> pd.Series:
        cache_key = f"vix:{lookback_days}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        # Use 3mo period to ensure we always get >= 30 trading days
        df = yf.download(
            "^VIX",
            period="3mo",
            interval="1d",
            auto_adjust=False,
            progress=False,
        )

        if df is None or df.empty:
            s = pd.Series(dtype=float)
        else:
            s = _extract_close(df, "^VIX").tail(lookback_days)

        self._cache.set(cache_key, s, timedelta(minutes=10))
        return s

    def get_btc_close(self, lookback_days: int = 120) -> pd.Series:
        """Fetch BTC-USD daily close for indicator calculations."""
        return self.get_daily_close("BTC-USD", lookback_days)

    # -- Non-yfinance fetches (thread-safe, but sequential is fine) ---

    def get_fear_greed(self) -> Dict[str, Optional[Tuple[int, str]]]:
        return {
            "stocks": self._stock_fng.get_latest(),
            "gold": self._gold_fng.get_latest(),
            "crypto": self._crypto_fng.get_latest(),
        }

    def get_indicators(self) -> Dict[str, float]:
        """Calculate / fetch all Bitcoin indicator values.

        Returns a dict mapping indicator key → numeric value.
        Values that cannot be computed are omitted (not set to None).
        """
        values: Dict[str, float] = {}

        # RSI from BTC-USD price data (pure calculation)
        try:
            btc = self.get_btc_close(120)
            rsi = calculate_rsi(btc, period=14)
            if rsi is not None:
                values["rsi"] = rsi
        except Exception as exc:
            log.debug("RSI calculation failed: %s", exc)

        # CBBI from colintalkscrypto.com
        try:
            cbbi = self._cbbi.get_latest()
            if cbbi is not None:
                values["cbbi"] = cbbi
        except Exception as exc:
            log.debug("CBBI fetch failed: %s", exc)

        # MVRV Z + NUPL from CoinMetrics (cached on disk)
        try:
            snap = self._cm_svc.get_dashboard_snapshot(
                asset="btc",
                start_time="2025-01-01",
                force_refresh=False,
            )
            mvrv = snap.get("mvrv_z", {}).get("latest")
            if mvrv is not None:
                values["mvrv_z"] = round(float(mvrv), 3)

            n = snap.get("nupl", {}).get("latest")
            if n is not None:
                values["nupl"] = round(float(n), 4)
        except Exception as exc:
            log.debug("CoinMetrics indicators failed: %s", exc)

        # Merge any externally-set values (MVRV, NUPL, VDD, LTH RP)
        # These require on-chain data from services like Glassnode,
        # CoinMetrics, or CryptoQuant.  Set them via:
        #   provider.latest_indicator_values["mvrv_z"] = 2.1
        values.update(self.latest_indicator_values)

        return values

    # -- Consolidated fetch (run this in ONE background thread) -------

    def fetch_all(self) -> DashboardSnapshot:
        """Fetch ALL dashboard data in a single sequential pass.

        This is the method the GUI should call from its background
        Worker.  All yfinance calls run on the same thread,
        eliminating race conditions.
        """
        # 1) Prices (sequential yfinance calls)
        prices: Dict[str, pd.Series] = {}
        for symbol in PRICE_SYMBOLS:
            try:
                prices[symbol] = self.get_daily_close(symbol, 10)
            except Exception as exc:
                log.warning("Price fetch failed for %s: %s", symbol, exc)
                prices[symbol] = pd.Series(dtype=float)

        # 2) VIX (also yfinance — must be sequential)
        try:
            vix = self.get_vix_daily(45)
        except Exception as exc:
            log.warning("VIX fetch failed: %s", exc)
            vix = pd.Series(dtype=float)

        # 3) Fear & Greed (HTTP, not yfinance — safe either way)
        try:
            fg = self.get_fear_greed()
        except Exception as exc:
            log.warning("F&G fetch failed: %s", exc)
            fg = {}

        # 4) Indicators (BTC price is yfinance, then CBBI is HTTP)
        try:
            indicators = self.get_indicators()
        except Exception as exc:
            log.warning("Indicator fetch failed: %s", exc)
            indicators = {}

        return DashboardSnapshot(
            prices=prices,
            vix=vix,
            fear_greed=fg,
            indicators=indicators,
        )


# -------------------------------------------------------------------
# Data transfer objects
# -------------------------------------------------------------------

@dataclass
class DashboardSnapshot:
    """All data needed for one dashboard refresh cycle."""
    prices: Dict[str, pd.Series] = field(default_factory=dict)
    vix: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    fear_greed: Dict[str, Optional[Tuple[int, str]]] = field(
        default_factory=dict,
    )
    indicators: Dict[str, float] = field(default_factory=dict)


# -------------------------------------------------------------------
# Protocol + spec (for type-checking and DI)
# -------------------------------------------------------------------

class MarketDataProvider(Protocol):
    def fetch_all(self) -> DashboardSnapshot: ...

    latest_indicator_values: Dict[str, float]


@dataclass(frozen=True)
class IndicatorSpec:
    """Describes an indicator tile: key, title, optional unit, color bands."""
    key: str
    title: str
    unit: str = ""
    bands: Tuple[Tuple[float, float, str], ...] = ()


# Default indicator specifications (used by MainWindow)
DEFAULT_INDICATOR_SPECS: List[IndicatorSpec] = [
    IndicatorSpec(
        key="mvrv_z", title="MVRV Z-Score",
        bands=((-10, 0, "green"), (0, 3, "yellow"),
               (3, 7, "orange"), (7, 1e9, "red")),
    ),
    IndicatorSpec(
        key="nupl", title="NUPL",
        bands=((-1, 0, "green"), (0, 0.25, "yellow"),
               (0.25, 0.5, "orange"), (0.5, 1.1, "red")),
    ),
    IndicatorSpec(
        key="rsi", title="RSI",
        bands=((0, 30, "green"), (30, 40, "yellow"),
               (40, 70, "orange"), (70, 101, "red")),
    ),
    IndicatorSpec(
        key="vdd", title="VDD",
        bands=((0, 1, "green"), (1, 2, "yellow"),
               (2, 3, "orange"), (3, 1e9, "red")),
    ),
    IndicatorSpec(
        key="lth_rp_gap", title="Price vs LTH RP", unit="%",
        bands=((-1000, -5, "green"), (-5, 5, "yellow"),
               (5, 1000, "orange")),
    ),
    IndicatorSpec(
        key="cbbi", title="CBBI",
        bands=((0, 16, "green"), (16, 60, "yellow"),
               (60, 80, "orange"), (80, 101, "red")),
    ),
]
