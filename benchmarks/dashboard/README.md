# Guardian AI Benchmark Dashboard

Lokalny, read-only dashboard dla katalogów utworzonych przez
`benchmark_cli.py compare`. Czyta wyłącznie pięć zweryfikowanych artefaktów:
`runs.csv`, `cases.csv`, `pairwise.csv`, `comparison.json` i `report.md`.
Nie wykonuje requestów do modeli, nie potrzebuje kluczy API i nie czyta
surowych treści e-maili, promptów ani reasoning.

## 1. Jednorazowe przygotowanie środowiska

W zwykłym Terminalu macOS:

```bash
cd /Users/kacperjozwik/Development/phishing-extension
conda create -n guardian-viz python=3.13 -y
conda activate guardian-viz
python -m pip install -r benchmarks/dashboard/requirements.txt
```

Nie instaluj zależności wizualizacyjnych do `backend/guardian/.venv`. Ten venv
pozostaje zamrożonym środowiskiem runnera benchmarków.

## 2. Uruchomienie dashboardu

```bash
cd /Users/kacperjozwik/Development/phishing-extension
conda activate guardian-viz
unset OPENAI_API_KEY GEMINI_API_KEY

python -m streamlit run benchmarks/dashboard/app.py \
  --server.address=127.0.0.1 \
  --browser.gatherUsageStats=false \
  -- \
  --comparison-dir benchmark-runs/comparisons/FULL_EIGHT_ARM_PILOT_030_001
```

Otwórz `http://127.0.0.1:8501`. Serwer działa tylko na loopbacku. Zatrzymaj go
przez `Ctrl+C`, a środowisko wyłącz poleceniem `conda deactivate`.

Jeżeli port 8501 jest zajęty, dodaj przed separatorem `--`:

```text
--server.port=8502
```

## 3. Zakładki

- `Overview`: tabela, F1, FPR i koszt–jakość;
- `Quality`: confusion matrix, akcje i metryki przeliczane z przypadków;
- `Cost & Latency`: observed cost, mediana/IQR i efektywność;
- `Direct vs CrewAI`: wyłącznie pary tego samego modelu, zawsze jako całe
  system bundles;
- `Case Explorer`: TP/FP/TN/FN/TECH dla wariantu i anonimowej próbki;
- `Technical & Report`: model ID, token cap, błędy, retry, hashe i raport.

Ikona aparatu na wykresie Plotly pobiera bieżący widok do PNG.

## 4. Statyczne PNG, SVG i Excel

W tym samym środowisku:

```bash
python benchmarks/dashboard/export_static.py \
  --comparison-dir benchmark-runs/comparisons/FULL_EIGHT_ARM_PILOT_030_001
```

Pierwsze uruchomienie tworzy:

```text
benchmark-runs/comparisons/FULL_EIGHT_ARM_PILOT_030_001/charts/
├── 01_f1.{png,svg}
├── 02_fpr.{png,svg}
├── 03_cost_per_message.{png,svg}
├── 04_latency_median.{png,svg}
├── 05_cost_quality_pareto.{png,svg}
├── 06_case_heatmap.{png,svg}
├── 07_direct_vs_crewai.{png,svg}
├── summary.xlsx
└── charts_manifest.json
```

Eksporter nie nadpisuje istniejącego niepustego katalogu. Dla kolejnej wersji
użyj nowej ścieżki:

```bash
python benchmarks/dashboard/export_static.py \
  --comparison-dir benchmark-runs/comparisons/FULL_EIGHT_ARM_PILOT_030_001 \
  --output-dir benchmark-runs/comparisons/FULL_EIGHT_ARM_PILOT_030_001/charts_v2
```

## 5. Zasady interpretacji

- `n=30`, dane syntetyczne/challenge-enriched, `PILOT_HOLD` i `INCONCLUSIVE`;
- nie uśredniaj F1 wielu modeli i nie twórz jednego `AI Score`;
- Gemini 3.7 Direct ma 29/30 sukcesów i jeden technical failure, mimo opisowego
  F1 równego 1;
- Gemini 3.7 CrewAI ma output cap 1000, a Direct 500;
- Gemini 3.1 Direct i CrewAI używają różnych protokołów API;
- binary correctness oraz golden action match są różnymi ocenami;
- `observed_cost_usd_per_message` to koszt porównawczy, a
  `ledger_reserved_or_observed_cost_usd` to konserwatywna ekspozycja budżetowa;
- confidence i trust score nie są wspólnie skalibrowane między modelami;
- McNemar w pilocie jest wyłącznie opisowy.

## 6. Integralność i prywatność

Loader przed pokazaniem danych sprawdza SHA-256 czterech artefaktów zapisane w
`comparison.json`, komplet wymaganych kolumn, liczbę próbek na wariant, pełność
par oraz spójność z metadanymi JSON. Symlinki i kolumny mogące zawierać surową
treść wiadomości są odrzucane.

Hashe potwierdzają wewnętrzną spójność lokalnego eksportu i wykrywają przypadkową
zmianę plików. Nie są podpisem cyfrowym: źródłem zaufania nadal jest zachowany,
audytowany katalog `compare` oraz jego provenance.

`benchmark-runs/` jest ignorowany przez Git. Kod dashboardu można commitować,
ale eksporty i wykresy trzeba zabezpieczyć osobno. Nie używaj `git add -f` dla
całego katalogu wyników.
