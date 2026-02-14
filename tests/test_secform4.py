"""Tests for secform4.com scraper (mocked HTTP)."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import responses

from insider_scanner.core.secform4 import parse_secform4_html, scrape_ticker
from tests.fixtures import SECFORM4_HTML

# AAPL CIK (raw, not zero-padded)
AAPL_CIK = "320193"


class TestParseSecform4:
    def test_parse_trades(self):
        trades = parse_secform4_html(SECFORM4_HTML, "AAPL")
        assert len(trades) == 4

    def test_ticker_assigned(self):
        trades = parse_secform4_html(SECFORM4_HTML, "AAPL")
        assert all(t.ticker == "AAPL" for t in trades)

    def test_source_set(self):
        trades = parse_secform4_html(SECFORM4_HTML, "AAPL")
        assert all(t.source == "secform4" for t in trades)

    def test_trade_types(self):
        trades = parse_secform4_html(SECFORM4_HTML, "AAPL")
        types = [t.trade_type for t in trades]
        assert "Sell" in types
        assert "Buy" in types

    def test_ceo_trade(self):
        trades = parse_secform4_html(SECFORM4_HTML, "AAPL")
        ceo = [t for t in trades if "Cook" in t.insider_name]
        assert len(ceo) == 1
        assert ceo[0].shares == 100_000
        assert ceo[0].price == 185.50
        assert ceo[0].value == 18_550_000

    def test_trade_dates_parsed(self):
        trades = parse_secform4_html(SECFORM4_HTML, "AAPL")
        ceo = [t for t in trades if "Cook" in t.insider_name][0]
        assert ceo.trade_date == date(2025, 11, 15)
        assert ceo.filing_date == date(2025, 11, 17)

    def test_empty_html(self):
        trades = parse_secform4_html("<html><body></body></html>", "TEST")
        assert trades == []


class TestScrapeSecform4:
    """Tests for scrape_ticker with CIK resolution mocked."""

    @responses.activate
    @patch("insider_scanner.core.edgar.resolve_cik_from_json", return_value=AAPL_CIK)
    def test_scrape_ticker_mocked(self, mock_cik):
        responses.add(
            responses.GET,
            f"https://www.secform4.com/{AAPL_CIK}.htm",
            body=SECFORM4_HTML,
            status=200,
        )
        trades = scrape_ticker("AAPL", use_cache=False)
        assert len(trades) == 4
        assert all(t.ticker == "AAPL" for t in trades)
        mock_cik.assert_called_once_with("AAPL", use_cache=False)

    @responses.activate
    @patch("insider_scanner.core.edgar.resolve_cik_from_json", return_value=AAPL_CIK)
    def test_scrape_404(self, mock_cik):
        responses.add(
            responses.GET,
            f"https://www.secform4.com/{AAPL_CIK}.htm",
            status=404,
        )
        trades = scrape_ticker("AAPL", use_cache=False)
        assert trades == []

    @patch("insider_scanner.core.edgar.resolve_cik_from_json", return_value=None)
    def test_scrape_cik_not_found(self, mock_cik):
        """If CIK cannot be resolved, return empty list."""
        trades = scrape_ticker("ZZZZ", use_cache=False)
        assert trades == []

    @responses.activate
    @patch("insider_scanner.core.edgar.resolve_cik_from_json", return_value=AAPL_CIK)
    def test_scrape_network_error(self, mock_cik):
        responses.add(
            responses.GET,
            f"https://www.secform4.com/{AAPL_CIK}.htm",
            body=ConnectionError("network error"),
        )
        trades = scrape_ticker("AAPL", use_cache=False)
        assert trades == []

    @responses.activate
    @patch("insider_scanner.core.edgar.resolve_cik_from_json", return_value=AAPL_CIK)
    def test_scrape_with_start_date(self, mock_cik):
        responses.add(
            responses.GET,
            f"https://www.secform4.com/{AAPL_CIK}.htm",
            body=SECFORM4_HTML,
            status=200,
        )
        trades = scrape_ticker("AAPL", use_cache=False, start_date=date(2025, 11, 1))
        # Only filing dates >= Nov 1: Cook (11/17), Williams (11/12)
        assert all(t.filing_date >= date(2025, 11, 1) for t in trades)
        assert len(trades) == 2

    @responses.activate
    @patch("insider_scanner.core.edgar.resolve_cik_from_json", return_value=AAPL_CIK)
    def test_scrape_with_end_date(self, mock_cik):
        responses.add(
            responses.GET,
            f"https://www.secform4.com/{AAPL_CIK}.htm",
            body=SECFORM4_HTML,
            status=200,
        )
        trades = scrape_ticker("AAPL", use_cache=False, end_date=date(2025, 10, 3))
        # Only filing dates <= Oct 3: Maestri (10/03), Pelosi (09/22)
        assert all(t.filing_date <= date(2025, 10, 3) for t in trades)
        assert len(trades) == 2

    @responses.activate
    @patch("insider_scanner.core.edgar.resolve_cik_from_json", return_value=AAPL_CIK)
    def test_scrape_with_date_range(self, mock_cik):
        responses.add(
            responses.GET,
            f"https://www.secform4.com/{AAPL_CIK}.htm",
            body=SECFORM4_HTML,
            status=200,
        )
        trades = scrape_ticker(
            "AAPL", use_cache=False,
            start_date=date(2025, 10, 3),
            end_date=date(2025, 11, 12),
        )
        # Filing dates in range: Maestri (10/03), Williams (11/12)
        assert len(trades) == 2

    @responses.activate
    @patch("insider_scanner.core.edgar.resolve_cik_from_json", return_value=AAPL_CIK)
    def test_url_uses_cik_not_ticker(self, mock_cik):
        """Verify the HTTP request goes to CIK-based URL, not ticker-based."""
        responses.add(
            responses.GET,
            f"https://www.secform4.com/{AAPL_CIK}.htm",
            body=SECFORM4_HTML,
            status=200,
        )
        scrape_ticker("AAPL", use_cache=False)
        assert len(responses.calls) == 1
        assert f"/{AAPL_CIK}.htm" in responses.calls[0].request.url
