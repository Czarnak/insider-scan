# Insider Scanner

Scan insider trades from **secform4.com**, **openinsider.com**, and **SEC EDGAR**. Includes Congress member trade flagging, multi-source deduplication, filtering, and a desktop GUI with EDGAR filing links.

---

## Setup

```bash
git clone <repo-url>
cd insider-scanner
pip install -e ".[dev]"
```

### Requirements

Python 3.11+. Dependencies: `requests`, `beautifulsoup4`, `lxml`, `pandas`, `PySide6`, `pyyaml`.

---

## Usage

### GUI

```bash
insider-scanner
# or
python -m insider_scanner.main
```

The GUI provides:

- **Ticker search**: Enter a ticker and scan secform4.com + openinsider.com simultaneously
- **Latest trades**: Fetch recent insider trades across all tickers
- **Source selection**: Toggle secform4 and/or openinsider sources
- **Date range**: Optional start/end date pickers with calendar popups — passed to scrapers and applied as filters
- **Filters**: By trade type (Buy/Sell/Exercise), minimum dollar value, Congress-only
- **Results table**: Sortable columns, Congress trades highlighted in red
- **EDGAR links**: Double-click a trade → view details, click "Open EDGAR Filing" to verify on SEC.gov
- **CIK resolver**: Resolve any ticker to its SEC CIK number and open the filings page
- **Export**: Save scan results as CSV + JSON

### CLI

```bash
# Scan a specific ticker
insider-scanner-cli scan AAPL
insider-scanner-cli scan AAPL --type Buy --min-value 1000000 --save

# Scan with date range
insider-scanner-cli scan AAPL --since 2025-01-01 --until 2025-06-30

# Fetch latest insider trades
insider-scanner-cli latest --count 50 --save
insider-scanner-cli latest --since 2025-06-01

# Resolve SEC CIK
insider-scanner-cli cik AAPL

# Initialize default Congress member list
insider-scanner-cli init-congress

# Congress-only filter
insider-scanner-cli scan AAPL --congress-only
```

---

## Architecture

```
src/insider_scanner/
├── core/
│   ├── models.py        # InsiderTrade dataclass (unified record)
│   ├── secform4.py      # secform4.com HTML parser + scraper
│   ├── openinsider.py   # openinsider.com HTML parser + scraper
│   ├── edgar.py         # SEC EDGAR CIK resolver + filing URLs
│   ├── senate.py        # Congress member list + trade flagging
│   └── merger.py        # Multi-source dedup, filtering, export
├── gui/
│   ├── main_window.py   # Main window (default OS style)
│   ├── scan_tab.py      # Search, date range, filters, results table, EDGAR links
│   └── widgets.py       # Pandas table model with Congress highlighting
├── utils/
│   ├── config.py        # Paths, SEC compliance constants
│   ├── logging.py       # Logging setup
│   ├── caching.py       # File-based cache with TTL expiry
│   ├── http.py          # Rate-limited HTTP with SEC User-Agent
│   └── threading.py     # Background worker for GUI
├── main.py              # GUI entry point
└── cli.py               # CLI entry point

scripts/
└── update_congress.py   # Fetch current federal + state legislators
```

### Data Flow

1. **Scrape**: `secform4.py` and `openinsider.py` parse HTML tables into `InsiderTrade` records
2. **Cache**: HTTP responses are cached locally with configurable TTL (default 1h)
3. **Merge**: `merger.py` deduplicates trades across sources (matching by ticker + name + date + share count)
4. **Flag**: `senate.py` checks insider names against the Congress member list (fuzzy matching)
5. **Verify**: `edgar.py` generates SEC EDGAR filing URLs for any trade (opens in browser)
6. **Export**: Results saved as CSV + JSON to `outputs/scans/`

### SEC EDGAR Compliance

All EDGAR requests use a proper `User-Agent` header and are rate-limited to 10 requests/second as required by SEC policy. The User-Agent is configurable via the `SEC_USER_AGENT` environment variable.

---

## Data Files

| File | Description |
|------|-------------|
| `data/congress_members.json` | Congress member list for trade flagging (editable) |
| `data/tickers_watchlist.txt` | Default ticker symbols |

The Congress member list ships with 8 well-known trading Congress members and can be edited or extended.

**Limitation**: Family member financial disclosures (spouses, children) are not publicly machine-readable and would require paid data services. This is a known limitation documented here.

---

## Scripts

Standalone utility scripts live in `scripts/`.

### `update_congress.py`

Fetches the current list of federal and (optionally) state legislators and writes them to `data/congress_members.json`.

```bash
# Federal only (no API key needed — uses unitedstates/congress-legislators on GitHub)
python scripts/update_congress.py

# Federal + state legislators (requires free Open States API key)
OPENSTATES_API_KEY=your_key python scripts/update_congress.py --include-state

# Preview without saving
python scripts/update_congress.py --dry-run

# Custom output path
python scripts/update_congress.py --output /path/to/members.json
```

Federal data comes from the [unitedstates/congress-legislators](https://github.com/unitedstates/congress-legislators) project (public domain, community-maintained YAML). State data uses the [Open States API](https://v3.openstates.org) (free key required).

---

## Tests

```bash
# Run all offline tests (default)
pytest -m "not live" -v

# Run only live integration tests (requires internet)
pytest -m live -v

# Run everything
pytest -v

# With coverage
pytest -m "not live" --cov=insider_scanner -v
```

Tests are split into two categories:

- **Offline (mocked)**: Use the `responses` library to mock HTTP calls. No internet needed. Run by default in CI.
- **Live integration**: Hit real websites. Marked with `@pytest.mark.live`. Excluded from CI. Run manually with `-m live`.

---

## CI/CD

GitHub Actions runs on push/PR:

- **Test matrix**: Python 3.11 + 3.12 on Ubuntu + Windows
- **Offline tests only**: Live tests excluded via `-m "not live"`
- **Lint**: `ruff check` on `src/` and `tests/`
- **Coverage**: Uploaded as artifact for Python 3.12 Ubuntu

---

## Adding Sources

To add a new scraping source:

1. Create `src/insider_scanner/core/newsource.py` with a `scrape_ticker(ticker) -> list[InsiderTrade]` function
2. Have the parser return `InsiderTrade` records with `source="newsource"`
3. Add it to the merger pipeline in `scan_tab.py` and `cli.py`
4. Write mocked tests in `tests/test_newsource.py`

---

## License

MIT
