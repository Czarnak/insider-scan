"""Tests for SEC EDGAR CIK resolver (mocked HTTP)."""

from __future__ import annotations

import responses

from insider_scanner.core.edgar import (
    parse_cik_from_html,
    resolve_cik,
    get_filing_url,
    build_edgar_url_for_trade,
)
from insider_scanner.core.models import InsiderTrade
from tests.fixtures import EDGAR_CIK_HTML, EDGAR_CIK_NOT_FOUND_HTML


class TestParseCik:
    def test_parse_valid(self):
        cik = parse_cik_from_html(EDGAR_CIK_HTML)
        assert cik == "0000320193"

    def test_parse_not_found(self):
        cik = parse_cik_from_html(EDGAR_CIK_NOT_FOUND_HTML)
        assert cik is None

    def test_parse_empty(self):
        cik = parse_cik_from_html("<html><body></body></html>")
        assert cik is None


class TestResolveCik:
    @responses.activate
    def test_resolve_success(self):
        responses.add(
            responses.GET,
            "https://www.sec.gov/cgi-bin/browse-edgar",
            body=EDGAR_CIK_HTML,
            status=200,
        )
        cik = resolve_cik("AAPL", use_cache=False)
        assert cik == "0000320193"

    @responses.activate
    def test_resolve_not_found(self):
        responses.add(
            responses.GET,
            "https://www.sec.gov/cgi-bin/browse-edgar",
            body=EDGAR_CIK_NOT_FOUND_HTML,
            status=200,
        )
        cik = resolve_cik("ZZZZZZ", use_cache=False)
        assert cik is None

    @responses.activate
    def test_resolve_network_error(self):
        responses.add(
            responses.GET,
            "https://www.sec.gov/cgi-bin/browse-edgar",
            body=ConnectionError("network error"),
        )
        cik = resolve_cik("FAIL", use_cache=False)
        assert cik is None


class TestFilingUrl:
    def test_url_format(self):
        url = get_filing_url("0000320193", count=40)
        assert "CIK=0000320193" in url
        assert "count=40" in url
        assert "type=4" in url


class TestBuildEdgarUrl:
    def test_build_url(self):
        from datetime import date
        trade = InsiderTrade(
            ticker="AAPL",
            insider_name="Cook Timothy",
            filing_date=date(2025, 11, 15),
        )
        url = build_edgar_url_for_trade(trade)
        assert "Cook+Timothy" in url
        assert "AAPL" in url
        assert "forms=4" in url

    def test_build_url_no_date(self):
        trade = InsiderTrade(ticker="AAPL", insider_name="Test Person")
        url = build_edgar_url_for_trade(trade)
        assert "Test+Person" in url
        assert "AAPL" in url
