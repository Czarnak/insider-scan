# Insider Scan (OpenInsider + SecForm4 + SEC EDGAR)

To narzędzie informacyjne do wykrywania transakcji insider tradingu dla listy tickerów w zadanym okresie.
Dane z agregatorów mogą być niekompletne/błędne — SEC EDGAR jest źródłem prawdy dla linków i podstawowej weryfikacji.

## Wymagania
- Python >= 3.11

## Instalacja
W katalogu projektu:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate

pip install -U pip
pip install -e .
