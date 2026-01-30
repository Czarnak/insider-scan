from __future__ import annotations

import hashlib
from datetime import timedelta, date

import pandas as pd

from insider_scan.models import TransactionRecord


def sha1_event_id(
    ticker: str,
    insider: str | None,
    trade_date: date | None,
    shares: float | None,
    price: float | None,
    txn_type: str,
    source: str,
) -> str:
    key = f"{ticker}|{insider or ''}|{trade_date.isoformat() if trade_date else ''}|{shares or ''}|{price or ''}|{txn_type}|{source}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def records_to_df(records: list[TransactionRecord]) -> pd.DataFrame:
    rows = [r.to_dict() for r in records]
    df = pd.DataFrame(rows)
    if df.empty:
        # create empty schema
        df = pd.DataFrame(columns=[
            "ticker","company_name","insider_name","role_relation","transaction_type",
            "trade_date","filing_date","shares","price","value_usd","sec_link",
            "source","source_url","confidence","event_id"
        ])
    # normalize types
    for c in ["trade_date", "filing_date"]:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce").dt.date
    for c in ["shares","price","value_usd"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _confidence_rank(x: str | None) -> int:
    # Higher is better
    m = {"HIGH": 3, "MED": 2, "LOW": 1}
    return m.get((x or "").upper().strip(), 0)


def merge_and_dedupe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Strategy:
    1) hard-dedupe by event_id exact
    2) fuzzy merge: ticker + insider + trade_date ±1 day + shares (rounded)
       - keep best confidence record and fill missing fields from others
    """
    if df.empty:
        return df

    # 1) exact event_id dedupe: keep highest confidence, then prefer having sec_link
    df = df.copy()
    df["_conf"] = df["confidence"].map(_confidence_rank)
    df["_has_sec"] = df["sec_link"].fillna("").astype(str).str.contains("sec.gov", case=False, na=False).astype(int)
    df = df.sort_values(["_conf", "_has_sec"], ascending=False)
    df = df.drop_duplicates(subset=["event_id"], keep="first")

    # 2) fuzzy key
    def norm_insider(x: str) -> str:
        return " ".join(str(x or "").strip().lower().split())

    df["_ins"] = df["insider_name"].fillna("").map(norm_insider)
    df["_td"] = pd.to_datetime(df["trade_date"], errors="coerce")
    df["_shares_r"] = df["shares"].round(0)

    # build groups by ticker+insider+shares_r
    groups = []
    for _, g in df.groupby(["ticker", "_ins", "_shares_r"], dropna=False):
        g = g.sort_values(["_td", "_conf"], ascending=[True, False]).copy()
        used = [False] * len(g)
        idxs = g.index.tolist()

        for i, idx_i in enumerate(idxs):
            if used[i]:
                continue
            row_i = g.loc[idx_i]
            bucket = [idx_i]
            used[i] = True
            td_i = row_i["_td"]
            for j in range(i + 1, len(idxs)):
                if used[j]:
                    continue
                idx_j = idxs[j]
                row_j = g.loc[idx_j]
                td_j = row_j["_td"]
                # If both dates exist and within +-1 day
                if pd.notna(td_i) and pd.notna(td_j):
                    if abs((td_j - td_i).days) <= 1:
                        bucket.append(idx_j)
                        used[j] = True
            groups.append(bucket)

    # combine within each fuzzy group
    keep_rows = []
    for bucket in groups:
        sub = df.loc[bucket].copy()
        # choose best base row
        sub = sub.sort_values(["_conf", "_has_sec"], ascending=False)
        base = sub.iloc[0].to_dict()

        # fill missing fields from other rows
        for _, r in sub.iloc[1:].iterrows():
            for col in [
                "company_name","role_relation","transaction_type","trade_date","filing_date",
                "shares","price","value_usd","sec_link","source_url"
            ]:
                if (base.get(col) is None) or (pd.isna(base.get(col))):
                    v = r.get(col)
                    if v is not None and not pd.isna(v):
                        base[col] = v

            # upgrade confidence if any has better
            if _confidence_rank(str(r.get("confidence"))) > _confidence_rank(str(base.get("confidence"))):
                base["confidence"] = r.get("confidence")

            # keep source as list? spec wants one; keep best's source but retain provenance in source_url already
        keep_rows.append(base)

    out = pd.DataFrame(keep_rows)

    # final sort + cleanup
    for c in ["trade_date", "filing_date"]:
        out[c] = pd.to_datetime(out[c], errors="coerce").dt.date
    for c in ["shares","price","value_usd"]:
        out[c] = pd.to_numeric(out[c], errors="coerce")

    out = out.drop(columns=[c for c in out.columns if c.startswith("_")], errors="ignore")
    out = out.sort_values(["trade_date", "value_usd"], ascending=[False, False], na_position="last").reset_index(drop=True)
    return out
