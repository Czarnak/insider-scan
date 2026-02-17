# data_clients.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, Dict, Any, Protocol

import pandas as pd
import requests
import yfinance as yf


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _extract_close(df: pd.DataFrame, symbol: str) -> pd.Series:
    """
    Works for both:
    - flat columns: ["Open","High","Low","Close","Adj Close","Volume"]
    - MultiIndex columns: [("Close","^VIX"), ...] (yfinance group_by='column')
    """
    if df is None or df.empty:
        return pd.Series(dtype=float)

    # MultiIndex: ("Close", SYMBOL)
    if isinstance(df.columns, pd.MultiIndex):
        if ("Close", symbol) in df.columns:
            s = df[("Close", symbol)]
        elif ("Adj Close", symbol) in df.columns:
            s = df[("Adj Close", symbol)]
        else:
            # fallback: find any level containing Close
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


@dataclass
class CacheEntry:
    value: Any
    expires_at: datetime


class TTLCache:
    def __init__(self):
        self._store: Dict[str, CacheEntry] = {}

    def get(self, key: str) -> Optional[Any]:
        now = _utcnow()
        entry = self._store.get(key)
        if entry and now < entry.expires_at:
            return entry.value
        return None

    def set(self, key: str, value: Any, ttl: timedelta) -> None:
        self._store[key] = CacheEntry(value=value, expires_at=_utcnow() + ttl)


def classify_fng(v: int) -> str:
    if v < 25:
        return "Extreme Fear"
    if v < 50:
        return "Fear"
    if v < 75:
        return "Greed"
    return "Extreme Greed"


class GoldFearGreedClient:
    """
    JM Bullion JSON: {"YYYY-MM-DD": score, ...}
    """
    URL = "https://cdn.jmbullion.com/fearandgreed/fearandgreed.json"

    def __init__(self, cache: TTLCache, ttl_minutes: int = 60, timeout_sec: int = 10):
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
                latest_date = max(data.keys())  # ISO dates sort lexicographically
                score = int(data[latest_date])
                latest = (score, classify_fng(score))
        except Exception:
            latest = None

        self.cache.set(cache_key, latest, self.ttl)
        return latest


class CryptoFearGreedClient:
    """
    Alternative.me FNG:
    https://api.alternative.me/fng/
    """
    URL = "https://api.alternative.me/fng/"

    def __init__(self, cache: TTLCache, ttl_minutes: int = 30, timeout_sec: int = 10):
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
            # expected: {"data":[{"value":"47","value_classification":"Fear",...}],...}
            item = (data.get("data") or [None])[0]
            if isinstance(item, dict):
                score = int(item.get("value"))
                label = str(item.get("value_classification") or classify_fng(score))
                latest = (score, label)
        except Exception:
            latest = None

        self.cache.set(cache_key, latest, self.ttl)
        return latest


@dataclass
class LatestIndicators:
    # dopasuj do swoich kluczy w DashboardTab
    values: Dict[str, float]


class MarketProvider:
    """
    - ceny i VIX: yfinance
    - F&G gold: JM Bullion JSON
    - F&G crypto: Alternative.me
    - F&G stocks: opcjonalnie (tu None)
    """

    def __init__(self):
        self._cache = TTLCache()
        self._gold_fng = GoldFearGreedClient(self._cache, ttl_minutes=60)
        self._crypto_fng = CryptoFearGreedClient(self._cache, ttl_minutes=30)

        # tu możesz w runtime aktualizować swoje wskaźniki
        self.latest_indicator_values: Dict[str, float] = {}

    def get_daily_close(self, symbol: str, lookback_days: int) -> pd.Series:
        cache_key = f"daily_close:{symbol}:{lookback_days}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        # + kilka dni bufora na weekendy/święta
        period_days = max(lookback_days + 10, 30)
        df = yf.download(symbol, period="5d", interval="1d", auto_adjust=False, progress=True)
        if df is None or df.empty:
            s = pd.Series(dtype=float)
        else:
            s = _extract_close(df, symbol).tail(lookback_days)

        self._cache.set(cache_key, s, timedelta(minutes=10))
        return s

    def get_vix_intraday_or_daily(self, lookback_days: int) -> pd.Series:
        cache_key = f"vix:{lookback_days}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        df = yf.download("^VIX", period="1mo", interval="1d", auto_adjust=False, progress=False)

        if df is None or df.empty:
            s = pd.Series(dtype=float)
        else:
            s = _extract_close(df, "^VIX").tail(lookback_days)

        self._cache.set(cache_key, s, timedelta(minutes=1))
        return s

    def get_fear_greed(self) -> Dict[str, Optional[Tuple[int, str]]]:
        return {
            "stocks": None,  # jeśli dodasz własne źródło, podmień
            "gold": self._gold_fng.get_latest(),
            "crypto": self._crypto_fng.get_latest(),
        }


class MarketDataProvider(Protocol):
    def get_daily_close(self, symbol: str, lookback_days: int) -> pd.Series: ...

    def get_vix_intraday_or_daily(self, lookback_days: int) -> pd.Series: ...

    def get_fear_greed(self) -> Dict[str, Optional[Tuple[int, str]]]: ...

    # optional (Dashboard reads it if present)
    latest_indicator_values: Dict[str, float]


@dataclass(frozen=True)
class IndicatorSpec:
    key: str
    title: str
    unit: str = ""
    bands: Tuple[Tuple[float, float, str], ...] = ()
