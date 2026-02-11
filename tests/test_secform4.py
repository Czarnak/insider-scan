"""Tests for secform4.com scraper (mocked HTTP)."""

from __future__ import annotations

from datetime import date

import responses

from insider_scanner.core.secform4 import parse_secform4_html, scrape_ticker
from tests.fixtures import SECFORM4_HTML


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
        from datetime import date
        trades = parse_secform4_html(SECFORM4_HTML, "AAPL")
        ceo = [t for t in trades if "Cook" in t.insider_name][0]
        assert ceo.trade_date == date(2025, 11, 15)
        assert ceo.filing_date == date(2025, 11, 17)

    def test_empty_html(self):
        trades = parse_secform4_html("<html><body></body></html>", "TEST")
        assert trades == []


class TestScrapeSecform4:
    @responses.activate
    def test_scrape_ticker_mocked(self):
        responses.add(
            responses.GET,
            "https://www.secform4.com/AAPL.htm",
            body=SECFORM4_HTML,
            status=200,
        )
        trades = scrape_ticker("AAPL", use_cache=False)
        assert len(trades) == 4
        assert all(t.ticker == "AAPL" for t in trades)

    @responses.activate
    def test_scrape_404(self):
        responses.add(
            responses.GET,
            "https://www.secform4.com/ZZZZ.htm",
            status=404,
        )
        trades = scrape_ticker("ZZZZ", use_cache=False)
        assert trades == []

    @responses.activate
    def test_scrape_network_error(self):
        responses.add(
            responses.GET,
            "https://www.secform4.com/FAIL.htm",
            body=ConnectionError("network error"),
        )
        trades = scrape_ticker("FAIL", use_cache=False)
        assert trades == []

    @responses.activate
    def test_scrape_with_start_date(self):
        responses.add(
            responses.GET,
            "https://www.secform4.com/AAPL.htm",
            body=SECFORM4_HTML,
            status=200,
        )
        trades = scrape_ticker("AAPL", use_cache=False, start_date=date(2025, 11, 1))
        # Only Nov trades should pass (Cook 11/15, Williams 11/10)
        assert all(t.trade_date >= date(2025, 11, 1) for t in trades)
        assert len(trades) == 2

    @responses.activate
    def test_scrape_with_end_date(self):
        responses.add(
            responses.GET,
            "https://www.secform4.com/AAPL.htm",
            body=SECFORM4_HTML,
            status=200,
        )
        trades = scrape_ticker("AAPL", use_cache=False, end_date=date(2025, 10, 1))
        # Only Maestri (10/01) and Pelosi (09/20)
        assert all(t.trade_date <= date(2025, 10, 1) for t in trades)
        assert len(trades) == 2

    @responses.activate
    def test_scrape_with_date_range(self):
        responses.add(
            responses.GET,
            "https://www.secform4.com/AAPL.htm",
            body=SECFORM4_HTML,
            status=200,
        )
        trades = scrape_ticker(
            "AAPL", use_cache=False,
            start_date=date(2025, 10, 1),
            end_date=date(2025, 11, 10),
        )
        # Maestri 10/01, Williams 11/10
        assert len(trades) == 2
