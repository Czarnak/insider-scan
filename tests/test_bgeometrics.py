"""Tests for BGeometrics free Bitcoin on-chain indicator client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from insider_scanner.core.bgeometrics_client import (
    BGeometricsClient,
    INDICATOR_ENDPOINTS,
    parse_json_timeseries,
)
from insider_scanner.core.dashboard import TTLCache


# -------------------------------------------------------------------
# parse_json_timeseries
# -------------------------------------------------------------------


class TestParseJsonTimeseries:
    def test_basic_mvrv(self):
        data = [
            {"d": "2026-02-14", "unixTs": "1771027200", "mvrvZscore": "0.4931"},
            {"d": "2026-02-15", "unixTs": "1771113600", "mvrvZscore": "0.5243"},
        ]
        rows = parse_json_timeseries(data, "mvrvZscore")
        assert len(rows) == 2
        assert rows[0] == ("2026-02-14", 0.4931)
        assert rows[1] == ("2026-02-15", 0.5243)

    def test_basic_nupl(self):
        data = [
            {"d": "2026-02-16", "unixTs": "1771200000", "nupl": "0.2070672777240897"},
        ]
        rows = parse_json_timeseries(data, "nupl")
        assert len(rows) == 1
        assert abs(rows[0][1] - 0.2070672777) < 1e-8

    def test_string_values_converted(self):
        """API returns values as strings — they must be parsed to float."""
        data = [{"d": "2026-01-01", "unixTs": "0", "mvrvZscore": "1.234"}]
        rows = parse_json_timeseries(data, "mvrvZscore")
        assert rows[0][1] == 1.234

    def test_comma_decimal_handled(self):
        """European comma decimals (e.g. from VDD) are converted."""
        data = [{"d": "2026-01-01", "unixTs": "0", "val": "732402853686,7"}]
        rows = parse_json_timeseries(data, "val")
        assert rows[0][1] == 732402853686.7

    def test_missing_value_field_skipped(self):
        data = [
            {"d": "2026-01-01", "unixTs": "0", "mvrvZscore": "0.5"},
            {"d": "2026-01-02", "unixTs": "0"},  # missing field
        ]
        rows = parse_json_timeseries(data, "mvrvZscore")
        assert len(rows) == 1

    def test_missing_date_skipped(self):
        data = [{"unixTs": "0", "mvrvZscore": "0.5"}]  # missing "d"
        rows = parse_json_timeseries(data, "mvrvZscore")
        assert len(rows) == 0

    def test_non_numeric_value_skipped(self):
        data = [{"d": "2026-01-01", "unixTs": "0", "mvrvZscore": "N/A"}]
        rows = parse_json_timeseries(data, "mvrvZscore")
        assert len(rows) == 0

    def test_empty_list(self):
        assert parse_json_timeseries([], "mvrvZscore") == []

    def test_non_list_input(self):
        assert parse_json_timeseries({"error": "nope"}, "x") == []
        assert parse_json_timeseries("string", "x") == []
        assert parse_json_timeseries(None, "x") == []

    def test_non_dict_records_skipped(self):
        data = [
            {"d": "2026-01-01", "unixTs": "0", "mvrvZscore": "0.5"},
            "bad record",
            42,
            None,
        ]
        rows = parse_json_timeseries(data, "mvrvZscore")
        assert len(rows) == 1

    def test_negative_values(self):
        data = [{"d": "2026-01-01", "unixTs": "0", "nupl": "-0.15"}]
        rows = parse_json_timeseries(data, "nupl")
        assert rows[0][1] == -0.15

    def test_zero_value(self):
        data = [{"d": "2009-01-03", "unixTs": "1230940800", "mvrvZscore": "0"}]
        rows = parse_json_timeseries(data, "mvrvZscore")
        assert rows[0][1] == 0.0


# -------------------------------------------------------------------
# BGeometricsClient
# -------------------------------------------------------------------

MVRV_JSON = [
    {"d": "2026-02-14", "unixTs": "1771027200", "mvrvZscore": "0.4931"},
    {"d": "2026-02-15", "unixTs": "1771113600", "mvrvZscore": "0.5243"},
]
NUPL_JSON = [
    {"d": "2026-02-16", "unixTs": "1771200000", "nupl": "0.2070672777240897"},
    {"d": "2026-02-17", "unixTs": "1771286400", "nupl": "0.20382201292732535"},
]


class TestBGeometricsClient:
    @pytest.fixture
    def cache(self):
        return TTLCache()

    @pytest.fixture
    def client(self, cache):
        return BGeometricsClient(cache, ttl_hours=6)

    def _mock_response(self, json_data, status_code=200):
        mock = MagicMock()
        mock.status_code = status_code
        mock.json.return_value = json_data
        mock.raise_for_status = MagicMock()
        if status_code >= 400:
            mock.raise_for_status.side_effect = requests.HTTPError(
                f"{status_code} Error"
            )
        return mock

    def test_get_latest_mvrv(self, client):
        with patch.object(
            client._session,
            "get",
            return_value=self._mock_response(MVRV_JSON),
        ):
            value = client.get_latest("mvrv_z")

        assert value == 0.5243

    def test_get_latest_nupl(self, client):
        with patch.object(
            client._session,
            "get",
            return_value=self._mock_response(NUPL_JSON),
        ):
            value = client.get_latest("nupl")

        assert value is not None
        assert abs(value - 0.203822) < 0.001

    def test_get_latest_caches_result(self, client):
        mock_resp = self._mock_response(MVRV_JSON)
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
            client._session,
            "get",
            return_value=self._mock_response([], status_code=429),
        ):
            value = client.get_latest("mvrv_z")

        assert value is None

    def test_get_latest_empty_array_returns_none(self, client):
        with patch.object(
            client._session,
            "get",
            return_value=self._mock_response([]),
        ):
            value = client.get_latest("mvrv_z")

        assert value is None

    def test_get_latest_network_error_returns_none(self, client):
        with patch.object(
            client._session,
            "get",
            side_effect=requests.ConnectionError("timeout"),
        ):
            value = client.get_latest("mvrv_z")

        assert value is None

    def test_get_all_latest(self, client):
        responses = {
            "/mvrv-zscore": self._mock_response(MVRV_JSON),
            "/nupl": self._mock_response(NUPL_JSON),
        }

        def side_effect(url, **kwargs):
            for path, resp in responses.items():
                if path in url:
                    return resp
            return self._mock_response([], status_code=404)

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
            return self._mock_response(MVRV_JSON)

        with patch.object(client._session, "get", side_effect=side_effect):
            values = client.get_all_latest()

        assert "mvrv_z" in values
        assert "nupl" not in values

    def test_none_cached_with_short_ttl(self, client):
        """Failed fetches are cached briefly to avoid hammering API."""
        with patch.object(
            client._session,
            "get",
            return_value=self._mock_response([]),
        ) as mock_get:
            client.get_latest("mvrv_z")
            client.get_latest("mvrv_z")

        # None was cached, so only one HTTP call
        assert mock_get.call_count == 1

    def test_json_decode_error_returns_none(self, client):
        """If response is not valid JSON, return None gracefully."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.side_effect = ValueError("No JSON")

        with patch.object(client._session, "get", return_value=mock_resp):
            value = client.get_latest("mvrv_z")

        assert value is None


# -------------------------------------------------------------------
# INDICATOR_ENDPOINTS config
# -------------------------------------------------------------------


class TestIndicatorEndpoints:
    def test_mvrv_z_configured(self):
        assert "mvrv_z" in INDICATOR_ENDPOINTS

    def test_nupl_configured(self):
        assert "nupl" in INDICATOR_ENDPOINTS

    def test_all_endpoints_have_path_field_and_label(self):
        for key, (path, value_field, label) in INDICATOR_ENDPOINTS.items():
            assert path.startswith("/"), f"{key}: path must start with /"
            assert len(value_field) > 0, f"{key}: value_field must not be empty"
            assert len(label) > 0, f"{key}: label must not be empty"
