"""BGeometrics free Bitcoin on-chain indicator API client.

BGeometrics (bitcoin-data.com) provides pre-calculated on-chain
metrics such as MVRV Z-Score, NUPL, and VDD via a free REST API.

Free tier limits: 8 requests per hour.  Since on-chain metrics
update only once per day, we cache responses for 6 hours — meaning
at most one API call per metric per session.

Response format (plain text, one row per day):
    2026-02-15 1771113600 0.5243
    ^date      ^unix_ts   ^value

Some endpoints use European comma decimals (e.g. VDD raw values),
which the parser handles transparently.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests

from datetime import timedelta

log = logging.getLogger(__name__)


# -------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------

@dataclass(frozen=True)
class BGeometricsConfig:
    base_url: str = "https://bitcoin-data.com/api/v1"
    timeout_sec: int = 20
    user_agent: str = "InsiderScanner/1.0"


# Available indicator endpoints.
# key → (url_path, human_label)
INDICATOR_ENDPOINTS: Dict[str, Tuple[str, str]] = {
    "mvrv_z": ("/mvrv-zscore", "MVRV Z-Score"),
    "nupl": ("/nupl", "NUPL"),
    # VDD endpoint returns raw CDD-USD values, not the VDD Multiple.
    # Uncomment if BGeometrics adds a vdd-multiple endpoint:
    # "vdd": ("/vdd", "VDD Multiple"),
}


# -------------------------------------------------------------------
# Parser
# -------------------------------------------------------------------

def parse_text_timeseries(text: str) -> List[Tuple[str, float]]:
    """Parse BGeometrics plain-text response into (date, value) pairs.

    Each line has the format:
        YYYY-MM-DD  unix_timestamp  value

    The value may use a European comma decimal (e.g. ``1234,56``),
    which is converted to a dot decimal before parsing.

    Blank lines and lines that don't match the expected 3-column
    format are silently skipped.
    """
    rows: List[Tuple[str, float]] = []
    for line in text.strip().splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        date_str = parts[0]
        raw_value = parts[2]
        # Handle European comma decimal: "1234,56" → "1234.56"
        raw_value = raw_value.replace(",", ".")
        try:
            value = float(raw_value)
        except ValueError:
            continue
        rows.append((date_str, value))
    return rows


# -------------------------------------------------------------------
# Client
# -------------------------------------------------------------------

# Sentinel to distinguish "cached None" from "cache miss"
_FETCH_FAILED = "__bg_fetch_failed__"


class BGeometricsClient:
    """Fetch pre-calculated Bitcoin indicators from BGeometrics.

    Designed for the dashboard: call ``get_latest()`` for a single
    indicator or ``get_all_latest()`` to fetch every configured
    indicator in one pass (sequential, respecting rate limits).

    Results are cached in an in-memory TTL cache for 6 hours,
    so repeated calls within a session never hit the API twice.
    """

    def __init__(
        self,
        cache: Any,
        cfg: Optional[BGeometricsConfig] = None,
        ttl_hours: int = 6,
    ):
        """Create a BGeometrics client.

        Args:
            cache: Object with ``get(key)`` and ``set(key, value, ttl)``
                   methods (e.g. ``TTLCache`` from dashboard module).
            cfg: Optional configuration override.
            ttl_hours: Hours to cache successful responses.
        """
        self.cfg = cfg or BGeometricsConfig()
        self.cache = cache
        self.ttl = timedelta(hours=ttl_hours)
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": self.cfg.user_agent})

    def get_latest(self, key: str) -> Optional[float]:
        """Fetch the latest value for a single indicator by key.

        Returns None if the key is unknown, the API fails, or
        the response contains no data.
        """
        endpoint = INDICATOR_ENDPOINTS.get(key)
        if endpoint is None:
            log.debug("Unknown BGeometrics indicator key: %s", key)
            return None

        cache_key = f"bgeometrics:{key}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            # Sentinel means "we tried and failed" — return None
            return None if cached is _FETCH_FAILED else cached

        url_path, label = endpoint
        value = self._fetch_latest_value(url_path, label)

        if value is not None:
            self.cache.set(cache_key, value, self.ttl)
        else:
            # Cache failure briefly to avoid hammering API
            self.cache.set(cache_key, _FETCH_FAILED, timedelta(minutes=30))

        return value

    def get_all_latest(self) -> Dict[str, float]:
        """Fetch the latest value for every configured indicator.

        Returns a dict mapping indicator key → float value.
        Indicators that fail to fetch are omitted (not set to None).
        """
        results: Dict[str, float] = {}
        for key in INDICATOR_ENDPOINTS:
            value = self.get_latest(key)
            if value is not None:
                results[key] = value
        return results

    # -- internals ---------------------------------------------------

    def _fetch_latest_value(
        self, url_path: str, label: str,
    ) -> Optional[float]:
        """HTTP GET → parse text → return last row's value."""
        url = self.cfg.base_url.rstrip("/") + url_path
        try:
            r = self._session.get(url, timeout=self.cfg.timeout_sec)
            r.raise_for_status()
            rows = parse_text_timeseries(r.text)
            if not rows:
                log.warning("BGeometrics %s: empty response", label)
                return None
            date_str, value = rows[-1]
            log.debug("BGeometrics %s: %s = %s", label, date_str, value)
            return round(value, 6)
        except requests.RequestException as exc:
            log.warning("BGeometrics %s fetch failed: %s", label, exc)
            return None
        except Exception as exc:
            log.warning("BGeometrics %s parse error: %s", label, exc)
            return None
