from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import requests
from dateutil.parser import parse as dtparse
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from insider_scan.config import HTTP, CACHE_DIR, SEC_DATA_BASE, SEC_WWW_BASE


def _sec_headers() -> dict[str, str]:
    return {
        "User-Agent": HTTP.user_agent,
        "Accept-Encoding": "gzip, deflate",
        "Accept": "application/json,text/html,*/*",
        "Connection": "keep-alive",
    }


def _sleep_throttle():
    time.sleep(HTTP.throttle_s)


class SecEdgarError(RuntimeError):
    pass


@dataclass(frozen=True)
class EdgarFiling:
    cik: str                # zero-padded 10
    accession_no: str       # with dashes
    filing_date: date | None
    form: str | None
    primary_doc: str | None


def _cache_path(name: str) -> Path:
    return Path(CACHE_DIR) / name


def _read_cache_json(path: Path) -> Any | None:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _write_cache_json(path: Path, data: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        # cache is best-effort
        pass


@retry(
    retry=retry_if_exception_type((requests.RequestException, SecEdgarError)),
    stop=stop_after_attempt(HTTP.max_retries),
    wait=wait_exponential(multiplier=0.8, min=0.8, max=8),
)
def _get_json(url: str) -> Any:
    _sleep_throttle()
    r = requests.get(url, headers=_sec_headers(), timeout=HTTP.timeout_s)
    if r.status_code >= 400:
        raise SecEdgarError(f"SEC GET {url} -> {r.status_code}")
    return r.json()


def get_company_tickers_map(force_refresh: bool = False) -> dict[str, dict[str, Any]]:
    """
    Returns mapping: TICKER -> {cik_str, title, ...}
    Source: https://www.sec.gov/files/company_tickers.json
    """
    cache = _cache_path("sec_company_tickers.json")
    if not force_refresh:
        cached = _read_cache_json(cache)
        if isinstance(cached, dict) and cached:
            # Convert numeric keys dict to ticker map if already processed
            if "AAPL" in cached:
                return cached
            # else it's raw numeric mapping; fall-through to process
            raw = cached
        else:
            raw = None
    else:
        raw = None

    if raw is None:
        url = f"{SEC_WWW_BASE}/files/company_tickers.json"
        raw = _get_json(url)
        _write_cache_json(cache, raw)

    ticker_map: dict[str, dict[str, Any]] = {}
    # raw format: {"0": {"cik_str": 320193, "ticker":"AAPL", "title":"Apple Inc."}, ...}
    for _, v in raw.items():
        try:
            t = str(v.get("ticker", "")).upper().strip()
            if not t:
                continue
            ticker_map[t] = v
        except Exception:
            continue

    _write_cache_json(cache, ticker_map)
    return ticker_map


def ticker_to_cik(ticker: str) -> tuple[str | None, str | None]:
    """
    Returns (cik10, company_title) or (None, None).
    """
    m = get_company_tickers_map()
    v = m.get(ticker.upper().strip())
    if not v:
        return None, None
    cik_num = v.get("cik_str")
    title = v.get("title")
    if cik_num is None:
        return None, title
    cik10 = str(cik_num).zfill(10)
    return cik10, title


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return dtparse(str(s)).date()
    except Exception:
        return None


def get_submissions(cik10: str) -> dict[str, Any]:
    cache = _cache_path(f"sec_submissions_{cik10}.json")
    cached = _read_cache_json(cache)
    if isinstance(cached, dict) and cached:
        return cached
    url = f"{SEC_DATA_BASE}/submissions/CIK{cik10}.json"
    data = _get_json(url)
    _write_cache_json(cache, data)
    return data


def find_form4_filing_near(
    cik10: str,
    trade_date: date | None,
    filing_date_hint: date | None = None,
    max_days: int = 10,
) -> EdgarFiling | None:
    """
    Searches recent filings list for Form 4 / 4/A.
    Matching strategy:
    - if filing_date_hint: pick closest to hint
    - else if trade_date: pick closest filing date to trade_date (often +0..2 days)
    """
    subs = get_submissions(cik10)
    recent = (subs.get("filings", {}) or {}).get("recent", {}) or {}

    forms = recent.get("form", []) or []
    filing_dates = recent.get("filingDate", []) or []
    accession_nos = recent.get("accessionNumber", []) or []
    primary_docs = recent.get("primaryDocument", []) or []

    candidates: list[EdgarFiling] = []
    for i in range(min(len(forms), len(filing_dates), len(accession_nos), len(primary_docs))):
        form = str(forms[i]) if forms[i] is not None else None
        if not form:
            continue
        if form not in ("4", "4/A"):
            continue
        fdate = _parse_date(filing_dates[i])
        acc = str(accession_nos[i]) if accession_nos[i] is not None else None
        pdoc = str(primary_docs[i]) if primary_docs[i] is not None else None
        if not acc:
            continue
        candidates.append(EdgarFiling(cik=cik10, accession_no=acc, filing_date=fdate, form=form, primary_doc=pdoc))

    if not candidates:
        return None

    def score(f: EdgarFiling) -> float:
        target = filing_date_hint or trade_date
        if not target or not f.filing_date:
            return 1e9
        return abs((f.filing_date - target).days)

    # pick best within max_days if we can
    best = sorted(candidates, key=score)[0]
    if (filing_date_hint or trade_date) and best.filing_date:
        if abs((best.filing_date - (filing_date_hint or trade_date)).days) <= max_days:
            return best
        # fallback: still return best but caller may downgrade confidence
        return best
    return best


def build_filing_index_url(cik10: str, accession_no: str) -> str:
    """
    EDGAR filing index HTML:
    https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodashes}/{accession}-index.html
    """
    cik_int = str(int(cik10))  # remove leading zeros for path segment
    acc_nodash = accession_no.replace("-", "")
    return f"{SEC_WWW_BASE}/Archives/edgar/data/{cik_int}/{acc_nodash}/{accession_no}-index.html"


def extract_sec_link_from_text(text: str) -> str | None:
    """
    Tries to find an SEC Archives link in arbitrary text.
    """
    if not text:
        return None
    # match both sec.gov/Archives and www.sec.gov/Archives
    m = re.search(r"(https?://(?:www\.)?sec\.gov/Archives/edgar/data/[^\s\"'>]+)", text, flags=re.IGNORECASE)
    if m:
        return m.group(1)
    return None
