from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date
from typing import Any


@dataclass
class TransactionRecord:
    ticker: str
    company_name: str | None
    insider_name: str | None
    role_relation: str | None  # CEO/CFO/Director/10% Owner/Officer/Congress/Other
    transaction_type: str      # Buy/Award/Option/Other
    trade_date: date | None
    filing_date: date | None
    shares: float | None
    price: float | None
    value_usd: float | None
    sec_link: str | None
    source: str
    source_url: str
    confidence: str            # HIGH/MED/LOW
    event_id: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # dataclasses date -> ISO
        if d.get("trade_date"):
            d["trade_date"] = d["trade_date"].isoformat()
        if d.get("filing_date"):
            d["filing_date"] = d["filing_date"].isoformat()
        return d
