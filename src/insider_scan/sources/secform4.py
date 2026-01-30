from __future__ import annotations

import hashlib
import time
from datetime import date
from typing import Any

import pandas as pd
import requests
from dateutil.parser import parse as dtparse
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from insider_scan.config import HTTP, SECFORM4_BASE
from insider_scan.models import TransactionRecord
from insider_scan.sources.sec_edgar import ticker_to_cik, extract_sec_link_from_text


# ---------- Session with retries ----------
_SESSION: requests.Session | None = None

def _session() -> requests.Session:
    global _SESSION
    if _SESSION is not None:
        return _SESSION

    s = requests.Session()
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
    }


def _sleep_throttle():
    time.sleep(0.6)


def _parse_date(s: Any) -> date | None:
    if s is None:
        return None
    txt = str(s).strip()
    if not txt or txt.lower() in {"nan", "na", "n/a", "none", "—"}:
        return None
    try:
        return dtparse(txt, fuzzy=True).date()
    except Exception:
        return None


def _parse_float(s: Any) -> float | None:
    if s is None:
        return None
    txt = str(s).strip()
    if not txt or txt.lower() in {"nan", "na", "n/a", "none", "—"}:
        return None
    txt = txt.replace(",", "").replace("$", "").strip()
    txt = txt.replace("(", "-").replace(")", "")
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
    if "10%" in r or "owner" in r:
        return "10% Owner"
    if "officer" in r:
        return "Officer"
    if "congress" in r or "senate" in r or "house" in r:
        return "Congress"
    return "Other"


def _txn_type_bucket(text: str | None) -> str:
    if not text:
        return "Other"
    t = str(text).lower()
    if "buy" in t or "purchase" in t:
        return "Buy"
    if "award" in t or "grant" in t:
        return "Award"
    if "option" in t:
        return "Option"
    if "sale" in t or "sell" in t:
        return "Other"  # minimal requirement: Buy; reszta jako Other
    return "Other"


def _event_id(ticker: str, insider: str | None, trade_date: date | None, shares: float | None,
              price: float | None, txn_type: str, source: str) -> str:
    key = f"{ticker}|{insider or ''}|{trade_date.isoformat() if trade_date else ''}|{shares or ''}|{price or ''}|{txn_type}|{source}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def _get_html(url: str) -> str:
    _sleep_throttle()
    timeout = (8.0, float(HTTP.timeout_s))
    r = _session().get(url, headers=_headers(), timeout=timeout)
    if r.status_code >= 400:
        raise requests.HTTPError(f"SecForm4 HTTP {r.status_code}", response=r)
    return r.text


def _resolve_company_url_from_ticker(ticker: str) -> tuple[str, str | None]:
    """
    secform4.com for companies uses CIK in path:
      https://www.secform4.com/insider-trading/{cik_int}.htm
    We obtain CIK from SEC ticker map.
    """
    cik10, company_title = ticker_to_cik(ticker)
    if not cik10:
        # fallback (old behavior): try ticker URL (may fail, but keep as last resort)
        return f"{SECFORM4_BASE}/insider-trading/{ticker.upper().strip()}.htm", company_title
    cik_int = str(int(cik10))  # remove leading zeros
    return f"{SECFORM4_BASE}/insider-trading/{cik_int}.htm", company_title


def fetch_secform4(ticker: str, start_date: str) -> list[TransactionRecord]:
    """
    Fetches company insider trading table from secform4.com using CIK-based URL.

    Filtering: keep rows where (reported/filing date >= start_date) OR (transaction date >= start_date).
    Parsing: use pandas.read_html for robustness.
    """
    ticker = ticker.upper().strip()
    start_dt = dtparse(start_date).date()

    url, company_title = _resolve_company_url_from_ticker(ticker)
    html = _get_html(url)

    # read_html returns list of DataFrames for all tables found
    tables = pd.read_html(html, flavor="lxml")
    if not tables:
        return []

    # Choose table that looks like transaction history: contains "Transaction" and "Reported" columns usually
    best = None
    best_score = -1
    for t in tables:
        cols = [str(c).lower() for c in t.columns]
        score = 0
        if any("transaction" in c for c in cols):
            score += 2
        if any("reported" in c or "filing" in c for c in cols):
            score += 2
        if any("insider" in c for c in cols):
            score += 1
        if any("shares" in c for c in cols):
            score += 1
        if score > best_score and len(t) > 0:
            best_score = score
            best = t

    if best is None or best.empty:
        return []

    df = best.copy()
    df.columns = [str(c).strip() for c in df.columns]

    # Heuristic column mapping (site-specific, but tolerant)
    def pick_col(contains: list[str]) -> str | None:
        for c in df.columns:
            cl = c.lower()
            if any(s in cl for s in contains):
                return c
        return None

    col_company = pick_col(["company", "issuer"])
    col_insider = pick_col(["insider", "reporting"])
    col_rel = pick_col(["relationship", "title", "role"])
    col_trade_dt = pick_col(["transaction date", "trade date"])
    col_reported_dt = pick_col(["reported", "filing date", "filed"])
    col_type = pick_col(["transaction", "type"])
    col_shares = pick_col(["shares", "amount"])
    col_price = pick_col(["price"])
    col_value = pick_col(["value", "total"])
    col_view = pick_col(["view"])  # sometimes holds link text; actual link in HTML (not in read_html)

    out: list[TransactionRecord] = []

    for _, r in df.iterrows():
        company = str(r[col_company]).strip() if col_company and pd.notna(r.get(col_company)) else company_title
        insider = str(r[col_insider]).strip() if col_insider and pd.notna(r.get(col_insider)) else None
        rel = str(r[col_rel]).strip() if col_rel and pd.notna(r.get(col_rel)) else None

        trade_dt = _parse_date(r.get(col_trade_dt)) if col_trade_dt else None
        filing_dt = _parse_date(r.get(col_reported_dt)) if col_reported_dt else None

        txn_type = _txn_type_bucket(str(r.get(col_type)) if col_type else None)

        shares = _parse_float(r.get(col_shares)) if col_shares else None
        price = _parse_float(r.get(col_price)) if col_price else None
        value = _parse_float(r.get(col_value)) if col_value else None

        # Filter by date range (best-effort)
        keep = False
        if filing_dt and filing_dt >= start_dt:
            keep = True
        elif trade_dt and trade_dt >= start_dt:
            keep = True
        elif (filing_dt is None and trade_dt is None):
            keep = True
        if not keep:
            continue

        # SEC link: secform4 pages usually have "View" links in HTML; read_html won't keep href.
        # We'll leave sec_link empty here; later SEC enrichment (EDGAR) will fill it anyway.
        sec_link = None

        event_id = _event_id(ticker, insider, trade_dt, shares, price, txn_type, "secform4")

        out.append(
            TransactionRecord(
                ticker=ticker,
                company_name=company,
                insider_name=insider,
                role_relation=_role_bucket(rel) if rel else None,
                transaction_type=txn_type,
                trade_date=trade_dt,
                filing_date=filing_dt,
                shares=shares,
                price=price,
                value_usd=value,
                sec_link=sec_link,
                source="secform4",
                source_url=url,
                confidence="LOW",  # will be upgraded when SEC EDGAR link is built
                event_id=event_id,
            )
        )

    return out
