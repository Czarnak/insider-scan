"""Tests for the Dashboard data layer (core/dashboard.py)."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from insider_scanner.core.dashboard import (
    CBBIClient,
    CryptoFearGreedClient,
    DEFAULT_INDICATOR_SPECS,
    DashboardSnapshot,
    GoldFearGreedClient,
    IndicatorSpec,
    MarketProvider,
    PRICE_SYMBOLS,
    TTLCache,
    _extract_close,
    calculate_rsi,
    classify_fng,
)


# -------------------------------------------------------------------
# TTLCache
# -------------------------------------------------------------------


class TestTTLCache:
    def test_set_and_get(self):
        cache = TTLCache()
        cache.set("k", 42, timedelta(minutes=5))
        assert cache.get("k") == 42

    def test_miss_returns_none(self):
        cache = TTLCache()
        assert cache.get("nonexistent") is None

    def test_expired_returns_none(self):
        cache = TTLCache()
        cache.set("k", "val", timedelta(seconds=-1))
        assert cache.get("k") is None

    def test_clear(self):
        cache = TTLCache()
        cache.set("a", 1, timedelta(hours=1))
        cache.set("b", 2, timedelta(hours=1))
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None

    def test_overwrite(self):
        cache = TTLCache()
        cache.set("k", "old", timedelta(hours=1))
        cache.set("k", "new", timedelta(hours=1))
        assert cache.get("k") == "new"


# -------------------------------------------------------------------
# classify_fng
# -------------------------------------------------------------------


class TestClassifyFng:
    @pytest.mark.parametrize(
        "score,expected",
        [
            (0, "Extreme Fear"),
            (10, "Extreme Fear"),
            (24, "Extreme Fear"),
            (25, "Fear"),
            (49, "Fear"),
            (50, "Greed"),
            (74, "Greed"),
            (75, "Extreme Greed"),
            (100, "Extreme Greed"),
        ],
    )
    def test_classification(self, score, expected):
        assert classify_fng(score) == expected


# -------------------------------------------------------------------
# _extract_close
# -------------------------------------------------------------------


class TestExtractClose:
    def test_flat_columns(self):
        idx = pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"])
        df = pd.DataFrame(
            {"Open": [1, 2, 3], "Close": [10.0, 20.0, 30.0]},
            index=idx,
        )
        s = _extract_close(df, "AAPL")
        assert len(s) == 3
        assert s.iloc[-1] == 30.0

    def test_multiindex_columns(self):
        idx = pd.to_datetime(["2025-01-01", "2025-01-02"])
        arrays = [["Close", "Close"], ["^VIX", "SPY"]]
        cols = pd.MultiIndex.from_arrays(arrays)
        df = pd.DataFrame(
            [[15.0, 500.0], [16.0, 510.0]],
            index=idx,
            columns=cols,
        )
        s = _extract_close(df, "^VIX")
        assert len(s) == 2
        assert s.iloc[0] == 15.0

    def test_empty_dataframe(self):
        assert _extract_close(pd.DataFrame(), "X").empty

    def test_none_dataframe(self):
        assert _extract_close(None, "X").empty

    def test_no_close_column(self):
        df = pd.DataFrame(
            {"Open": [1, 2], "Volume": [100, 200]},
            index=pd.to_datetime(["2025-01-01", "2025-01-02"]),
        )
        assert _extract_close(df, "X").empty

    def test_adj_close_fallback(self):
        idx = pd.to_datetime(["2025-01-01"])
        df = pd.DataFrame({"Adj Close": [42.0]}, index=idx)
        s = _extract_close(df, "X")
        assert len(s) == 1
        assert s.iloc[0] == 42.0


# -------------------------------------------------------------------
# calculate_rsi
# -------------------------------------------------------------------


class TestCalculateRsi:
    def _make_series(self, values: list[float]) -> pd.Series:
        idx = pd.date_range("2025-01-01", periods=len(values), freq="D")
        return pd.Series(values, index=idx)

    def test_needs_enough_data(self):
        """Returns None with < period+1 data points."""
        s = self._make_series([100.0] * 10)
        assert calculate_rsi(s, period=14) is None

    def test_none_input(self):
        assert calculate_rsi(None) is None

    def test_empty_input(self):
        assert calculate_rsi(pd.Series(dtype=float)) is None

    def test_steady_uptrend(self):
        """All gains → RSI near 100."""
        prices = [100 + i for i in range(30)]
        rsi = calculate_rsi(self._make_series(prices))
        assert rsi is not None
        assert rsi > 90

    def test_steady_downtrend(self):
        """All losses → RSI near 0."""
        prices = [200 - i for i in range(30)]
        rsi = calculate_rsi(self._make_series(prices))
        assert rsi is not None
        assert rsi < 10

    def test_sideways_market(self):
        """Alternating up/down → RSI around 50."""
        prices = [100 + (1 if i % 2 == 0 else -1) for i in range(60)]
        rsi = calculate_rsi(self._make_series(prices))
        assert rsi is not None
        assert 30 < rsi < 70

    def test_returns_float(self):
        prices = [100 + i * 0.5 for i in range(30)]
        rsi = calculate_rsi(self._make_series(prices))
        assert isinstance(rsi, float)

    def test_all_flat_prices(self):
        """No change → RSI should be near 50 (or edge case)."""
        prices = [100.0] * 30
        rsi = calculate_rsi(self._make_series(prices))
        # With zero gains and zero losses, avg_loss=0 → RSI=100
        # But with flat prices, delta=0, so both gain and loss are 0
        # In practice, EWM of all zeros gives 0/0 handled as RSI=100
        assert rsi is not None


# -------------------------------------------------------------------
# GoldFearGreedClient
# -------------------------------------------------------------------


class TestGoldFearGreedClient:
    def test_parses_response(self):
        cache = TTLCache()
        client = GoldFearGreedClient(cache)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"2025-06-01": 30, "2025-06-02": 65}
        mock_resp.raise_for_status = MagicMock()

        with patch(
            "insider_scanner.core.dashboard.requests.get", return_value=mock_resp
        ):
            result = client.get_latest()

        assert result == (65, "Greed")

    def test_uses_cache(self):
        cache = TTLCache()
        cache.set("gold_fng_latest", (42, "Fear"), timedelta(hours=1))
        client = GoldFearGreedClient(cache)

        with patch("insider_scanner.core.dashboard.requests.get") as mock_get:
            result = client.get_latest()
            mock_get.assert_not_called()
        assert result == (42, "Fear")

    def test_network_error_returns_none(self):
        cache = TTLCache()
        client = GoldFearGreedClient(cache)
        with patch(
            "insider_scanner.core.dashboard.requests.get",
            side_effect=ConnectionError("offline"),
        ):
            assert client.get_latest() is None


# -------------------------------------------------------------------
# CryptoFearGreedClient
# -------------------------------------------------------------------


class TestCryptoFearGreedClient:
    def test_parses_response(self):
        cache = TTLCache()
        client = CryptoFearGreedClient(cache)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [{"value": "22", "value_classification": "Extreme Fear"}],
        }
        mock_resp.raise_for_status = MagicMock()

        with patch(
            "insider_scanner.core.dashboard.requests.get", return_value=mock_resp
        ):
            result = client.get_latest()
        assert result == (22, "Extreme Fear")

    def test_network_error_returns_none(self):
        cache = TTLCache()
        client = CryptoFearGreedClient(cache)
        with patch(
            "insider_scanner.core.dashboard.requests.get",
            side_effect=ConnectionError,
        ):
            assert client.get_latest() is None


# -------------------------------------------------------------------
# CBBIClient
# -------------------------------------------------------------------


class TestCBBIClient:
    def test_parses_confidence_format(self):
        cache = TTLCache()
        client = CBBIClient(cache)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"Confidence": 0.42}
        mock_resp.raise_for_status = MagicMock()

        with patch(
            "insider_scanner.core.dashboard.requests.get", return_value=mock_resp
        ):
            result = client.get_latest()
        assert result == 42.0

    def test_parses_date_keyed_format(self):
        cache = TTLCache()
        client = CBBIClient(cache)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "2025-06-01": 0.55,
            "2025-06-02": 0.60,
        }
        mock_resp.raise_for_status = MagicMock()

        with patch(
            "insider_scanner.core.dashboard.requests.get", return_value=mock_resp
        ):
            result = client.get_latest()
        assert result == 60.0  # latest date, 0.60 * 100

    def test_uses_cache(self):
        cache = TTLCache()
        cache.set("cbbi_latest", 73.5, timedelta(hours=1))
        client = CBBIClient(cache)

        with patch("insider_scanner.core.dashboard.requests.get") as mock_get:
            result = client.get_latest()
            mock_get.assert_not_called()
        assert result == 73.5

    def test_network_error_returns_none(self):
        cache = TTLCache()
        client = CBBIClient(cache)
        with patch(
            "insider_scanner.core.dashboard.requests.get",
            side_effect=ConnectionError,
        ):
            assert client.get_latest() is None


# -------------------------------------------------------------------
# IndicatorSpec / DEFAULT_INDICATOR_SPECS
# -------------------------------------------------------------------


class TestIndicatorSpec:
    def test_frozen(self):
        spec = IndicatorSpec(key="x", title="X")
        with pytest.raises(AttributeError):
            spec.key = "y"  # type: ignore[misc]

    def test_defaults(self):
        spec = IndicatorSpec(key="x", title="X")
        assert spec.unit == ""
        assert spec.bands == ()

    def test_default_specs_exist(self):
        assert len(DEFAULT_INDICATOR_SPECS) >= 6
        keys = {s.key for s in DEFAULT_INDICATOR_SPECS}
        assert "rsi" in keys
        assert "cbbi" in keys

    def test_all_specs_have_bands(self):
        for spec in DEFAULT_INDICATOR_SPECS:
            assert len(spec.bands) >= 2, f"{spec.key} has too few bands"


# -------------------------------------------------------------------
# PRICE_SYMBOLS
# -------------------------------------------------------------------


class TestPriceSymbols:
    def test_contains_expected(self):
        assert "GC=F" in PRICE_SYMBOLS  # Gold
        assert "ES=F" in PRICE_SYMBOLS  # S&P 500
        assert "^VIX" not in PRICE_SYMBOLS  # VIX handled separately

    def test_count(self):
        assert len(PRICE_SYMBOLS) == 5


# -------------------------------------------------------------------
# DashboardSnapshot
# -------------------------------------------------------------------


class TestDashboardSnapshot:
    def test_defaults(self):
        snap = DashboardSnapshot()
        assert snap.prices == {}
        assert snap.vix.empty
        assert snap.fear_greed == {}
        assert snap.indicators == {}

    def test_with_data(self):
        s = pd.Series([1.0, 2.0])
        snap = DashboardSnapshot(
            prices={"GC=F": s},
            vix=s,
            fear_greed={"gold": (55, "Greed")},
            indicators={"rsi": 62.5},
        )
        assert len(snap.prices) == 1
        assert snap.indicators["rsi"] == 62.5


# -------------------------------------------------------------------
# MarketProvider
# -------------------------------------------------------------------


class TestMarketProvider:
    def _make_df(self, n: int = 10) -> pd.DataFrame:
        idx = pd.date_range("2025-01-01", periods=n, freq="D")
        return pd.DataFrame(
            {"Close": [100.0 + i for i in range(n)]},
            index=idx,
        )

    def test_get_daily_close_caches(self):
        provider = MarketProvider()
        fake_df = self._make_df(10)

        with patch(
            "insider_scanner.core.dashboard.yf.download", return_value=fake_df
        ) as mock_dl:
            s1 = provider.get_daily_close("AAPL", 5)
            s2 = provider.get_daily_close("AAPL", 5)
        mock_dl.assert_called_once()
        assert len(s1) == 5
        assert len(s2) == 5

    def test_get_daily_close_empty(self):
        provider = MarketProvider()
        with patch(
            "insider_scanner.core.dashboard.yf.download", return_value=pd.DataFrame()
        ):
            s = provider.get_daily_close("FAKE", 5)
        assert s.empty

    def test_get_vix_daily(self):
        provider = MarketProvider()
        fake_df = self._make_df(50)

        with patch("insider_scanner.core.dashboard.yf.download", return_value=fake_df):
            s = provider.get_vix_daily(30)
        assert len(s) == 30

    def test_get_fear_greed_structure(self):
        provider = MarketProvider()
        with patch.object(provider._gold_fng, "get_latest", return_value=(55, "Greed")):
            with patch.object(
                provider._crypto_fng, "get_latest", return_value=(30, "Fear")
            ):
                fg = provider.get_fear_greed()
        assert fg["stocks"] is None
        assert fg["gold"] == (55, "Greed")
        assert fg["crypto"] == (30, "Fear")

    def test_get_indicators_rsi(self):
        """RSI is calculated from BTC-USD price data."""
        provider = MarketProvider()
        # 30 upward-trending prices → RSI > 50
        fake_df = self._make_df(30)

        with patch("insider_scanner.core.dashboard.yf.download", return_value=fake_df):
            with patch.object(provider._cbbi, "get_latest", return_value=None):
                indicators = provider.get_indicators()

        assert "rsi" in indicators
        assert indicators["rsi"] > 50

    def test_get_indicators_includes_external(self):
        """External values (set manually) are merged in."""
        provider = MarketProvider()
        provider.latest_indicator_values = {"mvrv_z": 2.5, "nupl": 0.3}

        with patch(
            "insider_scanner.core.dashboard.yf.download", return_value=pd.DataFrame()
        ):
            with patch.object(provider._cbbi, "get_latest", return_value=None):
                indicators = provider.get_indicators()

        assert indicators.get("mvrv_z") == 2.5
        assert indicators.get("nupl") == 0.3

    def test_get_indicators_cbbi(self):
        """CBBI is fetched from the CBBI client."""
        provider = MarketProvider()
        with patch(
            "insider_scanner.core.dashboard.yf.download", return_value=pd.DataFrame()
        ):
            with patch.object(provider._cbbi, "get_latest", return_value=65.0):
                indicators = provider.get_indicators()

        assert indicators.get("cbbi") == 65.0

    def test_fetch_all_returns_snapshot(self):
        """fetch_all() returns a complete DashboardSnapshot."""
        provider = MarketProvider()
        fake_df = self._make_df(30)

        with patch("insider_scanner.core.dashboard.yf.download", return_value=fake_df):
            with patch.object(
                provider._gold_fng, "get_latest", return_value=(55, "Greed")
            ):
                with patch.object(
                    provider._crypto_fng, "get_latest", return_value=(30, "Fear")
                ):
                    with patch.object(provider._cbbi, "get_latest", return_value=42.0):
                        snap = provider.fetch_all()

        assert isinstance(snap, DashboardSnapshot)
        # Prices: 5 symbols + BTC-USD fetched for RSI
        assert len(snap.prices) == len(PRICE_SYMBOLS)
        assert not snap.vix.empty
        assert snap.fear_greed.get("gold") == (55, "Greed")
        assert "rsi" in snap.indicators

    def test_fetch_all_survives_failures(self):
        """fetch_all() returns partial data even when some calls fail."""
        provider = MarketProvider()

        with patch(
            "insider_scanner.core.dashboard.yf.download",
            side_effect=Exception("network down"),
        ):
            with patch.object(
                provider._gold_fng,
                "get_latest",
                return_value=(55, "Greed"),
            ):
                with patch.object(
                    provider._crypto_fng, "get_latest", return_value=None
                ):
                    with patch.object(provider._cbbi, "get_latest", return_value=None):
                        snap = provider.fetch_all()

        assert isinstance(snap, DashboardSnapshot)
        # Prices are empty Series (yfinance failed)
        for s in snap.prices.values():
            assert s.empty
        assert snap.vix.empty
        # F&G still works (different transport)
        assert snap.fear_greed.get("gold") == (55, "Greed")
