"""Tests for BGeometrics free Bitcoin on-chain indicator client."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
import requests

from insider_scanner.core.bgeometrics_client import (
    BGeometricsClient,
    BGeometricsConfig,
    INDICATOR_ENDPOINTS,
    parse_text_timeseries,
)
from insider_scanner.core.dashboard import TTLCache


# -------------------------------------------------------------------
# parse_text_timeseries
# -------------------------------------------------------------------

class TestParseTextTimeseries:
    SAMPLE = (
        "2026-02-14 1771027200 0.4931\n"
        "2026-02-15 1771113600 0.5243\n"
    )

    def test_basic_parsing(self):
        rows = parse_text_timeseries(self.SAMPLE)
        assert len(rows) == 2
        assert rows[0] == ("2026-02-14", 0.4931)
        assert rows[1] == ("2026-02-15", 0.5243)

    def test_european_comma_decimal(self):
        text = "2026-02-15 1771113600 732402853686,7\n"
        rows = parse_text_timeseries(text)
        assert len(rows) == 1
        assert rows[0] == ("2026-02-15", 732402853686.7)

    def test_blank_lines_skipped(self):
        text = "2026-02-14 1771027200 0.49\n\n\n2026-02-15 1771113600 0.52\n"
        rows = parse_text_timeseries(text)
        assert len(rows) == 2

    def test_malformed_lines_skipped(self):
        text = (
            "2026-02-14 1771027200 0.49\n"
            "bad line\n"
            "only two columns\n"
            "2026-02-15 1771113600 0.52\n"
        )
        rows = parse_text_timeseries(text)
        assert len(rows) == 2

    def test_non_numeric_value_skipped(self):
        text = "2026-02-14 1771027200 abc\n"
        rows = parse_text_timeseries(text)
        assert len(rows) == 0

    def test_empty_string(self):
        assert parse_text_timeseries("") == []

    def test_negative_values(self):
        text = "2026-02-14 1771027200 -0.15\n"
        rows = parse_text_timeseries(text)
        assert rows[0][1] == -0.15

    def test_high_precision_preserved(self):
        text = "2026-02-17 1771286400 0.20382201292732535\n"
        rows = parse_text_timeseries(text)
        assert abs(rows[0][1] - 0.20382201292732535) < 1e-15


# -------------------------------------------------------------------
# BGeometricsClient
# -------------------------------------------------------------------

class TestBGeometricsClient:
    MVRV_RESPONSE = (
        "2026-02-14 1771027200 0.4931\n"
        "2026-02-15 1771113600 0.5243\n"
    )
    NUPL_RESPONSE = (
        "2026-02-16 1771200000 0.2070672777240897\n"
        "2026-02-17 1771286400 0.20382201292732535\n"
    )

    @pytest.fixture
    def cache(self):
        return TTLCache()

    @pytest.fixture
    def client(self, cache):
        return BGeometricsClient(cache, ttl_hours=6)

    def _mock_response(self, text, status_code=200):
        mock = MagicMock()
        mock.text = text
        mock.status_code = status_code
        mock.raise_for_status = MagicMock()
        if status_code >= 400:
            mock.raise_for_status.side_effect = requests.HTTPError(
                f"{status_code} Error"
            )
        return mock

    def test_get_latest_mvrv(self, client):
        with patch.object(
            client._session, "get",
            return_value=self._mock_response(self.MVRV_RESPONSE),
        ):
            value = client.get_latest("mvrv_z")

        assert value == 0.5243

    def test_get_latest_nupl(self, client):
        with patch.object(
            client._session, "get",
            return_value=self._mock_response(self.NUPL_RESPONSE),
        ):
            value = client.get_latest("nupl")

        assert value is not None
        assert abs(value - 0.203822) < 0.001

    def test_get_latest_caches_result(self, client):
        mock_resp = self._mock_response(self.MVRV_RESPONSE)
        with patch.object(client._session, "get", return_value=mock_resp) as mock_get:
            v1 = client.get_latest("mvrv_z")
            v2 = client.get_latest("mvrv_z")

        # Only one HTTP call — second hit cache
        assert mock_get.call_count == 1
        assert v1 == v2

    def test_get_latest_unknown_key_returns_none(self, client):
        assert client.get_latest("nonexistent_metric") is None

    def test_get_latest_http_error_returns_none(self, client):
        with patch.object(
            client._session, "get",
            return_value=self._mock_response("", status_code=429),
        ):
            value = client.get_latest("mvrv_z")

        assert value is None

    def test_get_latest_empty_response_returns_none(self, client):
        with patch.object(
            client._session, "get",
            return_value=self._mock_response(""),
        ):
            value = client.get_latest("mvrv_z")

        assert value is None

    def test_get_latest_network_error_returns_none(self, client):
        with patch.object(
            client._session, "get",
            side_effect=requests.ConnectionError("timeout"),
        ):
            value = client.get_latest("mvrv_z")

        assert value is None

    def test_get_all_latest(self, client):
        responses = {
            "/mvrv-zscore": self._mock_response(self.MVRV_RESPONSE),
            "/nupl": self._mock_response(self.NUPL_RESPONSE),
        }

        def side_effect(url, **kwargs):
            for path, resp in responses.items():
                if path in url:
                    return resp
            return self._mock_response("", status_code=404)

        with patch.object(client._session, "get", side_effect=side_effect):
            values = client.get_all_latest()

        assert "mvrv_z" in values
        assert "nupl" in values
        assert values["mvrv_z"] == 0.5243

    def test_get_all_latest_partial_failure(self, client):
        """If one indicator fails, others still return."""

        def side_effect(url, **kwargs):
            if "nupl" in url:
                raise requests.ConnectionError("fail")
            return self._mock_response(self.MVRV_RESPONSE)

        with patch.object(client._session, "get", side_effect=side_effect):
            values = client.get_all_latest()

        assert "mvrv_z" in values
        assert "nupl" not in values

    def test_none_cached_with_short_ttl(self, client):
        """Failed fetches are cached briefly to avoid hammering API."""
        with patch.object(
            client._session, "get",
            return_value=self._mock_response(""),
        ) as mock_get:
            client.get_latest("mvrv_z")
            client.get_latest("mvrv_z")

        # None was cached, so only one HTTP call
        assert mock_get.call_count == 1


# -------------------------------------------------------------------
# INDICATOR_ENDPOINTS config
# -------------------------------------------------------------------

class TestIndicatorEndpoints:
    def test_mvrv_z_configured(self):
        assert "mvrv_z" in INDICATOR_ENDPOINTS

    def test_nupl_configured(self):
        assert "nupl" in INDICATOR_ENDPOINTS

    def test_all_endpoints_have_path_and_label(self):
        for key, (path, label) in INDICATOR_ENDPOINTS.items():
            assert path.startswith("/"), f"{key}: path must start with /"
            assert len(label) > 0, f"{key}: label must not be empty"
