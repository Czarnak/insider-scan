"""Tests for CongressTrade dataclass."""

from __future__ import annotations

from datetime import date

from insider_scanner.core.models import CongressTrade


class TestCongressTradeBasic:
    def test_defaults(self):
        t = CongressTrade()
        assert t.official_name == ""
        assert t.chamber == ""
        assert t.trade_type == "Other"
        assert t.amount_low == 0.0
        assert t.amount_high == 0.0
        assert t.filing_date is None
        assert t.trade_date is None

    def test_full_construction(self):
        t = CongressTrade(
            official_name="Nancy Pelosi",
            chamber="House",
            party="Democrat",
            filing_date=date(2026, 1, 23),
            doc_id="20033725",
            source_url="https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/20033725.pdf",
            trade_date=date(2026, 1, 15),
            asset_description="Apple Inc. - Common Stock (AAPL)",
            ticker="AAPL",
            trade_type="Purchase",
            owner="Spouse",
            amount_range="$1,001 - $15,000",
            amount_low=1001.0,
            amount_high=15000.0,
            comment="50 call options",
            source="house",
        )
        assert t.official_name == "Nancy Pelosi"
        assert t.chamber == "House"
        assert t.ticker == "AAPL"
        assert t.trade_type == "Purchase"
        assert t.owner == "Spouse"
        assert t.amount_low == 1001.0
        assert t.amount_high == 15000.0


class TestCongressTradeSerialisation:
    def test_to_dict(self):
        t = CongressTrade(
            official_name="Test Member",
            chamber="Senate",
            filing_date=date(2026, 2, 1),
            trade_date=date(2026, 1, 20),
            ticker="MSFT",
            trade_type="Sale",
            amount_range="$15,001 - $50,000",
            amount_low=15001.0,
            amount_high=50000.0,
            source="senate",
        )
        d = t.to_dict()
        assert d["official_name"] == "Test Member"
        assert d["chamber"] == "Senate"
        assert d["filing_date"] == "2026-02-01"
        assert d["trade_date"] == "2026-01-20"
        assert d["ticker"] == "MSFT"
        assert d["trade_type"] == "Sale"
        assert d["amount_low"] == 15001.0
        assert d["amount_high"] == 50000.0

    def test_to_dict_none_dates(self):
        d = CongressTrade().to_dict()
        assert d["filing_date"] == ""
        assert d["trade_date"] == ""

    def test_from_dict(self):
        d = {
            "official_name": "Test Member",
            "chamber": "House",
            "filing_date": "2026-02-01",
            "trade_date": "2026-01-20",
            "ticker": "GOOG",
            "trade_type": "Purchase",
            "amount_range": "$50,001 - $100,000",
            "amount_low": 50001.0,
            "amount_high": 100000.0,
            "owner": "Self",
            "source": "house",
        }
        t = CongressTrade.from_dict(d)
        assert t.official_name == "Test Member"
        assert t.filing_date == date(2026, 2, 1)
        assert t.trade_date == date(2026, 1, 20)
        assert t.ticker == "GOOG"
        assert t.amount_low == 50001.0

    def test_from_dict_empty(self):
        t = CongressTrade.from_dict({})
        assert t.official_name == ""
        assert t.filing_date is None
        assert t.amount_low == 0.0

    def test_roundtrip(self):
        original = CongressTrade(
            official_name="Roundtrip Test",
            chamber="Senate",
            party="Republican",
            filing_date=date(2026, 3, 15),
            trade_date=date(2026, 3, 10),
            ticker="NVDA",
            trade_type="Purchase",
            amount_range="$100,001 - $250,000",
            amount_low=100001.0,
            amount_high=250000.0,
            owner="Joint",
            doc_id="12345",
            source="senate",
        )
        restored = CongressTrade.from_dict(original.to_dict())
        assert restored.official_name == original.official_name
        assert restored.filing_date == original.filing_date
        assert restored.trade_date == original.trade_date
        assert restored.ticker == original.ticker
        assert restored.amount_low == original.amount_low
        assert restored.amount_high == original.amount_high


class TestParseAmountRange:
    def test_standard_range(self):
        assert CongressTrade.parse_amount_range("$1,001 - $15,000") == (1001.0, 15000.0)

    def test_large_range(self):
        assert CongressTrade.parse_amount_range("$1,000,001 - $5,000,000") == (1000001.0, 5000000.0)

    def test_mid_range(self):
        assert CongressTrade.parse_amount_range("$50,001 - $100,000") == (50001.0, 100000.0)

    def test_over_pattern(self):
        assert CongressTrade.parse_amount_range("Over $50,000,000") == (50000000.0, 50000000.0)

    def test_empty_string(self):
        assert CongressTrade.parse_amount_range("") == (0.0, 0.0)

    def test_whitespace(self):
        assert CongressTrade.parse_amount_range("  ") == (0.0, 0.0)

    def test_no_commas(self):
        assert CongressTrade.parse_amount_range("$1001 - $15000") == (1001.0, 15000.0)

    def test_invalid_text(self):
        assert CongressTrade.parse_amount_range("unknown") == (0.0, 0.0)

    def test_single_value(self):
        # No dash separator
        assert CongressTrade.parse_amount_range("$5,000") == (0.0, 0.0)
