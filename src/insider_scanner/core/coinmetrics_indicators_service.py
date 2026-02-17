from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any, Literal

import numpy as np
import pandas as pd

from insider_scanner.core.coinmetrics_cached_client import CoinMetricsCachedClient, CoinMetricsCacheConfig
from insider_scanner.core.coinmetrics_client import CoinMetricsClient


def nupl(market_cap: pd.Series, realized_cap: pd.Series) -> pd.Series:
    mc, rc = market_cap.align(realized_cap, join="inner")
    out = (mc - rc) / mc.replace(0.0, np.nan)
    out.name = "nupl"
    return out


def mvrv_z_score(
        market_cap: pd.Series,
        realized_cap: pd.Series,
        sigma_window: int = 365,
        sigma_method: Literal["rolling", "expanding"] = "rolling",
) -> pd.Series:
    mc, rc = market_cap.align(realized_cap, join="inner")
    if sigma_method == "rolling":
        sigma = mc.rolling(sigma_window, min_periods=max(30, sigma_window // 10)).std()
    else:
        sigma = mc.expanding(min_periods=30).std()
    z = (mc - rc) / sigma.replace(0.0, np.nan)
    z.name = "mvrv_z_score"
    return z


@dataclass(frozen=True)
class CoinMetricsIndicatorsConfig:
    cache_dir: Path
    ttl_sec: int = 6 * 3600
    frequency: str = "1d"

    tail_points: int = 800  # ~2+ years


class CoinMetricsIndicatorsService:
    """
    Dashboard-focused service:
    - fetches required raw metrics (cached)
    - computes indicators
    - returns snapshot dict (easy to plug into tiles)
    """

    def __init__(self, cm: CoinMetricsClient, cfg: CoinMetricsIndicatorsConfig):
        self.cfg = cfg
        self.cm_cached = CoinMetricsCachedClient(
            cm,
            CoinMetricsCacheConfig(cache_dir=cfg.cache_dir, ttl_sec=cfg.ttl_sec),
        )

    # ---- Raw data getters
    def get_caps(
            self,
            asset: str = "btc",
            start_time: Optional[str] = None,
            end_time: Optional[str] = None,
            force_refresh: bool = False,
    ) -> pd.DataFrame:
        """
        Market cap + realized cap for MVRV/NUPL.
        """
        df = self.cm_cached.get_asset_metrics_df(
            assets=asset,
            metrics=["CapMrktCurUSD", "CapRealUSD"],
            frequency=self.cfg.frequency,
            start_time=start_time,
            end_time=end_time,
            force_refresh=force_refresh,
        )
        if df is None or df.empty:
            return pd.DataFrame()

        cols = [c for c in ["CapMrktCurUSD", "CapRealUSD"] if c in df.columns]
        out = df[cols].dropna(how="all").sort_index()
        return out.tail(self.cfg.tail_points)

    # ---- Computations
    def compute_nupl(
            self, asset: str = "btc", start_time: Optional[str] = None, end_time: Optional[str] = None,
            force_refresh: bool = False
    ) -> pd.Series:
        df = self.get_caps(asset, start_time, end_time, force_refresh)
        if df.empty or "CapMrktCurUSD" not in df or "CapRealUSD" not in df:
            return pd.Series(dtype=float, name="nupl")
        return nupl(df["CapMrktCurUSD"], df["CapRealUSD"])

    def compute_mvrv_z(
            self,
            asset: str = "btc",
            start_time: Optional[str] = None,
            end_time: Optional[str] = None,
            force_refresh: bool = False,
            sigma_window: int = 365,
            sigma_method: Literal["rolling", "expanding"] = "rolling",
    ) -> pd.Series:
        df = self.get_caps(asset, start_time, end_time, force_refresh)
        if df.empty or "CapMrktCurUSD" not in df or "CapRealUSD" not in df:
            return pd.Series(dtype=float, name="mvrv_z_score")
        return mvrv_z_score(df["CapMrktCurUSD"], df["CapRealUSD"], sigma_window=sigma_window, sigma_method=sigma_method)

    # ---- Dashboard API
    def get_dashboard_snapshot(
            self,
            asset: str = "btc",
            start_time: Optional[str] = "2016-01-01",
            end_time: Optional[str] = None,
            force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Returns dict ready to plug into Dashboard tiles.

        Example output:
          {
            "nupl": {"latest": 0.12, "series": <pd.Series>},
            "mvrv_z": {"latest": 0.4, "series": <pd.Series>},
          }
        """
        z = self.compute_mvrv_z(asset, start_time, end_time, force_refresh)
        n = self.compute_nupl(asset, start_time, end_time, force_refresh)

        def _latest(s: pd.Series) -> Optional[float]:
            if s is None or s.empty:
                return None
            v = s.dropna()
            if v.empty:
                return None
            return float(v.iloc[-1])

        return {
            "mvrv_z": {"latest": _latest(z), "series": z},
            "nupl": {"latest": _latest(n), "series": n},
        }
