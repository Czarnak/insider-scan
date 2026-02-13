"""Common data models for insider trades."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal


@dataclass
class InsiderTrade:
    """Unified insider trade record from any source."""

    # Identifiers
    ticker: str
    company: str = ""
    insider_name: str = ""
    insider_title: str = ""

    # Trade details
    trade_type: Literal["Buy", "Sell", "Exercise", "Other"] = "Other"
    trade_date: date | None = None
    filing_date: date | None = None
    shares: float = 0.0
    price: float = 0.0
    value: float = 0.0
    shares_owned_after: float = 0.0

    # Source tracking
    source: str = ""  # "secform4", "openinsider", "edgar"
    edgar_url: str = ""  # Link to SEC filing

    # Congress-specific
    is_congress: bool = False
    congress_member: str = ""

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "company": self.company,
            "insider_name": self.insider_name,
            "insider_title": self.insider_title,
            "trade_type": self.trade_type,
            "trade_date": str(self.trade_date) if self.trade_date else "",
            "filing_date": str(self.filing_date) if self.filing_date else "",
            "shares": self.shares,
            "price": self.price,
            "value": self.value,
            "shares_owned_after": self.shares_owned_after,
            "source": self.source,
            "edgar_url": self.edgar_url,
            "is_congress": self.is_congress,
            "congress_member": self.congress_member,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "InsiderTrade":
        td = d.get("trade_date", "")
        fd = d.get("filing_date", "")
        return cls(
            ticker=d.get("ticker", ""),
            company=d.get("company", ""),
            insider_name=d.get("insider_name", ""),
            insider_title=d.get("insider_title", ""),
            trade_type=d.get("trade_type", "Other"),
            trade_date=date.fromisoformat(td) if td else None,
            filing_date=date.fromisoformat(fd) if fd else None,
            shares=float(d.get("shares", 0)),
            price=float(d.get("price", 0)),
            value=float(d.get("value", 0)),
            shares_owned_after=float(d.get("shares_owned_after", 0)),
            source=d.get("source", ""),
            edgar_url=d.get("edgar_url", ""),
            is_congress=d.get("is_congress", False),
            congress_member=d.get("congress_member", ""),
        )
