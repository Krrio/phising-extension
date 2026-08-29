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

Gotowe, wykonane i policzone są cztery tory: bazowy OpenAI Direct, CrewAI Offline oraz OpenAI Direct z przypiętymi `gpt-5.4-nano-2026-03-17` i `gpt-5.4-mini-2026-03-17`. Każdy przeszedł smoke `n=5` i technicznie poprawny pilot jakości `n=30`; każdy pilot ma status `PILOT_HOLD`. Piąty tor, Google Gemini 3.5 Flash-Lite, ma gotowy adapter, zamrożone kampanie smoke/pilot, komplet testów kontraktu oraz pozytywny readiness; czeka na commit/push i dokładnie jeden ręcznie potwierdzony live smoke. Wspólny, całkowicie offline exporter `compare` sprawdza integralność źródeł i tworzy dane gotowe do wykresów.

Aktualne wyniki opisowe pilotów na tych samych 30 syntetycznych wiadomościach:

| Wariant | TP / FP / TN / FN | F1 | FPR | Koszt observed | Mediana latency | Status |
|---|---:|---:|---:|---:|---:|---|
| Direct `gpt-4o-mini-2024-07-18` | 15 / 3 / 12 / 0 | 0,909091 | 0,200000 | 0,00773385 USD | 2291,351 ms | `PILOT_HOLD` |
| CrewAI Offline, ten sam model | 15 / 7 / 8 / 0 | 0,810811 | 0,466667 | 0,02364090 USD | 6981,653 ms | `PILOT_HOLD` |
| Direct `gpt-5.4-nano-2026-03-17` | 15 / 11 / 4 / 0 | 0,731707 | 0,733333 | 0,00964995 USD | 1314,905 ms | `PILOT_HOLD` |
| Direct `gpt-5.4-mini-2026-03-17` | 15 / 1 / 14 / 0 | 0,967742 | 0,066667 | 0,03107325 USD | 1290,606 ms | `PILOT_HOLD` |

Wszystkie cztery warianty miały recall `1,0`, ale mały, challenge-enriched pilot nie pozwala ogłosić zwycięzcy ani gotowości produkcyjnej. Mini miało najmniej false positives, lecz nie przeszło bramki `benign_hide_zero`: jeden przekazany do IT phishing został ukryty zamiast dopuszczony lub ostrzeżony. Nano miało 11/15 benign z akcją `warn` albo `hide`, w tym dwa `hide`.

```text
5 syntetycznych runner inputs
        ↓
walidacja label/PII/egress/budżetu
        ↓
Direct adapter OpenAI albo Google, strict JSON, R=1, concurrency=1
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
        ↓
compare: runs.csv + cases.csv + pairwise.csv + comparison.json + report.md
```

Najważniejsze pliki:

| Plik | Rola |
|---|---|
| `benchmark_cli.py` | komendy validate, dry-run, live run, score i compare |
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
| `campaigns/BUDGET_30H_OPENAI_GPT54_NANO_SMOKE_001/` | challenger GPT-5.4 nano: smoke 5, reasoning `none`, aktualny kontrakt Chat Completions |
| `campaigns/BUDGET_30H_OPENAI_GPT54_NANO_PILOT_030_001/` | ten sam zestaw 30 co baseline, limit 60 attempts / 0,25 USD / 2 h |
| `campaigns/BUDGET_30H_OPENAI_GPT54_MINI_SMOKE_001/` | challenger GPT-5.4 Mini: smoke 5, przypięty snapshot, reasoning `none`, limit 0,10 USD |
| `campaigns/BUDGET_30H_OPENAI_GPT54_MINI_PILOT_030_001/` | ten sam zestaw 30 co pozostałe Direct, limit 60 attempts / 0,65 USD / 2 h |
| `campaigns/BUDGET_30H_GOOGLE_GEMINI35_FLASH_LITE_SMOKE_001/` | pierwszy direct challenger Google: Gemini 3.5 Flash-Lite przez Interactions API, smoke 5, limit 0,10 USD |
| `campaigns/BUDGET_30H_GOOGLE_GEMINI35_FLASH_LITE_PILOT_030_001/` | ten sam zestaw 30 i frozen assets, limit 60 attempts / 0,30 USD / 2 h |
| `campaigns/BUDGET_30H_CREWAI_OFFLINE_SMOKE_001/` | utwardzony profil Crew, prompt, frozen evidence i kampania smoke 5 × 3 calls |
| `campaigns/BUDGET_30H_CREWAI_OFFLINE_PILOT_030_001/` | ten sam zestaw 30 co Direct, limit 90 calls / 0,25 USD / 2 h |
| `backend/guardian/src/guardian_classic/benchmark_crew.py` | benchmarkowa fabryka trzech agentów; nie zmienia produkcyjnego Crew |
| `phishing_bench/crewai_offline.py` | izolacja procesu, egress guard, call budget i artefakty CrewAI |
| `phishing_bench/gemini_direct.py` | bezpośredni transport Gemini Interactions z izolacją sieci, limitem odpowiedzi i bezpiecznym parsowaniem usage |
| `phishing_bench/comparison.py` | offline integrity gate i eksport wielu modeli/silników do CSV/JSON/Markdown |
| `phishing_bench/` | transport, kontrakty, ledger, runner i scorer |
| `tests/test_benchmark.py` | deterministyczne testy bez API i bez kosztu |
| `tests/test_crewai_offline.py` | pełny kickoff CrewAI z zamockowaną wyłącznie granicą providera oraz testy telemetrii, egressu i budżetu |
| `tests/test_comparison.py` | porównania sparowane, wykrywanie manipulacji i bezpieczny eksport CSV |
| `tests/test_gpt54_nano_campaign.py` | drift modelu/requestu/cen oraz pełny mockowany run i scoring GPT-5.4 nano |
| `tests/test_gpt54_mini_campaign.py` | drift, budżet, pełny mockowany pilot/scoring i porównanie Mini–Nano |
| `tests/test_gemini_campaign.py` | kontrakt kampanii Gemini, readiness, pełny mockowany pilot/scoring i porównanie cross-provider |
| `tests/test_gemini_transport.py` | nagłówkowe uwierzytelnienie, TLS/egress/proxy, retry, limity odpowiedzi, tool blocking i mapowanie usage Gemini |

Adaptery Direct używają wyłącznie biblioteki standardowej Pythona i nie mają niewidocznych retry SDK. Każdy ma osobną dokładną allowlistę egressu: OpenAI tylko `api.openai.com`, a Gemini tylko `generativelanguage.googleapis.com`. Oba ignorują proxy, nie pobierają URL-i z wiadomości i odmawiają live runu przy aktywnym `SSLKEYLOGFILE`. Tor CrewAI działa w przypiętym środowisku backendu (`crewai==1.15.8`), ale wymusza `max_retries=0`, trzy calls na workflow, dokładny Chat Completions endpoint i `store=false`; dodatkowo wyłącza anonimowe OTLP telemetry, tracking oraz first-run tracing przed pierwszym importem frameworka.

## Jak wykonać test

Wszystkie polecenia uruchamiaj z głównego katalogu repozytorium. Runner wymaga Pythona 3.10+, a testy driftu używają także Node.js dostępnego już w projekcie rozszerzenia.

### 1. Testy lokalne — 0 USD

```bash
python3 -m unittest discover -s benchmarks/tests -v

# Pełny zestaw razem z testami runtime CrewAI:
env -u OPENAI_API_KEY -u GEMINI_API_KEY PYTHONWARNINGS=ignore \
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
- dokładny payload Gemini Interactions, brak `temperature`, tools i stanu, `store=false`, minimal thinking oraz przekazywanie klucza wyłącznie w nagłówku;
- parser statusu, structured output i usage Gemini, w tym cached oraz thought tokens, bez zapisywania sekretów i surowych błędów providera.

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

## CrewAI Offline — wykonany protokół

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

### 3. Pilot CrewAI `n=30` — procedura po przeglądzie smoke

Pilot używa dokładnie tych samych 30 runner inputs i labeli co ukończony pilot Direct. W wykonanej kampanii został uruchomiony dopiero po sprawdzeniu raportu smoke i `calls.jsonl`; poniższe polecenia dokumentują odtwarzalną procedurę, a nie zachętę do rerunu.

```bash
CREW_PILOT_CONFIG="benchmarks/campaigns/BUDGET_30H_CREWAI_OFFLINE_PILOT_030_001/runtime_config.json"

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py validate \
  --campaign "$CREW_PILOT_CONFIG"

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py run \
  --campaign "$CREW_PILOT_CONFIG"
```

Właściwy live pilot miał limit 90 calls, 0,25 USD i 2 godziny; konserwatywna rezerwacja z marginesem wynosiła około 0,1589 USD. Scoring korzysta z `benchmarks/secure_scoring/openai_pilot_030_v1/labels.jsonl`. Zachowaj istniejący run — nowy campaign ID jest wymagany dla każdego świadomego powtórzenia lub zmiany konfiguracji.

## Challenger OpenAI Direct: GPT-5.4 nano — wykonany

Ten tor zachował te same runner inputs, prompt, strict JSON Schema i decision policy, ale przypiął snapshot `gpt-5.4-nano-2026-03-17`. Pozostał na Chat Completions, z rolą `developer`, `max_completion_tokens`, `reasoning_effort="none"`, `temperature=0`, `store=false`, bez tools i z jednym wyborem odpowiedzi.

Smoke zakończył się `READINESS_PASS`: 5/5 `success`, 5/5 strict schema, 5/5 golden actions, zero błędów, retry i security events, koszt 0,00192406 USD, mediana 1825,607 ms. Pilot miał 30/30 `success`, ale zakończył się `PILOT_HOLD`: `TP=15, FP=11, TN=4, FN=0`, F1 `0,731707`, FPR `0,733333`, koszt 0,00964995 USD i mediana 1314,905 ms. Nie uruchamiaj tych campaign IDs ponownie; słaby wynik jakości jest wynikiem eksperymentu, nie powodem do rerunu.

## Challenger OpenAI Direct: GPT-5.4 Mini

Kampania przypina `gpt-5.4-mini-2026-03-17`. Jest to mocniejszy tier tej samej rodziny i ma dokładnie ten sam request profile co Nano, więc porównanie Mini–Nano izoluje zmianę modelu lepiej niż przejście na alias bez datowanego snapshotu. Zamrożona cena z 28 sierpnia 2026 to 0,75 USD/M input, 0,075 USD/M cached input i 4,50 USD/M output.

### 1. Testy, readiness i dry-run Mini — 0 USD

```bash
MINI_SMOKE_CONFIG="benchmarks/campaigns/BUDGET_30H_OPENAI_GPT54_MINI_SMOKE_001/runtime_config.json"

env -u OPENAI_API_KEY PYTHONWARNINGS=ignore \
  backend/guardian/.venv/bin/python -m unittest discover -s benchmarks/tests -v

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py validate \
  --campaign "$MINI_SMOKE_CONFIG"

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py run \
  --campaign "$MINI_SMOKE_CONFIG"
```

Oczekiwane są: `READY_FOR_MANUAL_LIVE_CONFIRMATION`, 5 rekordów, `gpt-5.4-mini-2026-03-17`, rola `developer`, `max_completion_tokens`, reasoning `none`, maksymalnie 10 attempts i zero provider calls w dry-run. Konserwatywna rezerwacja pełnego smoke wynosi `0,0865905 USD`, a twardy cap `0,10 USD`. Gdyby usage było identyczne jak w wykonanym smoke Nano, szacowany koszt Mini wyniósłby około `0,00708285 USD`; to tylko prognoza, rozstrzyga usage i dashboard providera.

### 2. Dokładnie jeden live smoke Mini i scoring

Najpierw commituj i pushuj zamrożony harness, a następnie upewnij się, że `git status --short` nic nie wypisuje. Klucza nie dodawaj do commita ani pliku:

```bash
read -s OPENAI_API_KEY
export OPENAI_API_KEY

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py run \
  --campaign "$MINI_SMOKE_CONFIG" \
  --live \
  --confirm-campaign BUDGET_30H_OPENAI_GPT54_MINI_SMOKE_001

unset OPENAI_API_KEY

MINI_SMOKE_RUN="/absolutna/sciezka/wypisana/przez/live-run"
backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py score \
  --run-dir "$MINI_SMOKE_RUN" \
  --labels benchmarks/secure_scoring/openai_smoke_v1/labels.jsonl

cat "$MINI_SMOKE_RUN/scoring/report.md"
```

Nie uruchamiaj automatycznie drugiego smoke. Do pilota przechodź dopiero po sprawdzeniu 5/5 terminalnych wyników, strict schema, zera błędów/retry/security events, kompletnego usage i `resolved_model` równego przypiętemu snapshotowi.

### 3. Pilot GPT-5.4 Mini `n=30` — dopiero po przejściu smoke

```bash
MINI_PILOT_CONFIG="benchmarks/campaigns/BUDGET_30H_OPENAI_GPT54_MINI_PILOT_030_001/runtime_config.json"

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py validate \
  --campaign "$MINI_PILOT_CONFIG"

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py run \
  --campaign "$MINI_PILOT_CONFIG"
```

Pilot zachowuje dokładnie te same 30 próbek, prompt, schema, politykę, retry i limit 500 output tokens. Ledger rezerwuje `0,5150505 USD`, wymagany cap z marginesem 20% to `0,6180606 USD`, a twardy limit kampanii to `0,65 USD`. To celowo pesymistyczny bezpiecznik. Przy usage identycznym jak w pilocie Nano koszt Mini wyniósłby około `0,03536625 USD`.

Po ręcznej akceptacji smoke i sprawdzeniu czystego worktree:

```bash
read -s OPENAI_API_KEY
export OPENAI_API_KEY

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py run \
  --campaign "$MINI_PILOT_CONFIG" \
  --live \
  --confirm-campaign BUDGET_30H_OPENAI_GPT54_MINI_PILOT_030_001

unset OPENAI_API_KEY

MINI_PILOT_RUN="/absolutna/sciezka/wypisana/przez/live-run"
backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py score \
  --run-dir "$MINI_PILOT_RUN" \
  --labels benchmarks/secure_scoring/openai_pilot_030_v1/labels.jsonl

cat "$MINI_PILOT_RUN/scoring/report.md"
```

Pilot jest screeningiem opisowym. Nie tunuj promptu ani polityki na tych samych 30 rekordach i nie powtarzaj runu po słabym wyniku; każda świadoma zmiana wymaga nowego campaign ID oraz nowego zestawu do potwierdzenia.

## Następny challenger: Google Gemini 3.5 Flash-Lite

Gemini `gemini-3.5-flash-lite` jest pierwszym direct challengerem spoza OpenAI. Google opisuje go jako stabilny, niskokosztowy model do zadań o dużym wolumenie; wspiera Structured Outputs i parametr `thinking_level`. Kampania używa zalecanego dla nowych integracji Interactions API, przypina `thinking_level="minimal"`, nie wysyła `temperature`, nie udostępnia tools i ustawia `store=false`. Ten sam prompt, schema, decision policy oraz próbki pozwalają mierzyć zmianę providera/modelu zamiast zmianę logiki produktu.

Zamrożona standardowa cena Paid Tier sprawdzona 29 sierpnia 2026 wynosi `0,30 USD/M` input, `0,03 USD/M` cached input oraz `2,50 USD/M` output, wliczając thinking tokens. Oficjalne źródła: [model Gemini 3.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite), [Interactions API](https://ai.google.dev/gemini-api/docs/interactions-overview), [REST API v1](https://ai.google.dev/api/interactions-api-v1), [Structured Outputs](https://ai.google.dev/gemini-api/docs/structured-output), [thinking](https://ai.google.dev/gemini-api/docs/generate-content/thinking) i [cennik](https://ai.google.dev/gemini-api/docs/pricing).

Google wskazuje, że w Free Tier przesłane treści mogą być używane do ulepszania produktów, a w Paid Tier — nie. Dlatego live benchmark wykonuj wyłącznie w osobnym płatnym projekcie z project-scoped kluczem i nadal wysyłaj tylko syntetyczne dane z domenami zarezerwowanymi. `store=false` wyłącza stan interakcji po stronie API, ale nie zastępuje warunków przetwarzania danych ani umowy z providerem.

### 1. Testy, validate i dry-run Gemini — 0 USD

Nie wykonuj live runu, dopóki pełny zestaw testów, oba `validate` i smoke dry-run nie przejdą lokalnie. Klucz nie jest do nich potrzebny:

```bash
GEMINI_SMOKE_CONFIG="benchmarks/campaigns/BUDGET_30H_GOOGLE_GEMINI35_FLASH_LITE_SMOKE_001/runtime_config.json"
GEMINI_PILOT_CONFIG="benchmarks/campaigns/BUDGET_30H_GOOGLE_GEMINI35_FLASH_LITE_PILOT_030_001/runtime_config.json"

env -u GEMINI_API_KEY PYTHONWARNINGS=ignore \
  backend/guardian/.venv/bin/python -m unittest discover -s benchmarks/tests -v

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py validate \
  --campaign "$GEMINI_SMOKE_CONFIG"
backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py run \
  --campaign "$GEMINI_SMOKE_CONFIG"

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py validate \
  --campaign "$GEMINI_PILOT_CONFIG"
backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py run \
  --campaign "$GEMINI_PILOT_CONFIG"
```

Oczekiwany kontrakt smoke to 5 rekordów, model `gemini-3.5-flash-lite`, endpoint `/v1/interactions`, strict `response_format`, `thinking_level="minimal"`, `seed=0`, brak `temperature`, tools i zapisu stanu oraz maksymalnie 10 attempts. Twardy cap smoke wynosi `0,10 USD`; pilot ma 30 rekordów, maksymalnie 60 attempts i cap `0,30 USD`.

### 2. Dokładnie jeden live smoke Gemini i scoring

Najpierw commituj zamrożony harness i upewnij się, że worktree jest czysty. Użyj klucza z płatnego projektu; nie zapisuj go w repo, pliku `.env` ani historii polecenia:

```bash
read -s GEMINI_API_KEY
export GEMINI_API_KEY

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py run \
  --campaign "$GEMINI_SMOKE_CONFIG" \
  --live \
  --confirm-campaign BUDGET_30H_GOOGLE_GEMINI35_FLASH_LITE_SMOKE_001

unset GEMINI_API_KEY

GEMINI_SMOKE_RUN="/absolutna/sciezka/wypisana/przez/live-run"
backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py score \
  --run-dir "$GEMINI_SMOKE_RUN" \
  --labels benchmarks/secure_scoring/openai_smoke_v1/labels.jsonl

cat "$GEMINI_SMOKE_RUN/scoring/report.md"
```

Nie powtarzaj smoke automatycznie. Pilot jest dozwolony dopiero po ręcznym sprawdzeniu 5 terminalnych sukcesów, strict schema, dokładnego modelu, kompletnego usage oraz zera błędów, retry i security events.

### 3. Jeden pilot Gemini `n=30` — wyłącznie po przejściu smoke

Po pozytywnym smoke ponownie ustaw klucz i wykonaj dokładnie jeden płatny pilot:

```bash
read -s GEMINI_API_KEY
export GEMINI_API_KEY

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py run \
  --campaign "$GEMINI_PILOT_CONFIG" \
  --live \
  --confirm-campaign BUDGET_30H_GOOGLE_GEMINI35_FLASH_LITE_PILOT_030_001

unset GEMINI_API_KEY

GEMINI_PILOT_RUN="/absolutna/sciezka/wypisana/przez/live-run"
backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py score \
  --run-dir "$GEMINI_PILOT_RUN" \
  --labels benchmarks/secure_scoring/openai_pilot_030_v1/labels.jsonl

cat "$GEMINI_PILOT_RUN/scoring/report.md"
```

Scoring jest offline i nie wykonuje dodatkowych requestów. Zachowaj wynik także wtedy, gdy dostanie `PILOT_HOLD`; nie stroimy promptu ani nie uruchamiamy ponownie tych samych 30 przypadków.

## Porównanie wielu modeli i silników — 0 USD

`compare` nie wykonuje requestów i nie potrzebuje klucza API. Pierwszy `--run` jest baseline. Każdy wariant musi być wcześniej policzony przez `score` na dokładnie tym samym zaufanym bundle labeli. Komenda ponownie sprawdza zamknięte artefakty runu, zgodność datasetu, labeli, decision policy, response schema, per-sample input hash oraz matematykę scoringu.

```bash
DIRECT_RUN="/absolutna/sciezka/do/direct-pilot"
CREW_RUN="/absolutna/sciezka/do/crewai-pilot"
GPT54_NANO_RUN="/absolutna/sciezka/do/gpt54-nano-pilot"
COMPARE_DIR="benchmark-runs/comparisons/THREE_WAY_PILOT_030_001"

python3 benchmarks/benchmark_cli.py compare \
  --run "direct=$DIRECT_RUN" \
  --run "crewai=$CREW_RUN" \
  --run "gpt54_nano=$GPT54_NANO_RUN" \
  --labels benchmarks/secure_scoring/openai_pilot_030_v1/labels.jsonl \
  --output-dir "$COMPARE_DIR"

cat "$COMPARE_DIR/report.md"
```

Wykonany eksport trzywariantowy pozostaje opisowy. CrewAI względem Direct ma `ΔF1=-0,098280`, `ΔFPR=+0,266667`, koszt `×3,056809` i medianę latency `×3,046959`; poprawne tylko po stronie Direct były 4 przypadki, tylko po stronie CrewAI 0. GPT-5.4 Nano względem Direct ma `ΔF1=-0,177384`, `ΔFPR=+0,533333`, koszt `×1,247755` i medianę latency `×0,573856`; poprawne tylko po stronie Direct było 8 przypadków, tylko po stronie Nano 0. To nadal `INCONCLUSIVE`, a nie deklaracja zwycięzcy.

Po wykonaniu i policzeniu Mini dodaj do nowego eksportu czwarty wariant `--run "gpt54_mini=$MINI_PILOT_RUN"`. Nie nadpisuj istniejącego katalogu `THREE_WAY_PILOT_030_001`; użyj nowej nazwy, na przykład `FOUR_WAY_PILOT_030_001`.

Nie mieszaj dwóch osi eksperymentu. OpenAI, Google, Cohere, Mistral i Anthropic to modele/providerzy. CrewAI jest architekturą orkiestracji, nie kolejnym modelem. Pierwsza macierz cross-provider powinna używać jednego direct calla na mail oraz tego samego promptu, schematu i polityki. CrewAI pozostaje osobnym punktem `architecture=crew`.

## Co jest mierzone

| Obszar | Pomiar | Interpretacja |
|---|---|---|
| Kompletność | expected/received i dokładnie jeden terminalny rekord per sample | czy harness nie zgubił błędu ani próbki |
| Kontrakt | `response_schema_valid` | czy strict structured output został poprawnie odczytany i zwalidowany lokalnie |
| Decyzja produktu | verdict, trust score, confidence, categories i action | czy wynik modelu mapuje się na allow/warn/hide zgodnie z bieżącą polityką |
| Golden smoke | oczekiwana akcja na pięciu fixture'ach | tylko ręczna kontrola przewodu, nie estymata jakości |
| Niezawodność | status, attempts, retry, timeout/429/5xx/refusal/invalid output | wszystkie niepowodzenia zostają w mianowniku; status pozostaje błędem, a action=`allow` odzwierciedla obecny fail-open produktu |
| Zużycie | input/cached/output/reasoning/total tokens | faktyczne usage zwrócone przez danego providera |
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

Porównania trafiają do wskazanego `--output-dir`:

```text
benchmark-runs/comparisons/<comparison>/
├── runs.csv          # jeden płaski wiersz na model/silnik
├── cases.csv         # jeden wiersz na wariant × próbkę, format long/tidy
├── pairwise.csv      # zgodność, delty, koszt i latency dla każdej pary
├── comparison.json   # pełny eksport maszynowy i hashe źródeł
└── report.md         # krótka interpretacja bez rankingu
```

Do wykresu jakości/kosztu/latency użyj `runs.csv`. Do heatmap błędów według `scenario`, `difficulty` lub `class_label` użyj `cases.csv`. Pliki nie zawierają surowej treści wiadomości, promptów ani reasoning.

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

1. Zachować bez rerunów ukończone runy Direct, CrewAI Offline, GPT-5.4 Nano i GPT-5.4 Mini oraz ich eksport czterowariantowy; wyniki nadal są opisowe i `INCONCLUSIVE`.
2. Adapter Gemini, testy kontraktu, pełny lokalny zestaw testów, oba `validate` i dry-runy są ukończone bez live calla.
3. Commitnąć i pushnąć zamrożone kampanie Gemini, a następnie wykonać dokładnie jeden smoke `n=5` i policzyć go offline.
4. Tylko po technicznym przejściu smoke wykonać jeden pilot Gemini `n=30`, bez strojenia na widzianym zestawie i bez automatycznego rerunu.
5. Po scoringu Gemini utworzyć nowy eksport pięciowariantowy. Para Direct OpenAI–Direct Gemini ma typ `model_or_provider_delta`: architektura, dane, prompt, schema i polityka są wspólne, ale zmieniają się model, provider i natywny protokół API, więc nie jest to czysta delta modelu. Każde porównanie obejmujące CrewAI pozostaje `system_bundle_delta`.
6. Następnie dodać najwyżej 1–2 kolejne tanie direct adapters innych providerów. Dokładne modele, snapshoty i ceny ponownie zweryfikować tuż przed zamrożeniem każdego campaign ID.
7. Po screeningu wybrać najwyżej dwa warianty według prerejestrowanej polityki obejmującej przede wszystkim FN/recall i FPR, a dopiero potem koszt/latency. Zbudować nowy, niewidziany `binary_quality_v2` i wykonać blind confirmation `n=100` na finalistę. Nie zwiększać automatycznie do 200; druga setka jest dozwolona tylko jako wcześniej zaplanowane powtórzenie lub gdy przedział niepewności jest nadal decyzyjnie zbyt szeroki.
8. `n=30` służy do screeningu i debugowania, `n=100` do ostrożnego confirmation. Żaden wynik syntetyczny sam w sobie nie dowodzi gotowości produkcyjnej; później potrzebny jest osobny, zanonimizowany i zgodnie dopuszczony zestaw z rzeczywistego rozkładu ruchu.

Przy limicie 30 godzin rozsądny zakres to: zachować istniejące cztery piloty, dodać Gemini jako kolejny challenger `5+30`, ewentualnie dołożyć jeszcze najwyżej 1–2 tanie adaptery Direct, a następnie wykonać `2 × 100` blind confirmation tylko dla finalistów. To daje informację o wielu silnikach bez marnowania budżetu na 100–200 maili dla każdego słabego wariantu.

W blind confirmation hash scoring bundle musi zostać prerejestrowany w zaufanym miejscu przed pierwszym call, niezależnie od repo i operatora runnera. Sąsiedni `scoring_manifest.json` wystarcza do jawnych syntetycznych pilotów, ale nie jest granicą bezpieczeństwa dla ukrytych labeli.

Budowa harnessu, danych i anotacji jest przygotowaniem przed startem 30-godzinnego zegara. Zegar właściwej kampanii powinien ruszyć dopiero wtedy, gdy każdy porównywany wariant, scorer oraz zamrożony zakres danych przechodzą readiness gate.

## Źródła wersji i ceny

- OpenAI, [GPT-4o mini — snapshot, endpoints, Structured Outputs i cena](https://developers.openai.com/api/docs/models/gpt-4o-mini)
- OpenAI, [GPT-5.4 nano — snapshot, Structured Outputs i cena](https://developers.openai.com/api/docs/models/gpt-5.4-nano)
- OpenAI, [GPT-5.4 Mini — snapshot, Structured Outputs i cena](https://developers.openai.com/api/docs/models/gpt-5.4-mini)
- OpenAI, [aktualny wybór modeli](https://developers.openai.com/api/docs/models) i [GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
- OpenAI, [praktyki projektowania evali](https://developers.openai.com/api/docs/guides/evaluation-best-practices)
- OpenAI, [Chat Completions API](https://developers.openai.com/api/reference/cli/resources/chat/subresources/completions)
- OpenAI, [kontrola danych API](https://developers.openai.com/api/docs/guides/your-data)
- Cohere, [Command R7B](https://docs.cohere.com/docs/command-r7b) i [Structured Outputs](https://docs.cohere.com/v2/docs/structured-outputs)
- Google, [Gemini 3.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite), [Interactions API](https://ai.google.dev/gemini-api/docs/interactions-overview), [REST API v1](https://ai.google.dev/api/interactions-api-v1), [thinking](https://ai.google.dev/gemini-api/docs/generate-content/thinking), [ceny](https://ai.google.dev/gemini-api/docs/pricing) i [Structured Outputs](https://ai.google.dev/gemini-api/docs/structured-output)
- Mistral, [Mistral Small 4](https://docs.mistral.ai/models/mistral-small-4-0-26-03) i [Structured Outputs](https://docs.mistral.ai/studio/conversations/structured-output/custom)
- CrewAI, [Agents 1.15.8](https://docs.crewai.com/v1.15.8/en/concepts/agents), [Tasks 1.15.8](https://docs.crewai.com/v1.15.8/en/concepts/tasks), [Crews 1.15.8](https://docs.crewai.com/v1.15.8/en/concepts/crews) i [LLMs 1.15.8](https://docs.crewai.com/v1.15.8/en/concepts/llms)
- CrewAI, [changelog](https://docs.crewai.com/en/changelog)

Cena i dostępność modelu są częścią zamrożonego manifestu kampanii, ale przed każdym nowym campaign ID trzeba je ponownie zweryfikować w oficjalnej dokumentacji. Benchmark przypina CrewAI `1.15.8`, czyli wersję zainstalowaną i zamrożoną w `uv.lock`; nowsza wersja frameworka wymaga osobnego campaign ID i ponownego testu kontraktu.
