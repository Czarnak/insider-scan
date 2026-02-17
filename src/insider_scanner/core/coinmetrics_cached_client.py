from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Union

import pandas as pd

from insider_scanner.core.coinmetrics_client import CoinMetricsClient
from insider_scanner.utils.caching import cache_key, get_cached, set_cached
from insider_scanner.utils.logging import get_logger

log = get_logger("coinmetrics_cached")

JSON = Dict[str, Any]


@dataclass(frozen=True)
class CoinMetricsCacheConfig:
    cache_dir: Path
    ttl_sec: int  # DEFAULT_CACHE_TTL


class CoinMetricsCachedClient:
    """
    Wraps CoinMetricsClient with your existing text cache (caching.py).
    Stores JSON responses as raw string: key.txt + key.meta.
    """

    def __init__(self, cm: CoinMetricsClient, cfg: CoinMetricsCacheConfig):
        self.cm = cm
        self.cfg = cfg
        self.cfg.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_asset_metrics_df(
            self,
            assets: Union[str, Sequence[str]],
            metrics: Union[str, Sequence[str]],
            frequency: str = "1d",
            start_time: Optional[str] = None,
            end_time: Optional[str] = None,
            page_size: int = 1000,
            limit_per_asset: Optional[int] = None,
            sort: Optional[str] = "time",
            force_refresh: bool = False,
            **extra_params: Any,
    ) -> pd.DataFrame:
        """
        Cached equivalent of CoinMetricsClient.get_asset_metrics(...),
        but caches the final combined JSON payload (data + next_page_token=None).
        """
        params = {
            "assets": assets if isinstance(assets, str) else ",".join(assets),
            "metrics": metrics if isinstance(metrics, str) else ",".join(metrics),
            "frequency": frequency,
            "start_time": start_time,
            "end_time": end_time,
            "page_size": page_size,
            "limit_per_asset": limit_per_asset,
            "sort": sort,
            **extra_params,
        }
        # remove None for stable key
        params = {k: v for k, v in params.items() if v is not None}

        key = cache_key("coinmetrics:" + json.dumps(params, sort_keys=True))

        if not force_refresh:
            cached = get_cached(self.cfg.cache_dir, key, ttl=self.cfg.ttl_sec)
            if cached is not None:
                try:
                    j = json.loads(cached)
                    return self._json_to_df(j)
                except Exception as e:
                    log.debug("Cache parse failed for %s: %s", key, e)

        # fetch via underlying client (handles pagination)
        df = self.cm.get_asset_metrics(
            assets=assets,
            metrics=metrics,
            frequency=frequency,
            start_time=start_time,
            end_time=end_time,
            page_size=page_size,
            limit_per_asset=limit_per_asset,
            sort=sort,
            **extra_params,
        )

        # serialize a minimal JSON form for cache
        j = self._df_to_json(df)
        set_cached(self.cfg.cache_dir, key, json.dumps(j))
        return df

    @staticmethod
    def _json_to_df(j: JSON) -> pd.DataFrame:
        data = j.get("data", [])
        df = pd.DataFrame(data)
        if df.empty:
            return df

        if "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
            df = df.dropna(subset=["time"]).sort_values(["asset", "time"] if "asset" in df.columns else ["time"])
            df = df.set_index("time")

        for c in df.columns:
            if c in ("asset",):
                continue
            df[c] = pd.to_numeric(df[c])

        return df

    @staticmethod
    def _df_to_json(df: pd.DataFrame) -> JSON:
        if df is None or df.empty:
            return {"data": []}

        out = df.copy()
        if out.index.name == "time":
            out = out.reset_index()

        if "time" in out.columns:
            out["time"] = pd.to_datetime(out["time"], utc=True, errors="coerce").dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        return {"data": out.to_dict(orient="records")}
