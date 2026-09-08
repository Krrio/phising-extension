# GuardianClassic — backend CrewAI

Pakiet `guardian_classic` zawiera trzech agentów używanych przez lokalny
backend rozszerzenia Phishing Guard. Pełna instrukcja instalacji aplikacji,
kluczy, Chrome, obsługi i benchmarków znajduje się w
[Dokumentacji technicznej](../../docs/DOKUMENTACJA_TECHNICZNA.md).

## Instalacja

Z katalogu głównego repozytorium, dla macOS/Linux:

```bash
uv sync --project backend/guardian --locked --python 3.13
cd backend
uv pip install --python guardian/.venv/bin/python -r requirements.txt
```

Pakiet deklaruje Python `>=3.10,<3.14`. Instrukcja używa 3.13.
`pyproject.toml` przypina `crewai[google-genai,tools]==1.15.8` oraz
`google-genai==1.65.0`; zależności projektu odtwarza `uv.lock`.
Wymagania wrappera FastAPI są w `backend/requirements.txt` i trzeba je
zainstalować osobno z katalogu `backend/`.

Na Windows ścieżkę `guardian/.venv/bin/python` zastąp przez
`guardian/.venv/Scripts/python.exe`.

## Klucz i uruchomienie

Utwórz `backend/guardian/.env` według [szablonu](.env.example), jeżeli plik
jeszcze nie istnieje. Ustaw własny `OPENAI_API_KEY` oraz `MODEL=gpt-4o-mini`.
Nie nadpisuj istniejącego pliku z kluczem podczas kopiowania szablonu.

Z katalogu `backend/`:

```bash
uv run --project guardian --no-sync --env-file guardian/.env \
  python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

`--env-file` udostępnia także ustawienia telemetryczne przed importem CrewAI.
`--no-sync` zachowuje dodatkowe biblioteki wrappera. Opis API jest pod
<http://127.0.0.1:8000/docs>. Zatrzymanie: `Ctrl+C`.

Klucz w popupie Chrome jest osobną konfiguracją dla ręcznego `Analize`.
Backend nie pobiera go z przeglądarki. Benchmark CLI wymaga z kolei jawnego
`OPENAI_API_KEY` lub `GEMINI_API_KEY` w środowisku procesu.

## Przebieg Crew

`src/guardian_classic/crew.py` konfiguruje `Process.sequential`:

1. `analityk_domen` wykonuje `badanie_domen_task`, korzystając z
   `SuspiciousDomainTool` i `DomainAgeTool`.
2. `analityk_tresci` wykonuje `analiza_tresci_task`, oceniając treść, sygnały
   i opcjonalną politykę organizacji.
3. `orkiestrator` wykonuje `synteza_task` na podstawie wcześniejszych
   raportów i zwraca strukturalny `GuardianVerdict` przez Pydantic.

Role i zadania są w `src/guardian_classic/config/agents.yaml` oraz
`tasks.yaml`. FastAPI przygotowuje wejścia `domains_payload`,
`untrusted_payload`, `policy_payload` i `trusted_domains`.

`guardian_classic/main.py` nadal zawiera stare przykładowe wejścia szablonu.
`crewai run`, `run_crew`, `train` i `test` z tego entrypointu nie są aktualną
instrukcją uruchamiania rozszerzenia. Użyj FastAPI albo dedykowanego CLI
benchmarku opisanego w dokumentacji głównej.

## Cache domen

Wiek domeny jest sprawdzany przez RDAP, z fallbackiem WHOIS, i cache'owany
w `backend/guardian/.cache/registration_cache.db`. `GUARDIAN_CACHE_DB`
pozwala wskazać inną ścieżkę.

Cache zawiera domenę rejestrowalną, datę rejestracji, źródło, status i
metadane, bez kompletnych odpowiedzi RDAP/WHOIS. Ma limit 50 000 domen i
64 MiB, usuwa wygasłe wpisy i używa LRU. Konserwacja uruchamia się przy
starcie, po upływie do sześciu godzin lub po 1000 zapisów. Osobny proces
czyszczący nie jest potrzebny.

## Testy i benchmarki

Z katalogu głównego repozytorium:

```bash
backend/guardian/.venv/bin/python -m unittest discover -s backend/guardian/tests -v
backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py validate
```

Fabryka `benchmark_crew.py` jest osobna od produktowego Crew: korzysta z
zamrożonego evidence domenowego i kontrolowanych wywołań modeli. Nazwa
`CrewAI Offline` nie oznacza lokalnego modelu ani bezpłatnego live runu.
Pełna procedura tworzenia kampanii, dry-runu, pomiaru, scoringu i porównania:
[własne benchmarki](../../docs/DOKUMENTACJA_TECHNICZNA.md#10-wlasne-benchmarki).
