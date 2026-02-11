"""Congress member list management and trade flagging.

Maintains a local JSON file of known Congress members so trades
by these individuals can be flagged in scan results.

Note: Family member disclosure data is not publicly machine-readable
and would require paid data services. This module documents that limitation.
"""

from __future__ import annotations

import json
from pathlib import Path

from insider_scanner.core.models import InsiderTrade
from insider_scanner.utils.config import CONGRESS_FILE
from insider_scanner.utils.logging import get_logger

log = get_logger("senate")


def load_congress_members(path: Path | None = None) -> list[dict]:
    """Load the Congress member list from disk.

    Returns a list of dicts, each with at least ``"name"`` and optional
    ``"state"``, ``"chamber"`` (Senate/House), ``"party"``.
    """
    p = path or CONGRESS_FILE
    if not p.exists():
        log.debug("Congress file not found: %s", p)
        return []

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Failed to load congress file: %s", exc)
        return []


def save_congress_members(members: list[dict], path: Path | None = None) -> None:
    """Save the Congress member list to disk."""
    p = path or CONGRESS_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(members, indent=2), encoding="utf-8")
    log.info("Saved %d congress members to %s", len(members), p)


def _normalize_name(name: str) -> str:
    """Normalize a name for fuzzy matching (lowercase, strip suffixes)."""
    name = name.lower().strip()
    for suffix in (" jr", " sr", " iii", " ii", " iv", ","):
        name = name.replace(suffix, "")
    return " ".join(name.split())  # collapse whitespace


def flag_congress_trades(
    trades: list[InsiderTrade],
    members: list[dict] | None = None,
) -> list[InsiderTrade]:
    """Flag trades where the insider name matches a Congress member.

    Parameters
    ----------
    trades : list of InsiderTrade
        Trades to check.
    members : list of dict or None
        Congress member list. If None, loads from disk.

    Returns
    -------
    list of InsiderTrade
        Same list, mutated in place (is_congress and congress_member set).
    """
    if members is None:
        members = load_congress_members()

    if not members:
        return trades

    # Build lookup set of normalized names
    member_lookup: dict[str, str] = {}
    for m in members:
        raw_name = m.get("name", "")
        if raw_name:
            norm = _normalize_name(raw_name)
            member_lookup[norm] = raw_name

    for trade in trades:
        norm_insider = _normalize_name(trade.insider_name)

        # Exact match
        if norm_insider in member_lookup:
            trade.is_congress = True
            trade.congress_member = member_lookup[norm_insider]
            continue

        # Partial match: check if any member name is contained in insider name or vice versa
        for norm_member, raw_member in member_lookup.items():
            if norm_member in norm_insider or norm_insider in norm_member:
                trade.is_congress = True
                trade.congress_member = raw_member
                break

    flagged_count = sum(1 for t in trades if t.is_congress)
    if flagged_count:
        log.info("Flagged %d/%d trades as congress-related", flagged_count, len(trades))

    return trades


# Default seed data
DEFAULT_CONGRESS_MEMBERS: list[dict] = [
    {"name": "Pelosi Nancy", "state": "CA", "chamber": "House", "party": "D"},
    {"name": "Tuberville Tommy", "state": "AL", "chamber": "Senate", "party": "R"},
    {"name": "Crenshaw Dan", "state": "TX", "chamber": "House", "party": "R"},
    {"name": "Ossoff Jon", "state": "GA", "chamber": "Senate", "party": "D"},
    {"name": "Sullivan Dan", "state": "AK", "chamber": "Senate", "party": "R"},
    {"name": "Hagerty Bill", "state": "TN", "chamber": "Senate", "party": "R"},
    {"name": "Manchin Joe", "state": "WV", "chamber": "Senate", "party": "D"},
    {"name": "Lummis Cynthia", "state": "WY", "chamber": "Senate", "party": "R"},
]


def init_default_congress_file(path: Path | None = None) -> None:
    """Create the default congress members file if it doesn't exist."""
    p = path or CONGRESS_FILE
    if not p.exists():
        save_congress_members(DEFAULT_CONGRESS_MEMBERS, p)
