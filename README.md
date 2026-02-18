# Insider Scanner

Scan insider trades from **secform4.com**, **openinsider.com**, and **SEC EDGAR**. Includes congressional financial disclosure scanning (House and Senate), a live market dashboard with price cards, VIX chart, and Fear & Greed indexes, multi-source deduplication, committee-based sector filtering, and a desktop GUI with EDGAR filing links.

---

## Setup

```bash
git clone <repo-url>
cd insider-scanner
pip install -e ".[dev]"
```

### Requirements

Python 3.11+. Dependencies: `requests`, `beautifulsoup4`, `lxml`, `pandas`, `PySide6`, `pyyaml`, `pdfplumber`, `pyqtgraph`, `numpy`, `yfinance`, `fear_and_greed`.

---

## Usage

### GUI

```bash
insider-scanner
# or
python -m insider_scanner.main
```

The GUI provides:

- **Dashboard**: Live market overview — price cards, VIX chart, Fear & Greed indexes, and configurable indicator tiles with auto-refresh
- **Ticker search**: Enter a ticker and scan secform4.com + openinsider.com simultaneously
- **Latest trades**: Fetch recent insider trades across all tickers, with configurable count (10–500)
- **Watchlist scan**: One-click scan of all tickers in `data/tickers_watchlist.txt` — results merged and deduplicated
- **Source selection**: Toggle secform4 and/or openinsider sources
- **Date range**: Optional start/end filing date pickers with calendar popups — passed to scrapers and applied as filters
- **Filters**: By trade type (Buy/Sell/Exercise), minimum dollar value, Congress-only
- **Results table**: Sortable columns with both filing date and trade date, Congress trades highlighted in red, auto-generated EDGAR filing links
- **EDGAR links**: Double-click a trade → view details, click "Open EDGAR Filing" to open the SEC filing (direct links from secform4, generated search URLs for other sources)
- **Stop scan**: Cancel a running watchlist scan mid-progress
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
│   ├── models.py        # InsiderTrade + CongressTrade dataclasses
│   ├── dashboard.py     # Market data providers, Fear & Greed clients, TTL cache
│   ├── bgeometrics_client.py # BGeometrics free API for MVRV Z-Score, NUPL
│   ├── coinmetrics_client.py # CoinMetrics API client (Pro key optional)
│   ├── coinmetrics_cached_client.py # Disk-cached wrapper for CoinMetrics
│   ├── coinmetrics_indicators_service.py # MVRV/NUPL computation from raw caps
│   ├── secform4.py      # secform4.com scraper (compound-column parser, direct filing links)
│   ├── openinsider.py   # openinsider.com HTML parser + scraper
│   ├── edgar.py         # SEC EDGAR CIK resolver (JSON primary + HTML fallback) + filing URLs
│   ├── senate.py        # Congress member list + trade flagging
│   ├── congress_house.py # House financial disclosures (ZIP index + PTR PDF parsing)
│   ├── congress_senate.py # Senate EFD scraper (session + search + PTR page parsing)
│   └── merger.py        # Multi-source dedup, filtering, export
├── gui/
│   ├── main_window.py   # Main window (default OS style)
│   ├── dashboard_tab.py # Dashboard: live prices, VIX chart, F&G, indicators
│   ├── scan_tab.py      # Insider scan: search, date range, filters, results table, EDGAR links
│   ├── congress_tab.py  # Congress scan: official selection, House/Senate scraping, sector filtering
│   └── widgets.py       # Pandas table model, price/value cards, color helpers
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

### Data Flow — Insider Trades

1. **Resolve**: `edgar.py` resolves ticker → CIK via SEC `company_tickers.json` (cached 24h, HTML fallback)
2. **Scrape**: `secform4.py` fetches CIK-based pages with compound-column parsing (date+type, name+title split by `<br>`); `openinsider.py` fetches ticker-based pages; both produce `InsiderTrade` records
3. **Cache**: HTTP responses are cached locally with configurable TTL (default 1h)
4. **Merge**: `merger.py` deduplicates trades across sources (matching by ticker + name + date + share count)
5. **Flag**: `senate.py` checks insider names against the Congress member list (fuzzy matching)
6. **Verify**: secform4 trades include direct SEC filing links; others get generated EDGAR search URLs
7. **Export**: Results saved as CSV + JSON to `outputs/scans/`

### Data Flow — Congress (House)

1. **Index**: `congress_house.py` downloads yearly ZIP archives from `disclosures-clerk.house.gov` containing XML indexes of all financial disclosure filings. Past years are cached permanently; current year can be refreshed on demand.
2. **Search**: XML index is parsed to find PTR (Periodic Transaction Report) filings matching the selected official and date range. Multi-year ranges download multiple indexes as needed.
3. **Fetch**: Individual PTR PDFs are downloaded and cached locally under `data/house_disclosures/{year}/pdfs/`.
4. **Parse**: `pdfplumber` extracts transaction tables from electronically-filed PDFs. Scanned/handwritten PDFs are detected and skipped.
5. **Convert**: Raw table rows are converted to `CongressTrade` records with parsed tickers (from asset descriptions), normalized amount ranges, owner codes, and transaction types.

### Data Flow — Congress (Senate)

1. **Session**: `congress_senate.py` establishes an authenticated session with `efdsearch.senate.gov` by accepting the prohibition agreement and obtaining a CSRF token.
2. **Search**: POST to the EFD JSON API with senator name, report type (PTR), and date range. Results include links to individual PTR pages. Paper filings (scanned PDFs) are automatically filtered out.
3. **Parse**: Each electronic PTR page contains an HTML table with columns for transaction date, owner, ticker, asset name, type, amount range, and comment. These are parsed via BeautifulSoup.
4. **Convert**: Transactions are converted to `CongressTrade` records. Tickers are read directly from the "Ticker" column when available; when the ticker is "--", it's extracted from the asset description (e.g. "Vanguard ETF (BND)" → BND).

### Dashboard Tab

The **Dashboard** tab provides live market overview data, refreshing every 60 seconds:

- **Price cards**: Gold, Silver, Crude Oil, S&P 500, and Nasdaq futures with 1-day % change and color-coded backgrounds (green for up, red for down)
- **VIX chart**: 30-day VIX history rendered as a line chart using pyqtgraph with date axis
- **Fear & Greed indexes**: Stocks (CNN via `fear_and_greed` library), Gold (JM Bullion), and Crypto (Alternative.me) with score-based coloring
- **Indicator tiles**: Configurable grid of crypto/macro indicators (MVRV Z-Score, NUPL, RSI, VDD, Price vs LTH RP, CBBI) with band-based color coding
- **On-chain data**: MVRV Z-Score and NUPL sourced from BGeometrics free API (bitcoin-data.com); RSI calculated locally from BTC-USD price; CBBI from colintalkscrypto.com
- **Threading guard**: Prevents worker accumulation when data sources are slow — queued refreshes wait for the current batch to finish
- **In-memory caching**: TTL-based cache (10 min for prices, 30–60 min for F&G, 6 hours for on-chain indicators) avoids redundant API calls

The dashboard uses dependency injection via a `MarketDataProvider` Protocol, making it straightforward to swap data sources or inject mocks for testing.

### Congress Tab — GUI Integration

The **Congress Scan** tab provides a full GUI workflow for scanning congressional financial disclosures:

- **Official selection**: searchable dropdown populated from `congress_members.json`, with an "All" option
- **Source checkboxes**: independently toggle House and Senate scrapers
- **Date range**: optional filing date filter
- **Filters**: trade type (Purchase/Sale/Exchange), minimum dollar amount, and committee-based sector filtering
- **Background scanning**: threaded execution with progress bar and cancellable stop button
- **Results table**: sortable columns for filing date, trade date, official, chamber, ticker, asset, type, owner, amount range, and source
- **Detail panel**: double-click a row to see full details including official's committee sectors
- **Open Filing**: launches the original disclosure page (House PDF or Senate PTR) in browser
- **Save**: exports filtered results to CSV + JSON

### SEC EDGAR Compliance

All EDGAR requests use a proper `User-Agent` header and are rate-limited to 10 requests/second as required by SEC policy. The User-Agent is configurable via the `SEC_USER_AGENT` environment variable.

---

## Data Files

| File | Description |
|------|-------------|
| `data/congress_members.json` | Congress member list with committee assignments and sector mappings |
| `data/tickers_watchlist.txt` | Default ticker symbols |
| `data/house_disclosures/` | Cached House financial disclosure indexes (auto-populated) |

The Congress member list is populated by `scripts/update_congress.py` and includes committee assignments and sector mappings derived from the [unitedstates/congress-legislators](https://github.com/unitedstates/congress-legislators) project.

### Congress Data Model

Congress financial disclosures differ from standard insider trades. Instead of exact transaction values, they report dollar ranges (e.g. "$1,001 – $15,000"). The `CongressTrade` dataclass in `models.py` handles this with `amount_range` (original string), `amount_low` and `amount_high` (parsed floats), plus fields for `owner` (Self/Spouse/Dependent Child/Joint), `asset_description`, and `comment`.

### Committee → Sector Mapping

Each federal legislator is assigned one or more sectors based on their committee assignments. Committees are mapped to sectors via keyword matching (e.g. "Armed Services" → Defense, "Financial Services" → Finance). The available sectors are: Defense, Energy, Finance, Technology, Healthcare, Industrials, and Other. The `sector` field is a list — for example, a member serving on both Armed Services and Financial Services is tagged as `["Defense", "Finance"]`. "Other" is only included when no higher-priority sector applies.

**Limitation**: Family member financial disclosures (spouses, children) are not publicly machine-readable and would require paid data services. This is a known limitation documented here.

---

## Scripts

Standalone utility scripts live in `scripts/`.

### `update_congress.py`

Fetches the current list of federal and (optionally) state legislators, enriches them with committee assignments and sector mappings, and writes them to `data/congress_members.json`.

```bash
# Federal only with committee enrichment (no API key needed)
python scripts/update_congress.py

# Federal + state legislators (requires free Open States API key)
OPENSTATES_API_KEY=your_key python scripts/update_congress.py --include-state

# Skip committee enrichment
python scripts/update_congress.py --no-committees

# Preview without saving
python scripts/update_congress.py --dry-run

# Custom output path
python scripts/update_congress.py --output /path/to/members.json
```

Federal data and committee assignments come from the [unitedstates/congress-legislators](https://github.com/unitedstates/congress-legislators) project (public domain, community-maintained YAML). State data uses the [Open States API](https://v3.openstates.org) (free key required).

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

### Test modules

| Module | Tests | Description |
|--------|------:|-------------|
| `test_models.py` | 16 | InsiderTrade + CongressTrade dataclasses, amount range parsing |
| `test_dashboard.py` | 54 | TTLCache, classify_fng, _extract_close, FNG clients, RSI, CBBI, MarketProvider, fetch_all |
| `test_dashboard_widgets.py` | 19 | fg_color, indicator_color band mapping |
| `test_bgeometrics.py` | 21 | BGeometrics text parser, client caching, error handling, endpoint config |
| `test_coinmetrics.py` | 16 | NUPL/MVRV math, indicators service, cached client, 403 fail-fast |
| `test_secform4.py` | 19 | secform4.com compound-column HTML parser |
| `test_openinsider.py` | 13 | openinsider.com scraper |
| `test_edgar.py` | 14 | CIK resolution (JSON + HTML fallback), EDGAR URL builder |
| `test_senate.py` | 14 | Congress member flagging |
| `test_merger.py` | 19 | Deduplication, filtering, export |
| `test_caching.py` | 10 | File cache with TTL |
| `test_config.py` | 7 | Config paths, watchlist loading |
| `test_update_congress.py` | 34 | Committee enrichment, sector mapping |
| `test_congress_house.py` | 52 | House ZIP index, XML parsing, PDF extraction pipeline |
| `test_congress_senate.py` | 36 | Senate EFD session, search, PTR page parsing |
| `test_congress_tab.py` | 23 | Congress tab functions: filter, sector, save, dataframe |
| `test_integration.py` | 22 | End-to-end pipeline: scrapers → filter → save → reload |
| `test_gui.py` | 28+ | Widget creation, controls, interactions (requires display) |
| `test_live.py` | 6 | Live website tests (deselected in CI) |

---

## CI/CD

GitHub Actions runs on push/PR:

- **Test matrix**: Python 3.11 + 3.12 + 3.13 on Ubuntu + Windows
- **Offline tests only**: Live tests excluded via `-m "not live"`
- **GUI tests**: Run under `xvfb-run` on Linux for headless display; skipped on Windows
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

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## License

MIT

---

*Created with Claude AI*
