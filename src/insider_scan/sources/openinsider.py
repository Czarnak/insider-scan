from __future__ import annotations

import hashlib
import re
import time
from datetime import date
from pathlib import Path
from typing import Any

import socket
import requests
from bs4 import BeautifulSoup
from dateutil.parser import parse as dtparse
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from insider_scan.config import HTTP, OPENINSIDER_BASE, CACHE_DIR
from insider_scan.models import TransactionRecord
from insider_scan.sources.sec_edgar import extract_sec_link_from_text


# ---------- Session with robust retries ----------
_SESSION: requests.Session | None = None

def _session() -> requests.Session:
    global _SESSION
    if _SESSION is not None:
        return _SESSION

    s = requests.Session()

    # Retry on transient network / 5xx / 429
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        status=5,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
        respect_retry_after_header=True,
    )

    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    _SESSION = s
    return s


def _headers() -> dict[str, str]:
    return {
        "User-Agent": HTTP.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }


def _sleep_throttle():
    # Be gentler; OpenInsider sometimes chokes under quick bursts
    time.sleep(0.8)


def _cache_file(ticker: str, start_date: str) -> Path:
    p = Path(CACHE_DIR) / "openinsider"
    p.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Z0-9\-]", "_", ticker.upper())
    return p / f"{safe}_{start_date}.html"


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return dtparse(s, fuzzy=True).date()
    except Exception:
        return None


def _parse_float(s: str | None) -> float | None:
    if s is None:
        return None
    txt = str(s).strip()
    if not txt:
        return None
    txt = txt.replace(",", "").replace("$", "").replace("USD", "").strip()
    txt = txt.replace("(", "-").replace(")", "")
    try:
        return float(txt)
    except Exception:
        return None


def _parse_shares(s: str | None) -> float | None:
    if s is None:
        return None
    txt = str(s).strip().replace(",", "")
    txt = re.sub(r"[^\d\.\-]", "", txt)
    if not txt:
        return None
    try:
        return float(txt)
    except Exception:
        return None


def _role_bucket(role: str | None) -> str | None:
    if not role:
        return None
    r = role.lower()
    if "chief executive" in r or r.startswith("ceo"):
        return "CEO"
    if "chief financial" in r or r.startswith("cfo"):
        return "CFO"
    if "director" in r:
        return "Director"
    if "10%" in r or "ten percent" in r or "owner" in r:
        return "10% Owner"
    if "officer" in r:
        return "Officer"
    if "congress" in r or "senate" in r or "house" in r:
        return "Congress"
    return "Other"


def _txn_type_bucket(code: str | None) -> str:
    if not code:
        return "Other"
    c = str(code).strip().upper()
    if c == "P":
        return "Buy"
    if c == "A":
        return "Award"
    if c == "M":
        return "Option"
    return "Other"


def _event_id(ticker: str, insider: str | None, trade_date: date | None, shares: float | None,
              price: float | None, txn_type: str, source: str) -> str:
    key = f"{ticker}|{insider or ''}|{trade_date.isoformat() if trade_date else ''}|{shares or ''}|{price or ''}|{txn_type}|{source}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def _get_html(url: str, params: dict[str, Any]) -> str:
    _sleep_throttle()
    timeout = (5.0, float(HTTP.timeout_s))
    try:
        r = _session().get(url, headers=_headers(), params=params, timeout=timeout)
    except requests.exceptions.ConnectionError as e:
        # WinError 10061 / connection refused -> do not keep hammering retries forever
        raise
    if r.status_code >= 400:
        raise requests.HTTPError(f"OpenInsider HTTP {r.status_code}", response=r)
    return r.text


def fetch_openinsider(ticker: str, start_date: str, use_cache_on_fail: bool = True) -> list[TransactionRecord]:
    """
    Fetch OpenInsider screener rows for given ticker.
    Uses local cache; on connection failure, optionally returns cached HTML if present.
    """
    url = f"{OPENINSIDER_BASE}/screener"
    params = {
        "s": ticker.upper(),
        "o": "",
        "pl": "",
        "ph": "",
        "ll": "",
        "lh": "",
        "fd": start_date,   # filing date from
        "fdr": "",
        "td": "",
        "tdr": "",
        "cd": "",
        "cdr": "",
        "sortcol": 0,
        "cnt": 200,
        "page": 1,
    }

    cache_path = _cache_file(ticker, start_date)

    try:
        html = _get_html(url, params=params)
        cache_path.write_text(html, encoding="utf-8")
    except Exception:
        if use_cache_on_fail and cache_path.exists():
            html = cache_path.read_text(encoding="utf-8", errors="ignore")
        else:
            raise

    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", {"class": re.compile(r".*tinytable.*")})
    if not table:
        return []

    rows = table.find_all("tr")
    if len(rows) < 2:
        return []

    header = [th.get_text(" ", strip=True) for th in rows[0].find_all(["th", "td"])]
    col_idx = {name: i for i, name in enumerate(header)}

    def idx(*names: str) -> int | None:
        for n in names:
            if n in col_idx:
                return col_idx[n]
        return None

    i_ticker = idx("Ticker")
    i_company = idx("Company")
    i_insider = idx("Insider Name", "Insider")
    i_title = idx("Title")
    i_trade_date = idx("Trade Date")
    i_filing_date = idx("Filing Date")
    i_code = idx("Trade Type", "Type")
    i_shares = idx("Shares")
    i_price = idx("Price")
    i_value = idx("Value")
    i_link = idx("SEC Form 4", "SEC")

    out: list[TransactionRecord] = []
    source_url = f"{url}?s={ticker.upper()}&fd={start_date}"

    for tr in rows[1:]:
        tds = tr.find_all("td")
        if not tds:
            continue

        def get_text(i: int | None) -> str | None:
            if i is None or i >= len(tds):
                return None
            return tds[i].get_text(" ", strip=True)

        ticker_txt = (get_text(i_ticker) or ticker.upper()).strip()
        company = get_text(i_company)
        insider = get_text(i_insider)
        title = get_text(i_title)
        trade_dt = _parse_date(get_text(i_trade_date))
        filing_dt = _parse_date(get_text(i_filing_date))
        code = get_text(i_code)
        txn_type = _txn_type_bucket(code)
        shares = _parse_shares(get_text(i_shares))
        price = _parse_float(get_text(i_price))
        value = _parse_float(get_text(i_value))

        sec_link = None
        if i_link is not None and i_link < len(tds):
            a = tds[i_link].find("a")
            if a and a.get("href"):
                href = a["href"]
                sec_link = href if href.startswith("http") else f"{OPENINSIDER_BASE}{href}"
                sec_link = extract_sec_link_from_text(sec_link) or sec_link

        event_id = _event_id(ticker_txt, insider, trade_dt, shares, price, txn_type, "openinsider")

        out.append(
            TransactionRecord(
                ticker=ticker_txt,
                company_name=company,
                insider_name=insider,
                role_relation=_role_bucket(title) if title else None,
                transaction_type=txn_type,
                trade_date=trade_dt,
                filing_date=filing_dt,
                shares=shares,
                price=price,
                value_usd=value,
                sec_link=sec_link,
                source="openinsider",
                source_url=source_url,
                confidence="LOW" if not sec_link else "HIGH",
                event_id=event_id,
            )
        )

    return out
