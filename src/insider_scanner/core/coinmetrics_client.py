from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Union

import pandas as pd
import requests

from insider_scanner.utils.logging import get_logger

log = get_logger("coinmetrics_client")

JSON = Dict[str, Any]


@dataclass(frozen=True)
class CoinMetricsClientConfig:
    # Community API v4:
    base_url: str = "https://community-api.coinmetrics.io/v4"
    timeout_sec: int = 20
    max_retries: int = 5
    backoff_base_sec: float = 0.8
    backoff_jitter_sec: float = 0.25
    user_agent: str = "CoinMetricsClient/1.0 (requests)"


class CoinMetricsClient:
    """
    Minimal CoinMetrics API v4 client (community endpoint by default).

    Primary endpoint:
      GET /timeseries/asset-metrics

    Pagination:
      - response may include "next_page_token"
      - pass it back as query param "next_page_token"
    """

    def __init__(self, cfg: Optional[CoinMetricsClientConfig] = None):
        self.cfg = cfg or CoinMetricsClientConfig()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.cfg.user_agent})

    # -------------------------
    # Public endpoints
    # -------------------------
    def get_asset_metrics(
            self,
            assets: Union[str, Sequence[str]],
            metrics: Union[str, Sequence[str]],
            frequency: str = "1d",
            start_time: Optional[str] = None,
            end_time: Optional[str] = None,
            page_size: int = 1000,
            limit_per_asset: Optional[int] = None,
            sort: Optional[str] = "time",
            **extra_params: Any,
    ) -> pd.DataFrame:
        """
        Fetch /timeseries/asset-metrics with automatic pagination.
        Returns DataFrame indexed by UTC 'time' if present.

        Typical call:
          get_asset_metrics("btc", ["CapMrktCurUSD","CapRealUSD"], frequency="1d", start_time="2020-01-01")
        """
        params: Dict[str, Any] = {
            "assets": assets if isinstance(assets, str) else ",".join(assets),
            "metrics": metrics if isinstance(metrics, str) else ",".join(metrics),
            "frequency": frequency,
            "page_size": int(page_size),
        }
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time
        if limit_per_asset is not None:
            params["limit_per_asset"] = int(limit_per_asset)
        if sort:
            params["sort"] = sort

        params.update({k: v for k, v in extra_params.items() if v is not None})

        rows = self._paginate("/timeseries/asset-metrics", params)

        df = pd.DataFrame(rows)
        if df.empty:
            return df

        if "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
            df = df.dropna(subset=["time"])

        # attempt numeric conversion for metric columns
        # errors="coerce" is essential: CoinMetrics returns the string
        # "NaN" for unavailable values, which pd.to_numeric rejects
        # without coerce (ValueError: Unable to parse string "NaN")
        for c in df.columns:
            if c in ("asset", "time"):
                continue
            df[c] = pd.to_numeric(df[c], errors="coerce")

        if "time" in df.columns:
            if "asset" in df.columns:
                df = df.sort_values(["asset", "time"])
            else:
                df = df.sort_values(["time"])
            df = df.set_index("time")

        return df

    def catalog_assets(self) -> pd.DataFrame:
        j = self._get_json("/catalog/assets", params={})
        return pd.DataFrame(j.get("data", []))

    def catalog_asset_metrics(self) -> pd.DataFrame:
        j = self._get_json("/catalog/asset-metrics", params={})
        return pd.DataFrame(j.get("data", []))

    # -------------------------
    # Internals
    # -------------------------
    def _paginate(self, path: str, params: Dict[str, Any]) -> List[JSON]:
        out: List[JSON] = []
        next_token: Optional[str] = None

        while True:
            p = dict(params)
            if next_token:
                p["next_page_token"] = next_token

            j = self._get_json(path, params=p)
            data = j.get("data", [])
            if not isinstance(data, list):
                raise RuntimeError(f"Unexpected response format: 'data' is not a list ({path})")

            out.extend(data)

            next_token = j.get("next_page_token")
            if not next_token:
                break

        return out

    def _get_json(self, path: str, params: Dict[str, Any]) -> JSON:
        url = self.cfg.base_url.rstrip("/") + path

        last_err: Optional[Exception] = None
        for attempt in range(self.cfg.max_retries + 1):
            try:
                r = self.session.get(url, params=params, timeout=self.cfg.timeout_sec)

                # Fail immediately on auth errors (no point retrying).
                # raise_for_status() is called OUTSIDE the retry
                # exception handler so HTTPError propagates to caller.
                if r.status_code in (401, 403):
                    r.raise_for_status()

                # Retry on rate limits and transient server errors
                if r.status_code in (429, 500, 502, 503, 504):
                    raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")

                r.raise_for_status()
                j = r.json()
                if not isinstance(j, dict):
                    raise RuntimeError("Non-object JSON response")

                # some APIs return {"error": ...}
                if j.get("error"):
                    raise RuntimeError(f"API error: {j['error']}")

                return j

            except requests.HTTPError:
                # Auth errors (401, 403) — don't retry, propagate now
                raise
            except Exception as e:
                last_err = e
                if attempt >= self.cfg.max_retries:
                    break
                sleep_s = (self.cfg.backoff_base_sec * (2 ** attempt)) + random.uniform(0, self.cfg.backoff_jitter_sec)
                time.sleep(sleep_s)

        raise RuntimeError(f"CoinMetrics request failed after retries: {last_err}")
