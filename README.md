
# Insider Scan  
**Insider trading scanner (OpenInsider / SecForm4 / SEC EDGAR)**

Narzędzie informacyjne (Python 3.11+) do wyszukiwania i agregacji transakcji insider tradingu dla listy spółek w zadanym okresie.  
Dane są zbierane z agregatorów (**OpenInsider**, **SecForm4**) i **walidowane / uzupełniane linkami z SEC EDGAR**, który jest traktowany jako źródło referencyjne („source of truth”) dla filingów.

Projekt działa lokalnie, bez kluczy API, z zachowaniem limitów i zasad SEC.

---

## ✨ Funkcjonalności

- ✅ Wsparcie wielu źródeł:
  - **SecForm4** (CIK-based, stabilne)
  - **OpenInsider** (opcjonalne, best-effort)
- ✅ Centralna konfiguracja w **`config.yaml`**
- ✅ Możliwość **włączania/wyłączania źródeł**
- ✅ Automatyczne mapowanie **ticker → CIK → Form 4 (SEC EDGAR)**
- ✅ Deduplikacja transakcji (hash + fuzzy merge)
- ✅ Ocena jakości dopasowania (`confidence: HIGH / MED / LOW`)
- ✅ CLI + Dashboard **Streamlit**
- ✅ Cache HTTP + throttling + retry
- ✅ Brak zależności od płatnych API

---

## 📁 Struktura projektu

```

insider-scan/
├─ config.yaml               # konfiguracja runu (tickery, źródła)
├─ pyproject.toml
├─ README.md
├─ app.py                    # dashboard Streamlit
└─ src/
└─ insider_scan/
├─ **main**.py         # python -m insider_scan
├─ cli.py              # CLI pipeline
├─ config.py           # HTTP / UA / throttling
├─ settings.py         # loader YAML
├─ merge.py            # deduplikacja i scalanie
├─ models.py           # TransactionRecord
└─ sources/
├─ openinsider.py
├─ secform4.py
└─ sec_edgar.py

````

---

## ⚙️ Konfiguracja (`config.yaml`)

Plik `config.yaml` w katalogu projektu steruje zachowaniem aplikacji.

### Przykład:

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

### Znaczenie:

* `sources.openinsider` – włącz/wyłącz OpenInsider
* `sources.secform4` – włącz/wyłącz SecForm4
* `tickers` – domyślna lista tickerów
* `sec.*` – opcjonalne nadpisanie ustawień HTTP (zalecane)

> ⚠️ **SEC wymaga identyfikowalnego User-Agent** (email).
> Zalecane jest też ustawienie zmiennej środowiskowej:
>
> ```bash
> export SEC_USER_AGENT="Your Name your@email.com"
> ```

---

## 🧪 Instalacja

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -U pip
pip install -e .
```

---

## ▶️ Uruchomienie CLI

### Standardowo (tickery + źródła z `config.yaml`)

```bash
python -m insider_scan --start 2025-12-01
```

### Nadpisanie tickerów z CLI

```bash
python -m insider_scan --start 2025-12-01 --tickers AAPL TSLA
```

### Co robi CLI:

* zbiera dane z włączonych źródeł,
* uzupełnia linki do **SEC EDGAR**,
* deduplikuje transakcje,
* wypisuje `df.head(20)` + statystyki,
* zapisuje CSV do:

```
outputs/insider_YYYYMMDD_HHMMSS.csv
```

---

## 📊 Dashboard Streamlit

```bash
streamlit run app.py
```

### Funkcje dashboardu:

* filtry:

  * ticker
  * rola insidera
  * zakres dat
  * minimalna wartość transakcji
  * źródło danych
* tabela wynikowa z sortowaniem
* panel **Details**:

  * link do SEC EDGAR
  * link do źródła
* wykres liczby transakcji w czasie
* eksport CSV

Dashboard:

* używa ostatniego pliku CSV z `outputs/`,
* domyślne tickery i źródła pobiera z `config.yaml`,
* pozwala przełączać źródła checkboxami.

---

## 🔍 Confidence (`HIGH / MED / LOW`)

* **HIGH**

  * bezpośredni link do konkretnego filing Form 4 w SEC
  * zgodność tickera + daty
* **MED**

  * dopasowanie po dacie w submissions CIK
* **LOW**

  * brak jednoznacznego filing linku (np. tylko agregator)

---

## 🧠 Deduplikacja

Jedna transakcja = jeden rekord.

* `event_id = sha1(ticker | insider | trade_date | shares | price | type | source)`
* fuzzy merge:

  * `ticker`
  * `insider`
  * `trade_date ± 1 dzień`
  * `shares (zaokrąglone)`
* preferencja:

  1. rekord z linkiem SEC
  2. wyższy `confidence`

---

## 🛡️ Stabilność i compliance

* OpenInsider traktowany jako **best-effort**

  * możliwe blokady (`WinError 10061`, 403, 429)
  * pipeline **działa dalej** bez niego
* SecForm4:

  * używa **CIK**, nie tickerów
  * parsowanie przez `pandas.read_html`
* SEC EDGAR:

  * throttling
  * cache
  * zgodny User-Agent

---

## ⚠️ Ograniczenia

* Narzędzie **nie jest poradą inwestycyjną**
* Agregatory mogą mieć błędy lub opóźnienia
* SEC może tymczasowo ograniczyć dostęp przy zbyt agresywnym ruchu
* Struktura HTML źródeł może się zmienić (parsery defensywne)

---

## 🔧 Rozszerzanie projektu

Aby dodać nowe źródło:

1. Dodaj plik w `sources/`
2. Zwracaj `list[TransactionRecord]`
3. Podłącz w `cli.py`
4. Merge i dashboard zadziałają automatycznie

---

## ✅ Status projektu

* Core pipeline: **stabilny**
* SecForm4 + SEC EDGAR: **produkcyjnie używalne**
* OpenInsider: **opcjonalny / niestabilny**
* Konfiguracja YAML: **pełna kontrola runu**

---

**Autor:** Lukas C
**Cel:** monitoring i analiza aktywności insiderów (research / due diligence)

---