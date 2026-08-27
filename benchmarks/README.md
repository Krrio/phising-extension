# Benchmark phishing — instrukcja operacyjna

## Werdykt wobec specyfikacji z PDF

Specyfikacja jest dobra jako przewodnik implementacyjny i zgadza się z normatywnym `BENCHMARK_SPEC.md`. Nie należy jednak zaczynać od 200 wiadomości ani traktować pięciu przykładów jako pomiaru jakości. Smoke `n=5` sprawdza przewód, a zamrożony pilot `n=30` daje pierwszy opisowy pomiar jakości w budżecie. Oba etapy mają status `ENGINEERING_PILOT` i żaden nie jest jeszcze rankingiem modeli.

Przed implementacją wprowadzono pięć korekt:

1. Runner nie dostaje labeli ani ścieżki do scoring bundle. Syntetyczne labele smoke są w osobnym katalogu i są otwierane dopiero przez komendę `score`. W prawdziwym blind confirmation scoring bundle musi być poza mountem/użytkownikiem runnera, nie tylko w innym folderze repo.
2. Każdy timeout, 429, 5xx, refusal i invalid output tworzy terminalny `ResultRecord` i pozostaje w mianowniku. Każdy outbound attempt jest liczony przed wysłaniem.
3. Pierwszy test zachowuje obecny produktowy endpoint Chat Completions i prompt. Zmiana na Responses API byłaby osobnym eksperymentem, bo jednoczesna zmiana modelu/endpointu/kontraktu zaciera przyczynę różnicy.
4. Alias `gpt-4o-mini` zastąpiono w kampanii przypiętym snapshotem `gpt-4o-mini-2024-07-18`. OpenAI wymienia go jako snapshot wspierający Structured Outputs; zamrożona cena to 0,15 USD/M input tokens i 0,60 USD/M output tokens.
5. Produkcyjny Crew nie jest używany w benchmarku, bo dziedziczy inne ustawienia i korzysta z live RDAP/WHOIS. Powstał osobny, utwardzony profil `CrewAI Offline`: ten sam snapshot modelu i dane co Direct, trzy jawne wywołania na próbkę, zero retry, zamrożony evidence domenowy, wyłączona telemetria oraz twardy limit wywołań. Przed pilotem `n=30` musi przejść własny smoke `n=5`.

## Co jest gotowe

Gotowe są dwa tory, każdy ze smoke `n=5` i pilotem jakości `n=30`: OpenAI Direct oraz CrewAI Offline. Direct został już wykonany; CrewAI jest gotowy do pierwszego live smoke.

```text
5 syntetycznych runner inputs
        ↓
walidacja label/PII/egress/budżetu
        ↓
OpenAI Direct, strict JSON, R=1, concurrency=1
        ↓
attempts.jsonl + results.jsonl + budget ledger + manifest
        ↓
oddzielne labele
        ↓
scored_results.jsonl + metrics.json/csv + report.md

pilot 30: 15 malicious + 15 benign
        ↓
confusion matrix + precision/recall/F1/FPR + Wilson 95%
        ↓
PILOT_READY_FOR_SELECTION / PILOT_HOLD / SECURITY_FAIL / INVALID

CrewAI Offline: ten sam model i runner dataset
        ↓
osobny prompt bundle + 3 role sekwencyjne × 1 call, bez retry i bez live RDAP/WHOIS
        ↓
calls.jsonl + 2 frozen tool events na próbkę
        ↓
system_bundle_delta względem Direct, nie czysta delta frameworka
```

Najważniejsze pliki:

| Plik | Rola |
|---|---|
| `benchmark_cli.py` | komendy validate, dry-run, live run i score |
| `campaigns/BUDGET_30H_OPENAI_SMOKE_001/runtime_config.json` | zamrożony model, endpoint, retry, timeout, budżet i ceny |
| `campaigns/BUDGET_30H_OPENAI_SMOKE_001/direct_system_prompt_v1.txt` | kopia obecnego promptu Direct; test wykrywa drift względem produktu |
| `campaigns/BUDGET_30H_OPENAI_SMOKE_001/response_schema.json` | strict JSON Schema zgodne z bieżącym Direct flow |
| `campaigns/BUDGET_30H_OPENAI_SMOKE_001/decision_policy.json` | mapowanie verdict/trust/confidence na allow/warn/hide |
| `fixtures/openai_smoke_v1/runner_input.jsonl` | pięć syntetycznych wiadomości bez labeli |
| `secure_scoring/openai_smoke_v1/labels.jsonl` | oddzielny golden bundle, otwierany wyłącznie przez scorer |
| `secure_scoring/openai_smoke_v1/scoring_manifest.json` | zamrożone hashe datasetu i jawnych labeli smoke |
| `datasets/openai_pilot_pool_v1/source.md` | kanoniczna pula 39 syntetycznych przypadków; adnotacje nie trafiają do runnera |
| `tools/import_openai_pilot_pool.ts` | deterministyczny importer i wyliczanie sygnałów aktualnym kodem produktu |
| `fixtures/openai_pilot_030_v1/runner_input.jsonl` | 30 runner inputs bez labeli, 15 malicious + 15 benign |
| `fixtures/openai_pilot_030_v1/dataset_manifest.json` | publiczny, label-free manifest pochodzenia i transformacji |
| `secure_scoring/openai_pilot_030_v1/` | labele, metadane, selekcja, provenance i zamrożony scoring manifest |
| `campaigns/BUDGET_30H_OPENAI_PILOT_030_001/` | właściwa kampania pilota z limitem 60 attempts / 0,25 USD / 2 h |
| `campaigns/BUDGET_30H_CREWAI_OFFLINE_SMOKE_001/` | utwardzony profil Crew, prompt, frozen evidence i kampania smoke 5 × 3 calls |
| `campaigns/BUDGET_30H_CREWAI_OFFLINE_PILOT_030_001/` | ten sam zestaw 30 co Direct, limit 90 calls / 0,25 USD / 2 h |
| `backend/guardian/src/guardian_classic/benchmark_crew.py` | benchmarkowa fabryka trzech agentów; nie zmienia produkcyjnego Crew |
| `phishing_bench/crewai_offline.py` | izolacja procesu, egress guard, call budget i artefakty CrewAI |
| `phishing_bench/` | transport, kontrakty, ledger, runner i scorer |
| `tests/test_benchmark.py` | deterministyczne testy bez API i bez kosztu |
| `tests/test_crewai_offline.py` | pełny kickoff CrewAI z zamockowaną wyłącznie granicą providera oraz testy telemetrii, egressu i budżetu |

Tor Direct używa wyłącznie biblioteki standardowej Pythona i nie ma niewidocznych retry SDK. Tor CrewAI działa w przypiętym środowisku backendu (`crewai==1.15.8`), ale wymusza `max_retries=0`, trzy calls na workflow, dokładny Chat Completions endpoint i `store=false`. Oba tory blokują egress poza `api.openai.com`, ignorują proxy, nie pobierają URL-i z wiadomości i odmawiają live runu przy aktywnym `SSLKEYLOGFILE`. CrewAI ma dodatkowo wyłączone anonimowe OTLP telemetry, tracking oraz first-run tracing przed pierwszym importem frameworka.

## Jak wykonać test

Wszystkie polecenia uruchamiaj z głównego katalogu repozytorium. Runner wymaga Pythona 3.10+, a testy driftu używają także Node.js dostępnego już w projekcie rozszerzenia.

### 1. Testy lokalne — 0 USD

```bash
python3 -m unittest discover -s benchmarks/tests -v

# Pełny zestaw razem z testami runtime CrewAI:
env -u OPENAI_API_KEY PYTHONWARNINGS=ignore \
  backend/guardian/.venv/bin/python -m unittest discover -s benchmarks/tests -v
```

Testy sprawdzają między innymi:

- zgodność zamrożonego promptu z `src/background.ts`;
- strict outgoing request: model snapshot, `store=false`, brak tools i brak labeli;
- blokadę egressu do innego hosta;
- fail-fast przy pustym TLS trust store i nieretryowalny błąd certyfikatu;
- usuwanie sekretów z artefaktów;
- action mapping;
- retry, limiter attempts i jeden wynik na każdą próbkę;
- prywatne uprawnienia `0700/0600`;
- pełne score/report na mockowanym providerze;
- deterministyczny import 39 przypadków do zamrożonego podzbioru 30;
- brak label leakage i niewidocznego `href` w treści widzianej przez model;
- dokładny kontrakt 15/15, limity pilota i idempotentne hashe;
- confusion matrix, metryki opisowe, Wilson 95% oraz błędy techniczne pozostające w mianowniku.
- pełny sekwencyjny kickoff CrewAI przy zamockowanej wyłącznie granicy providera: dokładnie trzy role i trzy calls;
- dokładny model snapshot, `store=false`, strict JSON na orkiestratorze, brak tools w agentach i brak retry;
- wyłączenie anonimowej telemetrii/tracingu CrewAI oraz blokadę każdego hosta poza OpenAI.

Sprawdzenie, czy wygenerowane dane nadal są dokładnie zgodne ze źródłem i kodem produktu:

```bash
./node_modules/.bin/vite-node benchmarks/tools/import_openai_pilot_pool.ts --check
```

### 2. Readiness i dry-run — 0 USD

```bash
python3 benchmarks/benchmark_cli.py validate
python3 benchmarks/benchmark_cli.py run
```

Obie komendy budują i walidują faktyczny payload, ale niczego nie wysyłają. Oczekiwany status to `READY_FOR_MANUAL_LIVE_CONFIRMATION`. Raport pokazuje hashe requestów i konserwatywną rezerwację kosztu, nie pokazuje treści wiadomości ani klucza.

Readiness sprawdza również lokalny trust store TLS. Jeżeli Python zgłasza brak zaufanych CA, nie wyłączaj weryfikacji certyfikatów. Dla instalatora Python.org na macOS można naprawić konfigurację jednorazowo poleceniem:

```bash
"/Applications/Python 3.12/Install Certificates.command"
```

Alternatywa tylko dla bieżącej sesji, gdy zainstalowany jest pakiet `certifi`:

```bash
export SSL_CERT_FILE="$(python3 -m certifi)"
python3 benchmarks/benchmark_cli.py validate
```

Poprawny output zawiera `local_tls_preflight`, `CERT_REQUIRED`, `hostname_verification: true` oraz dodatnią liczbę CA. Błąd certyfikatu jest nieretryowalny, więc runner nie zużywa limitu na identyczne próby środowiskowe.

Do jednorazowego engineering smoke można przejść od razu. Dla odtwarzalnego runu porównawczego najpierw zatwierdź i commituj harness/kampanię; manifest zapisuje commit, flagę dirty, hashe kodu i wszystkich assetów. Scorer dodatkowo odrzuca zmianę zamkniętych `results`, `attempts` lub ledgera oraz niespójność między nimi.

Aktualna kampania ma trzy lokalne bezpieczniki:

- maksymalnie 10 outbound attempts, czyli 5 próbek i najwyżej jeden retry na próbkę;
- maksymalnie 15 minut;
- `max_cost_usd = 0.05`.

Przy obecnych payloadach konserwatywna rezerwacja dla pełnych 10 attempts wynosi około 0,016 USD. Jest celowo wyższa od spodziewanego rachunku, bo jako proxy liczby input tokens liczy każdy bajt UTF-8 jak osobny token i rezerwuje pełne 500 output tokens. Lokalny ledger nie zastępuje limitu projektu po stronie providera, szczególnie gdy timeout nie zwróci usage.

### 3. Przygotowanie klucza

Użyj osobnego, project-scoped klucza przeznaczonego tylko do benchmarku. Nie wpisuj go do JSON, `.env` w repo, argumentów CLI ani notebooka. W interaktywnym shellu można wczytać go bez wyświetlania:

```bash
read -s OPENAI_API_KEY
export OPENAI_API_KEY
```

Przed live run sprawdź także bieżący budżet/usage projektu na koncie OpenAI. Pięć fixture'ów jest w pełni syntetycznych i używa wyłącznie zarezerwowanych domen `.example` i `.invalid`.

`store=false` wyłącza zapisywanie odpowiedzi do późniejszego pobierania, ale nie jest równoznaczne z Zero Data Retention. Oficjalna dokumentacja OpenAI opisuje osobno logi abuse monitoring i kontrolę retencji. Dlatego ten etap nie wysyła realnych wiadomości ani PII.

### 4. Live smoke — maksymalnie 5 wiadomości

Live calls wymagają dwóch niezależnych potwierdzeń: flagi `--live` i dokładnego campaign ID.

```bash
python3 benchmarks/benchmark_cli.py run \
  --live \
  --confirm-campaign BUDGET_30H_OPENAI_SMOKE_001
```

Komenda wypisze absolutną ścieżkę nowego katalogu runu. Nie uruchamiaj jej ponownie tylko dlatego, że model pomylił klasyfikację; drugi run to osobne powtórzenie i osobny koszt.

Domyślnie reasoning nie jest zapisywany — tylko jego hash i długość. Ponieważ ten smoke jest syntetyczny, do ręcznej inspekcji można jawnie włączyć znormalizowane reasoning:

```bash
python3 benchmarks/benchmark_cli.py run \
  --live \
  --store-reasoning \
  --confirm-campaign BUDGET_30H_OPENAI_SMOKE_001
```

Nawet w tym trybie raw request i raw response nie są zapisywane, a raport nigdy nie renderuje reasoning jako Markdown/HTML. Przy krytycznym security event reasoning nie jest utrwalany.

### 5. Scoring i raport — 0 dodatkowych calls

Użyj ścieżki wypisanej przez live run:

```bash
python3 benchmarks/benchmark_cli.py score \
  --run-dir /absolutna/sciezka/do/runu \
  --labels benchmarks/secure_scoring/openai_smoke_v1/labels.jsonl
```

Scorer nie wysyła żadnych danych do providera. Dla przyszłego blind confirmation ścieżka `--labels` ma prowadzić do niedostępnego wcześniej secure root poza repo/mountem runnera.

### 6. Właściwy pilot jakości — 30 wiadomości

Pilot jest zamrożony przed pierwszym requestem: 15 malicious i 15 benign, tylko kanał e-mail. Pominięto SMS, QR i niewidoczny załącznik, ponieważ bieżący Direct flow analizuje tekst e-maila i nie dostarcza modelowi równoważnego obrazu ani zawartości pliku. Wszystkie domeny są zarezerwowane, a sygnały są wyliczane przez `src/phrases.ts` i `src/linkRisk.ts`. Ręczne `ANNOTATOR_SIGNALS`, etykiety, scenariusze i uzasadnienia nigdy nie wchodzą do payloadu.

Najpierw readiness i dry-run za 0 USD:

```bash
PILOT_CONFIG="benchmarks/campaigns/BUDGET_30H_OPENAI_PILOT_030_001/runtime_config.json"

python3 benchmarks/benchmark_cli.py validate --campaign "$PILOT_CONFIG"
python3 benchmarks/benchmark_cli.py run --campaign "$PILOT_CONFIG"
```

Oczekiwane: `record_count=30`, profil `openai_direct_quality_pilot_v1`, limit 60 attempts, 0,25 USD i 7200 sekund. Readiness rezerwuje konserwatywnie wszystkie możliwe próby oraz dodatkowe 20% marginesu. Przy zamrożonych payloadach rezerwacja z marginesem wynosi około 0,1124 USD; jest to bezpiecznik, nie prognoza rachunku. Smoke wskazuje, że typowy rzeczywisty koszt powinien być dużo niższy, ale rozstrzygający jest dashboard providera.

Preregistered gate do kolejnego etapu wymaga między innymi: 30/30 terminalnych rekordów, zera błędów technicznych i krytycznych zdarzeń, najwyżej 2 malicious z akcją `allow`, najwyżej 3 benign z akcją `warn` lub `hide`, zera benign `hide` oraz zera security-probe `allow`. Są to bramki pilota, nie deklarowane progi produkcyjne.

Po przejściu testów i dry-run zamroź stan w commicie oraz upewnij się, że worktree jest czysty. Ustaw project-scoped klucz jak w kroku 3 i wykonaj dokładnie jeden live run:

```bash
python3 benchmarks/benchmark_cli.py run \
  --campaign "$PILOT_CONFIG" \
  --live \
  --confirm-campaign BUDGET_30H_OPENAI_PILOT_030_001
```

Zapisz wypisaną ścieżkę jako `RUN_DIR`, usuń klucz z powłoki i uruchom scoring bez kolejnych requestów:

```bash
unset OPENAI_API_KEY

RUN_DIR="/absolutna/sciezka/wypisana/przez/live-run"
python3 benchmarks/benchmark_cli.py score \
  --run-dir "$RUN_DIR" \
  --labels benchmarks/secure_scoring/openai_pilot_030_v1/labels.jsonl

cat "$RUN_DIR/scoring/report.md"
```

Nie uruchamiaj ponownie pilota w reakcji na słaby wynik. Najpierw analizuje się `report.md`, `metrics.json` i per-case `scored_results.jsonl`; każda świadoma zmiana promptu, danych lub polityki wymaga nowego campaign ID.

## CrewAI Offline — bieżący następny krok

To nie jest uruchomienie produkcyjnego `GuardianClassic`. Benchmark buduje świeży, pozbawiony pamięci Crew dla każdej próbki: analityk domen, analityk treści i orkiestrator. Każdy wykonuje dokładnie jeden call do `gpt-4o-mini-2024-07-18`. Domena jest oceniana na podstawie lokalnego, wersjonowanego fixture; live RDAP/WHOIS i narzędzia sieciowe są wyłączone.

Porównanie z Direct nazywa się `system_bundle_delta`: model snapshot, runner dataset, response schema i decision policy są takie same. Prompt nie jest taki sam — Crew używa osobnych promptów ról/zadań, trzyetapowej orkiestracji i dodatkowego frozen evidence. Wyniku nie wolno opisywać jako czystego wpływu frameworka ani rankingu modeli.

### 1. Testy, readiness i dry-run — 0 USD

Uruchom z katalogu głównego repozytorium:

```bash
CREW_SMOKE_CONFIG="benchmarks/campaigns/BUDGET_30H_CREWAI_OFFLINE_SMOKE_001/runtime_config.json"

env -u OPENAI_API_KEY PYTHONWARNINGS=ignore \
  backend/guardian/.venv/bin/python -m unittest discover -s benchmarks/tests -v

export SSL_CERT_FILE="$(backend/guardian/.venv/bin/python -m certifi)"

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py validate \
  --campaign "$CREW_SMOKE_CONFIG"

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py run \
  --campaign "$CREW_SMOKE_CONFIG"
```

Oczekiwane readiness: `READY_FOR_MANUAL_LIVE_CONFIRMATION`, `record_count=5`, `provider_calls_made=0`, trzy role z `api=completions`, `store=false`, `provider_max_retries=0`, `task_output_storage=ephemeral_in_memory`, wyłączony exporter telemetrii i pusta lista proxy. Maksymalnie może powstać 15 calls. Aktualna konserwatywna rezerwacja to około 0,0222 USD, a z marginesem około 0,0267 USD; twardy cap smoke wynosi 0,05 USD.

Przed live runem zatwierdź i commituj zamrożone pliki benchmarku, aby manifest nie miał flagi dirty. Nie commituj katalogu `benchmark-runs/`, `.env` ani klucza.

### 2. Jeden płatny smoke — 5 wiadomości, maksymalnie 15 calls

```bash
read -s OPENAI_API_KEY
export OPENAI_API_KEY

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py run \
  --campaign "$CREW_SMOKE_CONFIG" \
  --live \
  --confirm-campaign BUDGET_30H_CREWAI_OFFLINE_SMOKE_001

unset OPENAI_API_KEY
```

Live run wypisze absolutny `RUN_DIR`. Nie powtarzaj go automatycznie po błędzie — najpierw wykonaj scoring i audyt calls:

```bash
RUN_DIR="/absolutna/sciezka/wypisana/przez/live-run"

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py score \
  --run-dir "$RUN_DIR" \
  --labels benchmarks/secure_scoring/openai_smoke_v1/labels.jsonl

cat "$RUN_DIR/scoring/report.md"
```

Smoke może dopuścić pilot tylko wtedy, gdy ma 5 terminalnych sukcesów, 15 calls w kolejności `domain_analyst → content_analyst → orchestrator`, poprawny strict output, usage dla każdego calla, dwa lokalne tool events na próbkę, zero telemetry/nieautoryzowanego egressu i brak przekroczenia budżetu. Golden mismatch wymaga przeglądu, ale nie jest automatycznie błędem przewodu.

### 3. Pilot CrewAI `n=30` — dopiero po przeglądzie smoke

Pilot używa dokładnie tych samych 30 runner inputs i labeli co ukończony pilot Direct. Nie uruchamiaj go, dopóki raport smoke i `calls.jsonl` nie potwierdzą zachowania prawdziwego frameworka.

```bash
CREW_PILOT_CONFIG="benchmarks/campaigns/BUDGET_30H_CREWAI_OFFLINE_PILOT_030_001/runtime_config.json"

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py validate \
  --campaign "$CREW_PILOT_CONFIG"

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py run \
  --campaign "$CREW_PILOT_CONFIG"
```

Po osobnym ręcznym potwierdzeniu limitu projektu i campaign ID właściwy live pilot ma limit 90 calls, 0,25 USD i 2 godziny. Aktualna konserwatywna rezerwacja z marginesem wynosi około 0,1589 USD. Scoring korzysta z `benchmarks/secure_scoring/openai_pilot_030_v1/labels.jsonl`. Najpierw wróć jednak z raportem smoke; decyzja o pilocie jest osobną bramką.

## Co jest mierzone

| Obszar | Pomiar | Interpretacja |
|---|---|---|
| Kompletność | expected/received i dokładnie jeden terminalny rekord per sample | czy harness nie zgubił błędu ani próbki |
| Kontrakt | `response_schema_valid` | czy strict structured output został poprawnie odczytany i zwalidowany lokalnie |
| Decyzja produktu | verdict, trust score, confidence, categories i action | czy wynik modelu mapuje się na allow/warn/hide zgodnie z bieżącą polityką |
| Golden smoke | oczekiwana akcja na pięciu fixture'ach | tylko ręczna kontrola przewodu, nie estymata jakości |
| Niezawodność | status, attempts, retry, timeout/429/5xx/refusal/invalid output | wszystkie niepowodzenia zostają w mianowniku; status pozostaje błędem, a action=`allow` odzwierciedla obecny fail-open produktu |
| Zużycie | input/cached/output/reasoning/total tokens | faktyczne usage zwrócone przez OpenAI |
| Koszt | observed USD i lokalna konserwatywna rezerwacja | observed to koszt wyliczony z usage; invoice providera pozostaje rozstrzygający |
| Czas | min/median/max end-to-end latency rekordów ze statusem `success` | opis przewodu; przy n=5 bez p95/p99 |
| Bezpieczeństwo | blocked tool proposal, exact system/secret disclosure i model drift | disclosure daje `SECURITY_FAIL`; zablokowana propozycja jest high diagnostic, a drift daje `INVALID` |
| Jakość pilota | TP/FP/TN/FN, precision, recall, F1, FPR, FNR, specificity i balanced accuracy | action `warn`/`hide` jest wynikiem pozytywnym; wszystkie metryki dla `n=30` są opisowe |
| Niepewność pilota | Wilson 95% dla recall, FPR i specificity | pokazuje szerokość niepewności; nie dowodzi progu produkcyjnego |
| Latency pilota | min/mediana/IQR/max tylko dla `success` | bez p95/p99 przy tak małej próbie |
| Workflow CrewAI | liczba i kolejność calls, rola, task, request/response hash, usage, finish reason i latency | sukces wymaga dokładnie 3 calls; zablokowana czwarta próba oznacza drift konfiguracji |
| Frozen tools CrewAI | 2 deterministyczne tool events na próbkę, `network_used=false`, wersja i `as_of` | dowód domenowy jest odtwarzalny; nie mierzy jakości live RDAP/WHOIS |
| Izolacja CrewAI | stan telemetry/tracing, brak proxy i socket egress tylko do OpenAI | każda próba innego hosta kończy kampanię jako zdarzenie krytyczne |

Pięciomailowy raport celowo nie zawiera precision, recall, F1 ani FPR. Dla 50 benign nawet wynik 0 false positives daje jednostronną górną granicę 95% około 5,8%, więc późniejszy `50/50` confirmation także nie dowodzi `FPR ≤ 2%`.

## Gdzie są wyniki

Domyślnie każdy live run trafia do ignorowanego przez Git katalogu:

```text
benchmark-runs/<campaign>__<UTC>__<id>/
├── run_manifest.json      # kod/git/config/model/endpoint i hashe zamrożonych assetów
├── budget_ledger.json     # attempts, koszt observed i rezerwacja, stop reason
├── attempts.jsonl         # append-only started/finished event dla każdej próby
├── results.jsonl          # źródło prawdy: jeden ResultRecord na próbkę
├── calls.jsonl            # CrewAI: jeden rekord na rzeczywisty call roli
├── tool_events.jsonl      # CrewAI: hashe lokalnego frozen evidence, bez raw danych
└── scoring/
    ├── scored_results.jsonl
    ├── metrics.json
    ├── metrics.csv
    └── report.md
```

Najpierw otwórz `scoring/report.md`, potem `scoring/metrics.json`. Do audytu retry i błędów użyj `attempts.jsonl`; do własnej analizy per wiadomość użyj `results.jsonl` i `scored_results.jsonl`. Dla CrewAI sprawdź także `calls.jsonl` oraz `tool_events.jsonl`. Wszystkie artefakty runu mają uprawnienia katalogu `0700` i plików `0600`.

Statusy końcowe:

- `READINESS_PASS` — przewód, schema, action mapping i pięć golden actions przeszły;
- `READINESS_PASS_WITH_GOLDEN_MISMATCH` — harness działa, ale co najmniej jedna oczekiwana akcja wymaga ręcznej inspekcji;
- `READINESS_FAIL` — brak rekordu, invalid output, błąd techniczny albo `allow` na zamrożonym prompt-injection probe;
- `SECURITY_FAIL` — krytyczne zdarzenie; nie rozszerzaj testu;
- `INVALID` — drift modelu/konfiguracji albo niespójny protokół; runu nie wolno naprawiać przez usuwanie rekordów;
- `INCONCLUSIVE` — jedyny uczciwy wniosek porównawczy przy jednym modelu i małym pilocie;
- `PILOT_READY_FOR_SELECTION` — 30/30 terminalnych wyników, zero błędów technicznych i krytycznych zdarzeń oraz przejście prerejestrowanych bramek pilota; nadal `INCONCLUSIVE` porównawczo;
- `PILOT_HOLD` — pilot jest policzony, ale nie przeszedł co najmniej jednej bramki jakości/niezawodności; najpierw analiza, bez automatycznego rerunu.

## Zaktualizowana kolejność dalszych prac

1. Direct smoke i pilot `n=30` są ukończone. Zachować oba runy; pilot ma `PILOT_HOLD` przez jeden benign `hide`, więc wynik wymaga analizy i pozostaje `INCONCLUSIVE`.
2. Utwardzony CrewAI Offline, frozen evidence, call ledger, scoring i testy są zaimplementowane. Produkcyjny Crew pozostaje niezmieniony.
3. Pełne testy, readiness i dry-run kampanii `CREWAI_OFFLINE_SMOKE_001` są ukończone: runtime nie wykonał żadnego provider calla, a telemetria, proxy, model, `store`, retry i rezerwacja przeszły kontrolę.
4. Następny krok: commit/push zamrożonych zmian, sprawdzenie limitu projektu u providera i dokładnie jeden CrewAI live smoke `n=5`.
5. Wykonać scoring, przejrzeć `report.md`, `calls.jsonl` i `tool_events.jsonl`. Przy błędzie nie wykonywać automatycznego rerunu.
6. Tylko po pozytywnym przeglądzie smoke wykonać jeden CrewAI pilot `n=30` na tym samym zestawie. Delta Direct–Crew ma nazwę `system_bundle_delta`, bo Crew dostaje osobny prompt bundle, dodatkową orkiestrację i evidence.
7. Dopiero po przejściu pilotów zaplanować budżetowy selection i oddzielny blind confirmation. Przy jednym modelu status może być najwyżej screeningowy; bez baseline/challengera nie wolno użyć `PROVISIONAL_BEST_FOR_FOLLOWUP`.

W blind confirmation hash scoring bundle musi zostać prerejestrowany w zaufanym miejscu przed pierwszym call, niezależnie od repo i operatora runnera. Sąsiedni `scoring_manifest.json` wystarcza do jawnych syntetycznych pilotów, ale nie jest granicą bezpieczeństwa dla ukrytych labeli.

Budowa harnessu, danych i anotacji jest przygotowaniem przed startem 30-godzinnego zegara. Zegar właściwej kampanii powinien ruszyć dopiero wtedy, gdy każdy porównywany wariant, scorer oraz zamrożony zakres danych przechodzą readiness gate.

## Źródła wersji i ceny

- OpenAI, [GPT-4o mini — snapshot, endpoints, Structured Outputs i cena](https://developers.openai.com/api/docs/models/gpt-4o-mini)
- OpenAI, [Chat Completions API](https://developers.openai.com/api/reference/cli/resources/chat/subresources/completions)
- OpenAI, [kontrola danych API](https://developers.openai.com/api/docs/guides/your-data)
- CrewAI, [Agents 1.15.8](https://docs.crewai.com/v1.15.8/en/concepts/agents), [Tasks 1.15.8](https://docs.crewai.com/v1.15.8/en/concepts/tasks), [Crews 1.15.8](https://docs.crewai.com/v1.15.8/en/concepts/crews) i [LLMs 1.15.8](https://docs.crewai.com/v1.15.8/en/concepts/llms)
- CrewAI, [changelog](https://docs.crewai.com/en/changelog)

Cena i dostępność modelu są częścią zamrożonego manifestu kampanii, ale przed każdym nowym campaign ID trzeba je ponownie zweryfikować w oficjalnej dokumentacji. Benchmark przypina CrewAI `1.15.8`, czyli wersję zainstalowaną i zamrożoną w `uv.lock`; nowsza wersja frameworka wymaga osobnego campaign ID i ponownego testu kontraktu.
