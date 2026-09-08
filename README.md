# Phishing Guard — rozszerzenie Chrome i Guardian AI

Rozszerzenie analizuje tekst i linki na stronach, wyróżnia lokalne sygnały
phishingu i umożliwia ocenę przez AI. Tryb Guardian automatycznie kieruje
wybrane wiadomości do backendu FastAPI z zespołem CrewAI i może zasłonić
wiadomość spełniającą progi wysokiego ryzyka.

**[Pełna dokumentacja techniczna i instrukcja obsługi](docs/DOKUMENTACJA_TECHNICZNA.md)**
obejmuje instalację, konfigurację kluczy, Chrome, tryby pracy, architekturę,
API, dane lokalne, benchmarki, testy i rozwiązywanie problemów.

## Szybki start — macOS/Linux

Wymagane: Git, Chrome, Node.js z npm, Python 3.13 oraz `uv`.
Polecenia zaczynaj w katalogu głównym sklonowanego repozytorium.
Instalację narzędzi i odpowiedniki dla Windows opisuje pełna dokumentacja.

### 1. Zbuduj rozszerzenie

```bash
npm ci
npm run build
```

### 2. Zainstaluj backend i CrewAI

```bash
uv sync --project backend/guardian --locked --python 3.13
cd backend
uv pip install --python guardian/.venv/bin/python -r requirements.txt
cd ..
```

Jeżeli nie masz jeszcze `backend/guardian/.env`, utwórz go na podstawie
[`backend/guardian/.env.example`](backend/guardian/.env.example).
Wpisz tam własny `OPENAI_API_KEY`. Ten plik pozostaje lokalny i jest
ignorowany przez Git. Szczegóły:
[klucze i modele](docs/DOKUMENTACJA_TECHNICZNA.md#4-klucze-api-i-modele).

Uruchom serwer:

```bash
cd backend
uv run --project guardian --no-sync --env-file guardian/.env \
  python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Dokumentacja API: <http://127.0.0.1:8000/docs>. Zostaw terminal otwarty.

### 3. Wgraj do Chrome

1. Otwórz `chrome://extensions` i włącz **Tryb dewelopera**.
2. Kliknij **Załaduj rozpakowane** / **Load unpacked**.
3. Wskaż katalog główny repozytorium, zawierający `manifest.json`.
4. Przypnij rozszerzenie i odśwież stronę, którą chcesz analizować.
5. Sprawdź [konfigurację identyfikatora rozszerzenia i CORS](docs/DOKUMENTACJA_TECHNICZNA.md#5-instalacja-w-chrome).

W popupie wybierz `Manual` i wpisz klucz w polu **Twój klucz OpenAI**, jeśli
chcesz używać przycisku `Analize`. Klucz w popupie jest niezależny od klucza
backendu. Tryb `Guardian` do automatycznej analizy używa klucza z backendu.

### 4. Obejrzyj gotowe benchmarki

W nowym terminalu, z katalogu głównego repozytorium, przygotuj osobne
środowisko wizualizacji:

```bash
uv venv .venv --python 3.13
uv pip install --python .venv/bin/python -r benchmarks/dashboard/requirements.txt
.venv/bin/python -m streamlit run benchmarks/dashboard/app.py \
  --server.address=127.0.0.1 --browser.gatherUsageStats=false
```

Otwórz <http://127.0.0.1:8501>. Repozytorium zawiera
[eksport ośmiu wariantów](benchmarks/results/README.md); do oglądania wyników
nie potrzeba kluczy API ani backendu.

Wykonywanie własnych pomiarów opisuje
[instrukcja benchmarków](docs/DOKUMENTACJA_TECHNICZNA.md#10-wlasne-benchmarki).
`benchmark_cli.py run` domyślnie wykonuje tylko dry-run. Płatne wywołania
wymagają osobnych flag i konfiguracji kampanii.

## Dokumentacja uzupełniająca

- [Backend i CrewAI](backend/guardian/README.md).
- [Dashboard Streamlit i eksport wykresów](benchmarks/dashboard/README.md).
- [Zestaw wyników dostępny po sklonowaniu](benchmarks/results/README.md).
- [Raport wyników ośmiu wariantów](benchmarks/BENCHMARK_RESULTS_REPORT.md).
- [Operacyjna instrukcja benchmarków](benchmarks/README.md).
- [Macierz modeli i historyczne kampanie](benchmarks/FULL_MODEL_MATRIX_RUNBOOK.md).
- [Specyfikacja badania](BENCHMARK_SPEC.md).
