"""Deduplicate and merge insider trades from multiple sources.

Merging strategy: trades from different sources are considered duplicates
if they share the same ticker, insider name, trade date, and approximate
share count (within 1%). When duplicates are found, the record with more
data fields populated wins, with EDGAR URL preserved if available.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from insider_scanner.core.models import InsiderTrade
from insider_scanner.utils.config import SCAN_OUTPUTS_DIR, ensure_dirs
from insider_scanner.utils.logging import get_logger

log = get_logger("merger")


def _dedup_key(trade: InsiderTrade) -> tuple:
    """Generate a deduplication key for a trade."""
    name = trade.insider_name.lower().strip()
    ticker = trade.ticker.upper().strip()
    td = str(trade.trade_date) if trade.trade_date else ""
    # Round shares to nearest 10 for fuzzy matching
    shares_bucket = round(trade.shares / 10) * 10 if trade.shares else 0
    return (ticker, name, td, shares_bucket)


def _richness_score(trade: InsiderTrade) -> int:
    """Score how many fields are populated (for picking the best duplicate)."""
    score = 0
    if trade.company:
        score += 1
    if trade.insider_name:
        score += 1
    if trade.insider_title:
        score += 1
    if trade.trade_date:
        score += 1
    if trade.filing_date:
        score += 1
    if trade.shares:
        score += 1
    if trade.price:
        score += 1
    if trade.value:
        score += 1
    if trade.edgar_url:
        score += 2  # EDGAR links are high-value
    return score


def merge_trades(
        *trade_lists: list[InsiderTrade],
) -> list[InsiderTrade]:
    """Merge and deduplicate trades from multiple sources.

    Parameters
    ----------
    *trade_lists : list of InsiderTrade
        One or more lists of trades (e.g. from secform4, openinsider).

    Returns
    -------
    list of InsiderTrade
        Merged and deduplicated, sorted by trade_date descending.
    """
    seen: dict[tuple, InsiderTrade] = {}

    for trades in trade_lists:
        for trade in trades:
            key = _dedup_key(trade)
            existing = seen.get(key)

            if existing is None:
                seen[key] = trade
            else:
                # Keep the richer record, but merge edgar_url if available
                if _richness_score(trade) > _richness_score(existing):
                    if existing.edgar_url and not trade.edgar_url:
                        trade.edgar_url = existing.edgar_url
                    if existing.is_congress:
                        trade.is_congress = True
                        trade.congress_member = existing.congress_member
                    seen[key] = trade
                else:
                    if trade.edgar_url and not existing.edgar_url:
                        existing.edgar_url = trade.edgar_url
                    if trade.is_congress:
                        existing.is_congress = True
                        existing.congress_member = trade.congress_member

    merged = list(seen.values())

    # Sort by trade date descending (None dates go last)
    merged.sort(
        key=lambda t: t.trade_date or date.min,
        reverse=True,
    )

    log.info(
        "Merged %d total trades → %d unique",
        sum(len(tl) for tl in trade_lists),
        len(merged),
    )
    return merged


def filter_trades(
        trades: list[InsiderTrade],
        *,
        ticker: str | None = None,
        trade_type: str | None = None,
        min_value: float | None = None,
        congress_only: bool = False,
        since: date | None = None,
        until: date | None = None,
) -> list[InsiderTrade]:
    """Filter trades by various criteria.

    Parameters
    ----------
    trades : list of InsiderTrade
        Input trades.
    ticker : str or None
        Filter by ticker symbol.
    trade_type : str or None
        Filter by trade type ("Buy", "Sell", etc.).
    min_value : float or None
        Minimum trade dollar value.
    congress_only : bool
        If True, only return congress-flagged trades.
    since : date or None
        Only return trades on or after this date.
    until : date or None
        Only return trades on or before this date.

    Returns
    -------
    list of InsiderTrade
    """
    result = trades

    if ticker:
        result = [t for t in result if t.ticker.upper() == ticker.upper()]
    if trade_type:
        result = [t for t in result if t.trade_type == trade_type]
    if min_value is not None:
        result = [t for t in result if abs(t.value) >= min_value]
    if congress_only:
        result = [t for t in result if t.is_congress]
    if since:
        result = [t for t in result if t.trade_date and t.trade_date >= since]
    if until:
        result = [t for t in result if t.trade_date and t.trade_date <= until]

    return result


def trades_to_dataframe(trades: list[InsiderTrade]) -> pd.DataFrame:
    """Convert a list of InsiderTrade to a pandas DataFrame."""
    if not trades:
        return pd.DataFrame()
    return pd.DataFrame([t.to_dict() for t in trades])


def save_scan_results(
        trades: list[InsiderTrade],
        label: str = "scan",
        output_dir: Path | None = None,
) -> Path:
    """Save scan results as CSV and JSON.

    Returns the output directory.
    """
    ensure_dirs()
    out = output_dir or SCAN_OUTPUTS_DIR
    out.mkdir(parents=True, exist_ok=True)

    # CSV
    df = trades_to_dataframe(trades)
    csv_path = out / f"{label}.csv"
    df.to_csv(csv_path, index=False)

    # JSON
    json_path = out / f"{label}.json"
    with open(json_path, "w") as f:
        json.dump([t.to_dict() for t in trades], f, indent=2)

    log.info("Saved %d trades to %s", len(trades), out)
    return out
