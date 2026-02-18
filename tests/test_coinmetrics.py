"""Tests for CoinMetrics indicators service and cached client."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
import requests

from insider_scanner.core.coinmetrics_indicators_service import (
    CoinMetricsIndicatorsConfig,
    CoinMetricsIndicatorsService,
    mvrv_z_score,
    nupl,
)
from insider_scanner.core.coinmetrics_cached_client import (
    CoinMetricsCachedClient,
    CoinMetricsCacheConfig,
)
from insider_scanner.core.coinmetrics_client import CoinMetricsClient


# -------------------------------------------------------------------
# Pure-math indicator functions
# -------------------------------------------------------------------

class TestNupl:
    def test_basic(self):
        mc = pd.Series([100.0, 200.0, 300.0], name="mc")
        rc = pd.Series([80.0, 150.0, 200.0], name="rc")
        result = nupl(mc, rc)
        # NUPL = (mc - rc) / mc → [0.2, 0.25, 0.333...]
        assert len(result) == 3
        assert abs(result.iloc[0] - 0.2) < 0.01

    def test_handles_zero_market_cap(self):
        mc = pd.Series([0.0, 100.0])
        rc = pd.Series([0.0, 80.0])
        result = nupl(mc, rc)
        # mc=0 → NaN (division by zero)
        assert np.isnan(result.iloc[0])
        assert abs(result.iloc[1] - 0.2) < 0.01

    def test_name(self):
        mc = pd.Series([100.0])
        rc = pd.Series([80.0])
        assert nupl(mc, rc).name == "nupl"


class TestMvrvZScore:
    def _make_cap_data(self, n: int = 500) -> tuple[pd.Series, pd.Series]:
        """Generate synthetic market cap and realized cap data."""
        idx = pd.date_range("2020-01-01", periods=n, freq="D")
        mc = pd.Series(np.linspace(100e9, 500e9, n), index=idx)
        rc = pd.Series(np.linspace(80e9, 300e9, n), index=idx)
        return mc, rc

    def test_produces_values(self):
        mc, rc = self._make_cap_data(500)
        z = mvrv_z_score(mc, rc)
        # With 500 data points and window=365, should have values
        valid = z.dropna()
        assert len(valid) > 0

    def test_insufficient_data_mostly_nan(self):
        mc, rc = self._make_cap_data(20)
        z = mvrv_z_score(mc, rc, sigma_window=365)
        # Only 20 data points, min_periods=36 → all NaN
        assert z.dropna().empty

    def test_name(self):
        mc, rc = self._make_cap_data(500)
        assert mvrv_z_score(mc, rc).name == "mvrv_z_score"


# -------------------------------------------------------------------
# CoinMetricsIndicatorsService
# -------------------------------------------------------------------

class TestCoinMetricsIndicatorsService:
    @pytest.fixture
    def mock_cm(self):
        return MagicMock(spec=CoinMetricsClient)

    @pytest.fixture
    def service(self, mock_cm, tmp_path):
        cfg = CoinMetricsIndicatorsConfig(
            cache_dir=tmp_path / "cm_cache",
            ttl_sec=3600,
        )
        return CoinMetricsIndicatorsService(mock_cm, cfg)

    def _caps_df(self, n=100) -> pd.DataFrame:
        """DataFrame with both required columns."""
        idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
        return pd.DataFrame({
            "CapMrktCurUSD": np.linspace(100e9, 500e9, n),
            "CapRealUSD": np.linspace(80e9, 300e9, n),
        }, index=idx)

    def test_get_caps_returns_both_columns(self, service, mock_cm):
        df = self._caps_df(400)
        mock_cm.get_asset_metrics.return_value = df

        result = service.get_caps("btc", start_time="2024-01-01")
        assert "CapMrktCurUSD" in result.columns
        assert "CapRealUSD" in result.columns

    def test_get_caps_missing_realized_cap_logs_warning(
        self, service, mock_cm, caplog,
    ):
        """If API returns only CapMrktCurUSD, log warning & return empty."""
        idx = pd.date_range("2024-01-01", periods=50, freq="D", tz="UTC")
        partial_df = pd.DataFrame({
            "CapMrktCurUSD": np.linspace(100e9, 200e9, 50),
        }, index=idx)
        mock_cm.get_asset_metrics.return_value = partial_df

        import logging
        with caplog.at_level(logging.WARNING):
            result = service.get_caps("btc", start_time="2024-01-01")

        assert result.empty
        assert "did not return columns" in caplog.text

    def test_get_caps_empty_response(self, service, mock_cm, caplog):
        mock_cm.get_asset_metrics.return_value = pd.DataFrame()

        import logging
        with caplog.at_level(logging.WARNING):
            result = service.get_caps("btc")

        assert result.empty
        assert "empty data" in caplog.text

    def test_compute_mvrv_z_with_data(self, service, mock_cm):
        df = self._caps_df(500)
        mock_cm.get_asset_metrics.return_value = df

        result = service.compute_mvrv_z("btc", start_time="2024-01-01")
        valid = result.dropna()
        assert len(valid) > 0

    def test_compute_nupl_with_data(self, service, mock_cm):
        df = self._caps_df(100)
        mock_cm.get_asset_metrics.return_value = df

        result = service.compute_nupl("btc", start_time="2024-01-01")
        valid = result.dropna()
        assert len(valid) > 0

    def test_snapshot_returns_latest_values(self, service, mock_cm):
        df = self._caps_df(500)
        mock_cm.get_asset_metrics.return_value = df

        snap = service.get_dashboard_snapshot(
            asset="btc", start_time="2024-01-01",
        )
        assert snap["mvrv_z"]["latest"] is not None
        assert snap["nupl"]["latest"] is not None

    def test_snapshot_missing_data_returns_none(self, service, mock_cm):
        mock_cm.get_asset_metrics.return_value = pd.DataFrame()

        snap = service.get_dashboard_snapshot("btc")
        assert snap["mvrv_z"]["latest"] is None
        assert snap["nupl"]["latest"] is None


# -------------------------------------------------------------------
# CoinMetricsCachedClient — cache poisoning prevention
# -------------------------------------------------------------------

class TestCachedClientCachePoisoning:
    @pytest.fixture
    def mock_cm(self):
        return MagicMock(spec=CoinMetricsClient)

    @pytest.fixture
    def cached_client(self, mock_cm, tmp_path):
        cfg = CoinMetricsCacheConfig(
            cache_dir=tmp_path / "cache",
            ttl_sec=3600,
        )
        return CoinMetricsCachedClient(mock_cm, cfg)

    def test_empty_result_not_cached(self, cached_client, mock_cm):
        """Empty API responses should NOT be written to disk cache."""
        mock_cm.get_asset_metrics.return_value = pd.DataFrame()

        result = cached_client.get_asset_metrics_df(
            assets="btc", metrics="CapMrktCurUSD",
        )
        assert result.empty

        # Second call should hit the API again, not serve cached empty
        mock_cm.get_asset_metrics.return_value = pd.DataFrame(
            {"CapMrktCurUSD": [100.0]},
            index=pd.DatetimeIndex(["2025-01-01"], name="time"),
        )
        result2 = cached_client.get_asset_metrics_df(
            assets="btc", metrics="CapMrktCurUSD",
        )
        assert not result2.empty
        assert mock_cm.get_asset_metrics.call_count == 2

    def test_valid_result_is_cached(self, cached_client, mock_cm):
        """Non-empty responses SHOULD be cached."""
        idx = pd.DatetimeIndex(
            pd.to_datetime(["2025-01-01", "2025-01-02"]),
            name="time",
        )
        df = pd.DataFrame({"CapMrktCurUSD": [100.0, 200.0]}, index=idx)
        mock_cm.get_asset_metrics.return_value = df

        cached_client.get_asset_metrics_df(
            assets="btc", metrics="CapMrktCurUSD",
        )
        cached_client.get_asset_metrics_df(
            assets="btc", metrics="CapMrktCurUSD",
        )
        # Second call should hit cache, not API
        assert mock_cm.get_asset_metrics.call_count == 1


# -------------------------------------------------------------------
# CoinMetricsClient — 403 fail-fast
# -------------------------------------------------------------------

class TestCoinMetricsClient403:
    def test_403_fails_immediately_no_retries(self):
        """403 Forbidden should raise immediately, not retry 5 times."""
        from insider_scanner.core.coinmetrics_client import (
            CoinMetricsClient,
            CoinMetricsClientConfig,
        )
        from unittest.mock import patch

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.raise_for_status.side_effect = requests.HTTPError(
            "403 Client Error: Forbidden",
        )

        cfg = CoinMetricsClientConfig(max_retries=5)
        client = CoinMetricsClient(cfg)

        with patch.object(client.session, "get", return_value=mock_response) as mock_get:
            with pytest.raises(requests.HTTPError, match="403"):
                client._get_json("/test", {})

            # Key assertion: only called ONCE (no retries)
            assert mock_get.call_count == 1
