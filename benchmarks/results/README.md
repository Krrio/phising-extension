# Wyniki dołączone do repozytorium

`FULL_EIGHT_ARM_PILOT_030_001/` zawiera gotowe wyniki ośmiu wariantów
Direct/CrewAI na 30 syntetycznych próbkach: 8 wierszy wariantów, 240 wyników
przypadków i 28 porównań par. Dashboard domyślnie czyta ten katalog, więc po
sklonowaniu repozytorium wystarczy zainstalować zależności i uruchomić
Streamlit zgodnie z [instrukcją](../dashboard/README.md).

Do oglądania wyników nie są potrzebne klucze API, lokalne runy ani ponowne
wywołania modeli. Jest to zapis zakończonego pilota, o statusie
`PILOT_HOLD` / `INCONCLUSIVE`, a nie nowy pomiar.

## Zawartość i pochodzenie

- `runs.csv`: metryki, koszt i czas każdego wariantu;
- `cases.csv`: anonimowe identyfikatory próbek, etykiety i wyniki;
- `pairwise.csv`: porównania wariantów;
- `comparison.json`: metadane, hashe eksportu i artefaktów źródłowych;
- `report.md`: opis wyników i ograniczeń porównania.

Źródłem jest lokalny eksport
`benchmark-runs/comparisons/FULL_EIGHT_ARM_PILOT_030_001/` wygenerowany
2026-09-05. Pliki CSV i `report.md` skopiowano bez zmian. W `comparison.json`
zastąpiono ścieżki absolutne w `source_artifacts.*.run_dir` i
`trusted_labels.path` ścieżkami względem katalogu głównego repozytorium.
Wyniki, hashe i identyfikatory runów zachowano. Ścieżki źródłowe dokumentują
pochodzenie danych; dashboard nie otwiera wskazanych przez nie plików.

Pakiet nie zawiera treści wiadomości, promptów, reasoning, kluczy API ani
surowych odpowiedzi providerów. `benchmark-runs/` nadal służy do lokalnych
artefaktów runnera i jest ignorowany przez Git.

## Weryfikacja i kolejne wersje

Z katalogu głównego repozytorium:

```bash
python -m unittest discover -s benchmarks/tests -p test_dashboard.py -v
```

Test przenosi pięć plików do katalogu tymczasowego i sprawdza ich kompletność,
SHA-256 oraz zgodność danych, bez dostępu do lokalnych runów. Zależności
wykresów są opcjonalne dla walidacji danych.

`.gitattributes` wyłącza konwersję końców linii dla artefaktów, aby ich hashe
pozostały zgodne również po sklonowaniu repozytorium na Windows.

Kolejne wyniki dodawaj jako osobny katalog po sprawdzeniu zawartości eksportu.
Zachowaj istniejące snapshoty. Wykresy PNG/SVG i XLSX można odtworzyć lokalnie
poleceniem `export_static.py` z instrukcji dashboardu.
