from __future__ import annotations

import argparse
import logging
import os
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from insider_scan.config import LOG_DIR, OUTPUT_DIR
from insider_scan.merge import records_to_df, merge_and_dedupe
from insider_scan.models import TransactionRecord
from insider_scan.sources.openinsider import fetch_openinsider
from insider_scan.sources.secform4 import fetch_secform4
from insider_scan.sources.sec_edgar import (
    ticker_to_cik,
    find_form4_filing_near,
    build_filing_index_url,
)
from insider_scan.settings import load_config
from insider_scan.config import apply_sec_overrides


# ---------- logging ----------
def setup_logger() -> logging.Logger:
    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
    log_path = Path(LOG_DIR) / f"run_{date.today().strftime('%Y%m%d')}.log"

    logger = logging.getLogger("insider_scan")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(fmt)

    logger.addHandler(sh)
    logger.addHandler(fh)
    return logger


# ---------- SEC link enrichment ----------
def enrich_sec_links(records: list[TransactionRecord], logger: logging.Logger) -> list[TransactionRecord]:
    """
    For each record:
    1) If sec_link already points to SEC (Archives/...), HIGH
    2) else: map ticker->CIK, find Form4 near trade_date/filing_date, build index url.
       - if match close: MED
       - else: LOW with company submissions page link
    """
    out: list[TransactionRecord] = []
    for r in records:
        sec_link = (r.sec_link or "").strip()
        if sec_link and "sec.gov/Archives/" in sec_link:
            r.confidence = "HIGH"
            out.append(r)
            continue

        cik10, title = ticker_to_cik(r.ticker)
        if r.company_name is None and title:
            r.company_name = title

        if not cik10:
            # Can't build SEC link reliably
            if not sec_link:
                r.sec_link = None
            r.confidence = "LOW"
            out.append(r)
            continue

        filing = find_form4_filing_near(cik10, r.trade_date, filing_date_hint=r.filing_date, max_days=10)
        if filing:
            idx_url = build_filing_index_url(cik10, filing.accession_no)
            r.sec_link = idx_url
            # Determine confidence: close match?
            target = r.filing_date or r.trade_date
            if target and filing.filing_date:
                delta = abs((filing.filing_date - target).days)
                r.confidence = "HIGH" if delta <= 2 else "MED"
            else:
                r.confidence = "MED"
            # prefer SEC filing date if missing
            if r.filing_date is None and filing.filing_date is not None:
                r.filing_date = filing.filing_date
            out.append(r)
            continue

        # Fallback: submissions landing (LOW)
        r.sec_link = f"https://data.sec.gov/submissions/CIK{cik10}.json"
        r.confidence = "LOW"
        out.append(r)

    return out


# ---------- pipeline ----------
def run_pipeline(tickers: list[str], start_date: str, end_date: str | None = None,
                 enable_openinsider: bool = True, enable_secform4: bool = True) -> pd.DataFrame:

    logger = setup_logger()
    logger.info("Starting insider scan")
    logger.info(f"Tickers: {tickers}")
    logger.info(f"Start date: {start_date} | End date: {end_date or date.today().isoformat()}")

    all_records: list[TransactionRecord] = []
    tickers_no_data: list[str] = []

    for t in tickers:
        t = t.upper().strip()
        if not t:
            continue

        per_ticker: list[TransactionRecord] = []
        logger.info(f"--- {t} ---")

        # OpenInsider
        if enable_openinsider:
            try:
                oi = fetch_openinsider(t, start_date=start_date)
                logger.info(f"OpenInsider: {len(oi)} rows")
                per_ticker.extend(oi)
            except Exception as e:
                msg = str(e)
                if "WinError 10061" in msg or "actively refused" in msg:
                    logger.warning(f"OpenInsider unavailable for {t} (connection refused). Skipping.")
                else:
                    logger.warning(f"OpenInsider failed for {t}: {e}")
        else:
            logger.info("OpenInsider: disabled by config")

        # SecForm4
        if enable_secform4:
            try:
                sf4 = fetch_secform4(t, start_date=start_date)
                logger.info(f"SecForm4: {len(sf4)} rows")
                per_ticker.extend(sf4)
            except Exception as e:
                logger.warning(f"SecForm4 failed for {t}: {e}")

            if not per_ticker:
                tickers_no_data.append(t)
                continue
        else:
            logger.info("OpenInsider: disabled by config")

        # SEC enrichment
        try:
            per_ticker = enrich_sec_links(per_ticker, logger=logger)
        except Exception as e:
            logger.warning(f"SEC enrichment failed for {t}: {e}")

        all_records.extend(per_ticker)

    df_raw = records_to_df(all_records)

    # Optional end_date filter (defaults today)
    end_dt = pd.to_datetime(end_date, errors="coerce").date() if end_date else date.today()
    start_dt = pd.to_datetime(start_date, errors="coerce").date()

    if not df_raw.empty:
        # filter by trade_date if present, else filing_date
        td = pd.to_datetime(df_raw["trade_date"], errors="coerce").dt.date
        fd = pd.to_datetime(df_raw["filing_date"], errors="coerce").dt.date
        mask = False
        mask = (td.notna() & (td >= start_dt) & (td <= end_dt)) | (td.isna() & fd.notna() & (fd >= start_dt) & (fd <= end_dt)) | (td.isna() & fd.isna())
        df_raw = df_raw[mask].copy()

    df = merge_and_dedupe(df_raw)

    # Save CSV
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path(OUTPUT_DIR) / f"insider_{ts}.csv"
    df.to_csv(out_path, index=False)

    # Console presentation
    print("\n=== df.head(20) ===")
    print(df.head(20).to_string(index=False))

    if len(df) > 0:
        dmin = pd.to_datetime(df["trade_date"], errors="coerce").min()
        dmax = pd.to_datetime(df["trade_date"], errors="coerce").max()
        print("\n=== Stats ===")
        print(f"Rows: {len(df)}")
        print(f"Trade date range: {dmin.date() if pd.notna(dmin) else None} .. {dmax.date() if pd.notna(dmax) else None}")
        print(f"Tickers in output: {sorted(df['ticker'].dropna().unique().tolist())}")
    else:
        print("\n=== Stats ===")
        print("Rows: 0")

    if tickers_no_data:
        print("\nTickers with no data:", tickers_no_data)

    print(f"\nSaved CSV: {out_path}")
    logger.info(f"Saved CSV: {out_path}")
    logger.info("Done")
    return df


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="insider_scan",
        description="Scan insider transactions via OpenInsider + SecForm4 and enrich SEC links.",
    )
    p.add_argument("--config", default="config.yaml", help="Path to YAML config (default: config.yaml)")
    p.add_argument("--tickers", nargs="*", help="Optional list of tickers; if omitted uses config.yaml tickers")
    p.add_argument("--start", required=True, dest="start_date", help="Start date YYYY-MM-DD")
    return p



def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    cfg = load_config(args.config)

    # Apply SEC overrides (optional)
    apply_sec_overrides(
        user_agent=cfg.sec.user_agent,
        throttle_s=cfg.sec.throttle_s,
        timeout_s=cfg.sec.timeout_s,
    )

    # tickers: CLI overrides YAML if provided
    if args.tickers and len(args.tickers) > 0:
        tickers = [t.upper().strip() for t in args.tickers if t.strip()]
    else:
        tickers = cfg.tickers

    if not tickers:
        print("ERROR: No tickers provided (CLI or config.yaml).")
        return 2

    _ = run_pipeline(
        tickers=tickers,
        start_date=args.start_date,
        end_date=None,
        enable_openinsider=cfg.sources.openinsider,
        enable_secform4=cfg.sources.secform4,
    )
    return 0

