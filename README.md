# Insider Scan  
**Insider trading scanner (OpenInsider / SecForm4 / SEC EDGAR)**

An informational tool (Python 3.11+) for discovering and aggregating insider trading transactions for a list of companies over a specified time range.  
Data is collected from aggregators (**OpenInsider**, **SecForm4**) and **validated / enriched with links from SEC EDGAR**, which is treated as the reference (“source of truth”) for filings.

The project runs locally, requires no API keys, and respects SEC rate limits and access rules.

---

## ✨ Features

- ✅ Multiple data sources:
  - **SecForm4** (CIK-based, stable)
  - **OpenInsider** (optional, best-effort)
- ✅ Centralized configuration via **`config.yaml`**
- ✅ Ability to **enable/disable individual sources**
- ✅ Automatic **ticker → CIK → Form 4 (SEC EDGAR)** mapping
- ✅ Transaction deduplication (hash + fuzzy merge)
- ✅ Match quality assessment (`confidence: HIGH / MED / LOW`)
- ✅ CLI + **Streamlit** dashboard
- ✅ HTTP cache + throttling + retries
- ✅ No dependency on paid APIs

---

## 📁 Project Structure

```

insider-scan/
├─ config.yaml               # run configuration (tickers, sources)
├─ pyproject.toml
├─ README.md
├─ app.py                    # Streamlit dashboard
└─ src/
└─ insider_scan/
├─ **main**.py         # python -m insider_scan
├─ cli.py              # CLI pipeline
├─ config.py           # HTTP / UA / throttling
├─ settings.py         # YAML loader
├─ merge.py            # deduplication and merging
├─ models.py           # TransactionRecord
└─ sources/
├─ openinsider.py
├─ secform4.py
└─ sec_edgar.py

````

---

## ⚙️ Configuration (`config.yaml`)

The `config.yaml` file in the project root controls the application behavior.

### Example:

```yaml
sources:
  openinsider: false
  secform4: true

tickers:
  - AAPL
  - TSLA
  - PLTR
  - AVXL

sec:
  user_agent: "InsiderScan/0.1 (contact: you@example.com)"
  throttle_s: 0.35
  timeout_s: 20
````

### Meaning:

* `sources.openinsider` – enable/disable OpenInsider
* `sources.secform4` – enable/disable SecForm4
* `tickers` – default list of tickers
* `sec.*` – optional overrides for HTTP settings (recommended)

> ⚠️ **SEC requires an identifiable User-Agent** (with an email address).
> It is also recommended to set the environment variable:
>
> ```bash
> export SEC_USER_AGENT="Your Name your@email.com"
> ```

---

## 🧪 Installation

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -U pip
pip install -e .
```

---

## ▶️ Running the CLI

### Default (tickers and sources from `config.yaml`)

```bash
python -m insider_scan --start 2025-12-01
```

### Override tickers from the CLI

```bash
python -m insider_scan --start 2025-12-01 --tickers AAPL TSLA
```

### What the CLI does:

* collects data from enabled sources,
* enriches records with **SEC EDGAR** links,
* deduplicates transactions,
* prints `df.head(20)` + basic statistics,
* saves a CSV file to:

```
outputs/insider_YYYYMMDD_HHMMSS.csv
```

---

## 📊 Streamlit Dashboard

```bash
streamlit run app.py
```

### Dashboard features:

* filters:

  * ticker
  * insider role
  * date range
  * minimum transaction value
  * data source
* sortable results table
* **Details** panel:

  * SEC EDGAR link
  * source link
* transaction count over time chart
* CSV export

The dashboard:

* loads the most recent CSV from `outputs/`,
* uses default tickers and source toggles from `config.yaml`,
* allows switching sources via checkboxes.

---

## 🔍 Confidence (`HIGH / MED / LOW`)

* **HIGH**

  * direct link to a specific Form 4 filing in SEC EDGAR
  * ticker and date alignment
* **MED**

  * matched by date within the company CIK submissions
* **LOW**

  * no unambiguous filing link (aggregator-only data)

---

## 🧠 Deduplication

One transaction = one record.

* `event_id = sha1(ticker | insider | trade_date | shares | price | type | source)`
* fuzzy merge on:

  * `ticker`
  * `insider`
  * `trade_date ± 1 day`
  * `shares (rounded)`
* preference order:

  1. record with SEC link
  2. higher `confidence`

---

## 🛡️ Stability and Compliance

* OpenInsider is treated as **best-effort**

  * connection refusals, 403, or 429 responses are possible
  * the pipeline **continues without it**
* SecForm4:

  * uses **CIK-based URLs**, not tickers
  * table parsing via `pandas.read_html`
* SEC EDGAR:

  * throttling
  * caching
  * compliant User-Agent usage

---

## ⚠️ Limitations

* This tool **is not investment advice**
* Aggregators may contain errors or delays
* SEC may temporarily restrict access under heavy load
* Source HTML structures may change over time (parsers are defensive)
* Not all transaction types present themselves properly

---

## 🔧 Extending the Project

To add a new source:

1. Add a new file under `sources/`
2. Return `list[TransactionRecord]`
3. Wire it into `cli.py`
4. Merging and the dashboard will work automatically

---

## ✅ Project Status

* Core pipeline: **stable**
* SecForm4 + SEC EDGAR: **production-ready**
* OpenInsider: **optional / unstable**

---

**Author:** LCZ
**Purpose:** monitoring and analysis of insider activity (research / due diligence)

---
