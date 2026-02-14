"""Scrape insider trades from secform4.com."""

from __future__ import annotations

from datetime import date

from bs4 import BeautifulSoup

from insider_scanner.core.models import InsiderTrade
from insider_scanner.utils.config import SCRAPER_CACHE_DIR
from insider_scanner.utils.http import fetch_url
from insider_scanner.utils.logging import get_logger

log = get_logger("secform4")

BASE_URL = "https://www.secform4.com/insider-trading"


def _parse_date(text: str) -> date | None:
    """Parse date from various formats."""
    text = text.strip()
    if not text or text == "-":
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return date.fromisoformat(text) if fmt == "%Y-%m-%d" else None
        except ValueError:
            pass
    # Fallback: try splitting common formats
    try:
        parts = text.replace("/", "-").split("-")
        if len(parts) == 3:
            if len(parts[0]) == 4:
                return date(int(parts[0]), int(parts[1]), int(parts[2]))
            else:
                return date(int(parts[2]), int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        pass
    return None


def _parse_number(text: str) -> float:
    """Parse a number string, stripping $, commas, parens (negative)."""
    text = text.strip().replace(",", "").replace("$", "")
    if not text or text == "-":
        return 0.0
    negative = False
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1]
        negative = True
    try:
        val = float(text)
        return -val if negative else val
    except ValueError:
        return 0.0


def _classify_trade(text: str) -> str:
    """Map raw trade type text to our enum."""
    t = text.strip().lower()
    if "purchase" in t or "buy" in t:
        return "Buy"
    if "sale" in t or "sell" in t:
        return "Sell"
    if "exercise" in t or "option" in t:
        return "Exercise"
    return "Other"


def scrape_ticker(
    ticker: str,
    use_cache: bool = True,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[InsiderTrade]:
    """Scrape insider trades for a specific ticker from secform4.com.

    Resolves the ticker to a CIK number via SEC's company_tickers.json,
    then fetches the secform4.com page at BASE_URL/{cik}.htm.

    Parameters
    ----------
    ticker : str
        Stock ticker symbol (e.g. "AAPL").
    use_cache : bool
        Whether to use the file cache.
    start_date : date or None
        Only include trades with filing_date on or after this date.
    end_date : date or None
        Only include trades with filing_date on or before this date.

    Returns
    -------
    list of InsiderTrade
    """
    from insider_scanner.core.edgar import resolve_cik_from_json

    # Resolve ticker → CIK (raw, not zero-padded)
    raw_cik = resolve_cik_from_json(ticker, use_cache=use_cache)
    if not raw_cik:
        log.warning("Could not resolve CIK for %s — skipping secform4", ticker)
        return []

    url = f"{BASE_URL}/{raw_cik}.htm"
    cache_dir = SCRAPER_CACHE_DIR if use_cache else None

    try:
        html = fetch_url(url, cache_dir=cache_dir, cache_ttl=3600)
    except Exception as exc:
        log.warning("Failed to fetch %s: %s", url, exc)
        return []

    trades = parse_secform4_html(html, ticker)

    # Post-filter by filing date (secform4 doesn't support date params in URL)
    if start_date:
        trades = [t for t in trades if t.filing_date and t.filing_date >= start_date]
    if end_date:
        trades = [t for t in trades if t.filing_date and t.filing_date <= end_date]

    return trades


def parse_secform4_html(html: str, ticker: str = "") -> list[InsiderTrade]:
    """Parse insider trades from secform4.com HTML.

    Parameters
    ----------
    html : str
        Raw HTML from secform4.com.
    ticker : str
        Ticker to assign to trades.

    Returns
    -------
    list of InsiderTrade
    """
    soup = BeautifulSoup(html, "lxml")
    trades: list[InsiderTrade] = []

    # Look for the main data table
    tables = soup.find_all("table")
    if not tables:
        log.debug("No tables found for %s", ticker)
        return trades

    # Find the table with insider trading data (typically the largest one)
    data_table = None
    for table in tables:
        rows = table.find_all("tr")
        if len(rows) > 2:
            # Check header for insider-trade keywords
            header = table.find("tr")
            if header:
                header_text = header.get_text().lower()
                if any(kw in header_text for kw in ("insider", "name", "title", "shares", "price", "date")):
                    data_table = table
                    break

    if data_table is None:
        # Fallback: use the largest table
        data_table = max(tables, key=lambda t: len(t.find_all("tr")))

    rows = data_table.find_all("tr")
    if len(rows) < 2:
        return trades

    # Parse header to find column indices
    header_cells = rows[0].find_all(["th", "td"])
    headers = [c.get_text(strip=True).lower() for c in header_cells]

    col_map = {}
    for i, h in enumerate(headers):
        if "insider" in h or "name" in h:
            col_map.setdefault("name", i)
        elif "title" in h or "relationship" in h:
            col_map.setdefault("title", i)
        elif "transaction" in h or "type" in h:
            col_map.setdefault("type", i)
        elif "date" in h and "filing" not in h:
            col_map.setdefault("trade_date", i)
        elif "filing" in h and "date" in h:
            col_map.setdefault("filing_date", i)
        elif "shares" in h and "owned" not in h:
            col_map.setdefault("shares", i)
        elif "price" in h:
            col_map.setdefault("price", i)
        elif "value" in h:
            col_map.setdefault("value", i)
        elif "owned" in h:
            col_map.setdefault("owned_after", i)

    # Parse data rows
    for row in rows[1:]:
        cells = row.find_all("td")
        if len(cells) < 3:
            continue

        def cell_text(key: str) -> str:
            idx = col_map.get(key)
            if idx is not None and idx < len(cells):
                return cells[idx].get_text(strip=True)
            return ""

        trade = InsiderTrade(
            ticker=ticker.upper(),
            insider_name=cell_text("name"),
            insider_title=cell_text("title"),
            trade_type=_classify_trade(cell_text("type")),
            trade_date=_parse_date(cell_text("trade_date")),
            filing_date=_parse_date(cell_text("filing_date")),
            shares=_parse_number(cell_text("shares")),
            price=_parse_number(cell_text("price")),
            value=_parse_number(cell_text("value")),
            shares_owned_after=_parse_number(cell_text("owned_after")),
            source="secform4",
        )

        if trade.insider_name or trade.shares != 0:
            trades.append(trade)

    log.info("secform4: parsed %d trades for %s", len(trades), ticker)
    return trades
