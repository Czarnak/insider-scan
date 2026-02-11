#!/usr/bin/env python3
"""Update data/congress_members.json with current legislators.

Federal legislators are fetched from the unitedstates/congress-legislators
GitHub repository (public domain, maintained by civic tech community).

State legislators can optionally be fetched from the Open States API
(https://v3.openstates.org) — requires a free API key set via
OPENSTATES_API_KEY environment variable.

Usage:
    # Federal only (no API key needed)
    python scripts/update_congress.py

    # Federal + state legislators
    OPENSTATES_API_KEY=your_key python scripts/update_congress.py --include-state

    # Dry run — print to stdout without writing file
    python scripts/update_congress.py --dry-run

    # Custom output path
    python scripts/update_congress.py --output /path/to/members.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Add project root to path so we can import project modules
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root / "src"))

import requests

FEDERAL_URL = (
    "https://unitedstates.github.io/congress-legislators/legislators-current.yaml"
    #"congress-legislators/refs/heads/main/legislators-current.yaml"
)
FEDERAL_FALLBACK_URL = (
    "https://unitedstates.github.io/congress-legislators/legislators-current.json"
    #"congress-legislators/refs/heads/main/legislators-current.json"
)
OPENSTATES_PEOPLE_URL = "https://v3.openstates.org/people"

DEFAULT_OUTPUT = _project_root / "data" / "congress_members.json"


# -----------------------------------------------------------------------
# Federal legislators (GitHub — no API key needed)
# -----------------------------------------------------------------------

def fetch_federal_legislators() -> list[dict]:
    """Fetch current federal legislators from the unitedstates project.

    Returns a list of dicts with keys: name, state, chamber, party, level,
    bioguide_id, first_name, last_name.
    """
    members = []

    # Try YAML first (more commonly used format)
    try:
        print("Fetching federal legislators from GitHub (YAML)...")
        resp = requests.get(FEDERAL_URL, timeout=30)
        resp.raise_for_status()

        import yaml
        raw = yaml.safe_load(resp.text)

        for person in raw:
            latest_term = person.get("terms", [{}])[-1]
            name = person.get("name", {})

            last = name.get("last", "")
            first = name.get("first", "")
            official_full = name.get("official_full", f"{first} {last}")

            # Use "Last First" format for matching consistency
            display_name = f"{last} {first}"

            chamber_raw = latest_term.get("type", "")
            chamber = "Senate" if chamber_raw == "sen" else "House"

            members.append({
                "name": display_name,
                "first_name": first,
                "last_name": last,
                "official_name": official_full,
                "state": latest_term.get("state", ""),
                "chamber": chamber,
                "party": latest_term.get("party", ""),
                "level": "federal",
                "bioguide_id": person.get("id", {}).get("bioguide", ""),
            })

        print(f"  Found {len(members)} federal legislators")
        return members

    except Exception as exc:
        print(f"  YAML fetch failed: {exc}")

    # Fallback: try JSON format
    try:
        print("  Trying JSON fallback...")
        resp = requests.get(FEDERAL_FALLBACK_URL, timeout=30)
        resp.raise_for_status()

        raw = resp.json()
        for person in raw:
            latest_term = person.get("terms", [{}])[-1]
            name = person.get("name", {})
            last = name.get("last", "")
            first = name.get("first", "")
            display_name = f"{last} {first}"
            chamber_raw = latest_term.get("type", "")
            chamber = "Senate" if chamber_raw == "sen" else "House"

            members.append({
                "name": display_name,
                "first_name": first,
                "last_name": last,
                "official_name": name.get("official_full", f"{first} {last}"),
                "state": latest_term.get("state", ""),
                "chamber": chamber,
                "party": latest_term.get("party", ""),
                "level": "federal",
                "bioguide_id": person.get("id", {}).get("bioguide", ""),
            })

        print(f"  Found {len(members)} federal legislators (JSON fallback)")
        return members

    except Exception as exc:
        print(f"  JSON fallback also failed: {exc}")
        return []


# -----------------------------------------------------------------------
# State legislators (Open States API — requires free API key)
# -----------------------------------------------------------------------

def fetch_state_legislators(api_key: str) -> list[dict]:
    """Fetch state legislators from the Open States API.

    Requires a free API key from https://v3.openstates.org.

    Paginates through all results (the API returns ~100 per page).
    """
    members = []
    page = 1
    max_pages = 80  # Safety limit (~7500 state legislators across US)

    headers = {"X-API-KEY": api_key}

    print("Fetching state legislators from Open States API...")

    while page <= max_pages:
        try:
            resp = requests.get(
                OPENSTATES_PEOPLE_URL,
                headers=headers,
                params={"page": page, "per_page": 100},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results", [])
            if not results:
                break

            for person in results:
                name = person.get("name", "")
                parts = name.split(", ") if ", " in name else name.rsplit(" ", 1)

                if len(parts) == 2 and ", " in name:
                    last, first = parts
                elif len(parts) == 2:
                    first, last = parts
                else:
                    first, last = name, ""

                # Determine state from jurisdiction
                jurisdiction = person.get("jurisdiction", {})
                state_name = jurisdiction.get("name", "")

                # Chamber from current_role
                role = person.get("current_role", {})
                chamber_raw = role.get("org_classification", "")
                if "senate" in chamber_raw.lower() or "upper" in chamber_raw.lower():
                    chamber = "State Senate"
                else:
                    chamber = "State House"

                party = person.get("party", "")

                members.append({
                    "name": f"{last} {first}".strip(),
                    "first_name": first,
                    "last_name": last,
                    "official_name": name,
                    "state": state_name,
                    "chamber": chamber,
                    "party": party,
                    "level": "state",
                    "openstates_id": person.get("id", ""),
                })

            pagination = data.get("pagination", {})
            total_pages = pagination.get("max_page", page)
            print(f"  Page {page}/{total_pages} — {len(results)} legislators")

            if page >= total_pages:
                break
            page += 1

        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 401:
                print("  ERROR: Invalid API key. Get a free key at https://v3.openstates.org")
                return []
            print(f"  HTTP error on page {page}: {exc}")
            break
        except Exception as exc:
            print(f"  Error on page {page}: {exc}")
            break

    print(f"  Found {len(members)} state legislators")
    return members


# -----------------------------------------------------------------------
# Merge and save
# -----------------------------------------------------------------------

def merge_and_save(
    federal: list[dict],
    state: list[dict],
    output_path: Path,
    dry_run: bool = False,
) -> None:
    """Merge federal + state lists and write to JSON."""
    combined = federal + state

    # Sort by level (federal first), then state, then name
    combined.sort(key=lambda m: (
        0 if m.get("level") == "federal" else 1,
        m.get("state", ""),
        m.get("name", ""),
    ))

    # Deduplicate by (name, state) — shouldn't happen but just in case
    seen = set()
    deduped = []
    for m in combined:
        key = (m["name"].lower(), m.get("state", "").lower())
        if key not in seen:
            seen.add(key)
            deduped.append(m)

    # Summary
    federal_count = sum(1 for m in deduped if m.get("level") == "federal")
    state_count = sum(1 for m in deduped if m.get("level") == "state")

    print(f"\nTotal: {len(deduped)} legislators ({federal_count} federal, {state_count} state)")

    if dry_run:
        print("\n--- DRY RUN (first 20 entries) ---")
        for m in deduped[:20]:
            print(f"  [{m.get('level', '?'):>7}] {m['name']:<30} {m.get('state', ''):>2}  {m.get('chamber', ''):<15} {m.get('party', '')}")
        if len(deduped) > 20:
            print(f"  ... and {len(deduped) - 20} more")
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(deduped, indent=2), encoding="utf-8")
    print(f"Saved to: {output_path}")


# -----------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Update congress_members.json with current legislators.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/update_congress.py                     # Federal only
  python scripts/update_congress.py --include-state     # Federal + state (needs OPENSTATES_API_KEY)
  python scripts/update_congress.py --dry-run           # Preview without saving
  python scripts/update_congress.py --federal-only      # Explicit federal only
        """,
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output JSON file path (default: data/congress_members.json)",
    )
    parser.add_argument(
        "--include-state",
        action="store_true",
        help="Include state legislators (requires OPENSTATES_API_KEY env var)",
    )
    parser.add_argument(
        "--federal-only",
        action="store_true",
        default=True,
        help="Only fetch federal legislators (default)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print results without saving to file",
    )
    args = parser.parse_args()

    # Fetch federal
    federal = fetch_federal_legislators()
    if not federal:
        print("WARNING: Could not fetch federal legislators. Check internet connection.")

    # Fetch state (optional)
    state = []
    if args.include_state:
        api_key = os.environ.get("OPENSTATES_API_KEY")
        if not api_key:
            print(
                "\nWARNING: OPENSTATES_API_KEY not set. Skipping state legislators.\n"
                "Get a free key at: https://v3.openstates.org\n"
                "Then run: OPENSTATES_API_KEY=your_key python scripts/update_congress.py --include-state"
            )
        else:
            state = fetch_state_legislators(api_key)

    merge_and_save(federal, state, args.output, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
