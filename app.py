### `app.py` (Streamlit)

from __future__ import annotations

import glob
import os
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from insider_scan.cli import run_pipeline
from insider_scan.config import OUTPUT_DIR
from insider_scan.settings import load_config



def _latest_output_csv() -> str | None:
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    files = sorted(glob.glob(os.path.join(OUTPUT_DIR, "insider_*.csv")))
    return files[-1] if files else None


def _load_df(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    # Normalize expected columns if missing
    for col in [
        "ticker", "company_name", "insider_name", "role_relation", "transaction_type",
        "trade_date", "filing_date", "shares", "price", "value_usd",
        "sec_link", "source", "source_url", "confidence", "event_id"
    ]:
        if col not in df.columns:
            df[col] = pd.NA
    # dates
    for c in ["trade_date", "filing_date"]:
        df[c] = pd.to_datetime(df[c], errors="coerce").dt.date
    # numerics
    for c in ["shares", "price", "value_usd"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


st.set_page_config(page_title="Insider Scan", layout="wide")
st.title("Insider Scan — OpenInsider + SecForm4 + SEC EDGAR")

with st.sidebar:
    st.header("Run / Load")
    default_start = date.today().replace(day=1)
    cfg = load_config("config.yaml")
    default_tickers = " ".join(cfg.tickers) if cfg.tickers else "AAPL TSLA PLTR"

    tickers_str = st.text_input("Tickers (space-separated)", value=default_tickers)

    enable_openinsider = st.checkbox("Enable OpenInsider", value=cfg.sources.openinsider)
    enable_secform4 = st.checkbox("Enable SecForm4", value=cfg.sources.secform4)
    start_date = st.date_input("Start date", value=default_start)
    run_btn = st.button("Run scan now")

    st.caption("Tip: Po uruchomieniu tworzy się CSV w outputs/. Dashboard może też wczytać ostatni plik.")

if run_btn:
    tickers = [t.strip().upper() for t in tickers_str.split() if t.strip()]
    df = run_pipeline(
        tickers=tickers,
        start_date=str(start_date),
        end_date=None,
        enable_openinsider=enable_openinsider,
        enable_secform4=enable_secform4,
    )

    st.success(f"Scan finished: {len(df)} rows")
    latest = _latest_output_csv()
    if latest:
        st.info(f"Saved: {latest}")

latest_csv = _latest_output_csv()
if not latest_csv:
    st.warning("Brak plików w outputs/. Uruchom scan w sidebar lub CLI.")
    st.stop()

df = _load_df(latest_csv)

# Sidebar filters based on detected values
with st.sidebar:
    st.header("Filters")

    detected_tickers = sorted([x for x in df["ticker"].dropna().unique().tolist() if str(x).strip()])
    selected_tickers = st.multiselect("Ticker", options=detected_tickers, default=detected_tickers)

    roles = sorted([x for x in df["role_relation"].dropna().unique().tolist() if str(x).strip()])
    selected_roles = st.multiselect("Role", options=roles, default=roles)

    sources = sorted([x for x in df["source"].dropna().unique().tolist() if str(x).strip()])
    selected_sources = st.multiselect("Source", options=sources, default=sources)

    min_value = float(df["value_usd"].dropna().min()) if df["value_usd"].notna().any() else 0.0
    max_value = float(df["value_usd"].dropna().max()) if df["value_usd"].notna().any() else 0.0
    if max_value < min_value:
        max_value = min_value

    min_value_usd = st.slider("Min value_usd", min_value=0.0, max_value=max_value if max_value > 0 else 1.0, value=0.0)

    date_min = df["trade_date"].dropna().min() if df["trade_date"].notna().any() else None
    date_max = df["trade_date"].dropna().max() if df["trade_date"].notna().any() else None
    if date_min and date_max:
        date_range = st.date_input("Trade date range", value=(date_min, date_max))
    else:
        date_range = None

# Apply filters
f = df.copy()
if selected_tickers:
    f = f[f["ticker"].isin(selected_tickers)]
if selected_roles:
    f = f[f["role_relation"].isin(selected_roles)]
if selected_sources:
    f = f[f["source"].isin(selected_sources)]
f = f[(f["value_usd"].fillna(0) >= float(min_value_usd))]

if date_range and isinstance(date_range, tuple) and len(date_range) == 2:
    d0, d1 = date_range
    f = f[(f["trade_date"].isna()) | ((f["trade_date"] >= d0) & (f["trade_date"] <= d1))]

# Main layout
colA, colB = st.columns([2, 1], gap="large")

with colA:
    st.subheader("Results")
    show_cols = [
        "ticker", "insider_name", "role_relation", "transaction_type",
        "trade_date", "filing_date", "shares", "price", "value_usd",
        "confidence", "source"
    ]
    show_cols = [c for c in show_cols if c in f.columns]
    f_sorted = f.sort_values(["trade_date", "value_usd"], ascending=[False, False], na_position="last")

    st.dataframe(f_sorted[show_cols], use_container_width=True, height=520)

    # Optional: simple time series count
    st.subheader("Transaction count over time")
    ts = f_sorted.dropna(subset=["trade_date"]).groupby("trade_date").size().reset_index(name="count")
    if len(ts) > 0:
        st.line_chart(ts.set_index("trade_date")["count"])
    else:
        st.caption("No dated transactions to chart.")

with colB:
    st.subheader("Details")
    # Use event_id selection (robust across Streamlit versions)
    event_ids = f_sorted["event_id"].dropna().astype(str).unique().tolist()
    if not event_ids:
        st.info("No rows to select.")
    else:
        selected_event = st.selectbox("Select event_id", options=event_ids, index=0)
        row = f_sorted[f_sorted["event_id"].astype(str) == str(selected_event)].head(1)
        if len(row) == 1:
            r = row.iloc[0].to_dict()
            st.write(f"**Ticker:** {r.get('ticker')}")
            st.write(f"**Insider:** {r.get('insider_name')}")
            st.write(f"**Role:** {r.get('role_relation')}")
            st.write(f"**Type:** {r.get('transaction_type')}")
            st.write(f"**Trade date:** {r.get('trade_date')}")
            st.write(f"**Filing date:** {r.get('filing_date')}")
            st.write(f"**Shares:** {r.get('shares')}")
            st.write(f"**Price:** {r.get('price')}")
            st.write(f"**Value USD:** {r.get('value_usd')}")
            st.write(f"**Confidence:** {r.get('confidence')}")
            st.write(f"**Source:** {r.get('source')}")

            sec_link = r.get("sec_link")
            src_url = r.get("source_url")
            if isinstance(sec_link, str) and sec_link.strip():
                st.link_button("Open SEC", sec_link)
            else:
                st.caption("No SEC link available.")
            if isinstance(src_url, str) and src_url.strip():
                st.link_button("Open source", src_url)

    st.subheader("Export")
    csv_bytes = f_sorted.to_csv(index=False).encode("utf-8")
    st.download_button("Download filtered CSV", data=csv_bytes, file_name="insider_filtered.csv", mime="text/csv")
