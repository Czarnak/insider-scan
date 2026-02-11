"""Scrape insider trades from openinsider.com."""

from __future__ import annotations

from datetime import date

from bs4 import BeautifulSoup

from insider_scanner.core.models import InsiderTrade
from insider_scanner.utils.config import SCRAPER_CACHE_DIR
from insider_scanner.utils.http import fetch_url
from insider_scanner.utils.logging import get_logger

log = get_logger("openinsider")

BASE_URL = "http://openinsider.com"


def _parse_date(text: str) -> date | None:
    text = text.strip()
    if not text or text == "-":
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    # Try MM/DD/YYYY
    try:
        parts = text.split("/")
        if len(parts) == 3:
            return date(int(parts[2]), int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        pass
    return None


def _parse_number(text: str) -> float:
    text = text.strip().replace(",", "").replace("$", "").replace("+", "")
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
    t = text.strip().lower()
    if "purchase" in t or "buy" in t or t == "p":
        return "Buy"
    if "sale" in t or "sell" in t or t == "s":
        return "Sell"
    if "exercise" in t or t == "m":
        return "Exercise"
    return "Other"


def scrape_ticker(ticker: str, use_cache: bool = True) -> list[InsiderTrade]:
    """Scrape insider trades for a specific ticker from openinsider.com.

    Parameters
    ----------
    ticker : str
        Stock ticker symbol.
    use_cache : bool
        Whether to use the file cache.

    Returns
    -------
    list of InsiderTrade
    """
    url = f"{BASE_URL}/screener?s={ticker.upper()}&o=&pl=&ph=&st=&lt=&lh=&fd=0&fdr=&td=0&tdr=&feession=&xp=1&vl=&vh=&ocl=&och=&session=&ession=&cnt=100"
    cache_dir = SCRAPER_CACHE_DIR if use_cache else None

    try:
        html = fetch_url(url, cache_dir=cache_dir, cache_ttl=3600)
    except Exception as exc:
        log.warning("Failed to fetch %s: %s", url, exc)
        return []

    return parse_openinsider_html(html, ticker)


def scrape_latest(count: int = 100, use_cache: bool = True) -> list[InsiderTrade]:
    """Scrape the latest insider trades across all tickers.

    Parameters
    ----------
    count : int
        Number of recent trades to fetch.
    use_cache : bool
        Whether to use the file cache.

    Returns
    -------
    list of InsiderTrade
    """
    url = f"{BASE_URL}/screener?s=&o=&pl=&ph=&st=&lt=&lh=&fd=0&fdr=&td=0&tdr=&feession=&xp=1&vl=&vh=&ocl=&och=&session=&ession=&cnt={count}"
    cache_dir = SCRAPER_CACHE_DIR if use_cache else None

    try:
        html = fetch_url(url, cache_dir=cache_dir, cache_ttl=1800)
    except Exception as exc:
        log.warning("Failed to fetch latest: %s", exc)
        return []

    return parse_openinsider_html(html)


def parse_openinsider_html(html: str, ticker: str = "") -> list[InsiderTrade]:
    """Parse insider trades from openinsider.com HTML.

    Parameters
    ----------
    html : str
        Raw HTML response body.
    ticker : str
        If empty, ticker is extracted from each row.

    Returns
    -------
    list of InsiderTrade
    """
    soup = BeautifulSoup(html, "lxml")
    trades: list[InsiderTrade] = []

    # openinsider uses a table with class "tinytable"
    table = soup.find("table", class_="tinytable")
    if table is None:
        # Fallback: largest table
        tables = soup.find_all("table")
        if not tables:
            log.debug("No tables found")
            return trades
        table = max(tables, key=lambda t: len(t.find_all("tr")))

    rows = table.find_all("tr")
    if len(rows) < 2:
        return trades

    # Parse header
    header_cells = rows[0].find_all(["th", "td"])
    headers = [c.get_text(strip=True).lower() for c in header_cells]

    col_map = {}
    for i, h in enumerate(headers):
        if h in ("x",):
            continue
        if "filing" in h and "date" in h:
            col_map.setdefault("filing_date", i)
        elif "trade" in h and "date" in h:
            col_map.setdefault("trade_date", i)
        elif "ticker" in h:
            col_map.setdefault("ticker", i)
        elif "company" in h:
            col_map.setdefault("company", i)
        elif "insider" in h and "name" in h:
            col_map.setdefault("name", i)
        elif "title" in h:
            col_map.setdefault("title", i)
        elif "trade type" in h or "type" in h:
            col_map.setdefault("type", i)
        elif "qty" in h or "shares" in h and "owned" not in h:
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
        if len(cells) < 4:
            continue

        def cell_text(key: str) -> str:
            idx = col_map.get(key)
            if idx is not None and idx < len(cells):
                return cells[idx].get_text(strip=True)
            return ""

        row_ticker = cell_text("ticker") or ticker.upper()

        trade = InsiderTrade(
            ticker=row_ticker.upper(),
            company=cell_text("company"),
            insider_name=cell_text("name"),
            insider_title=cell_text("title"),
            trade_type=_classify_trade(cell_text("type")),
            trade_date=_parse_date(cell_text("trade_date")),
            filing_date=_parse_date(cell_text("filing_date")),
            shares=_parse_number(cell_text("shares")),
            price=_parse_number(cell_text("price")),
            value=_parse_number(cell_text("value")),
            shares_owned_after=_parse_number(cell_text("owned_after")),
            source="openinsider",
        )

        if trade.insider_name or trade.shares != 0:
            trades.append(trade)

    log.info("openinsider: parsed %d trades for %s", len(trades), ticker or "latest")
    return trades
