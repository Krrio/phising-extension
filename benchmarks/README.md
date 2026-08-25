# Benchmark phishing — instrukcja operacyjna

## Werdykt wobec specyfikacji z PDF

Specyfikacja jest dobra jako przewodnik implementacyjny i zgadza się z normatywnym `BENCHMARK_SPEC.md`. Nie należy jednak zaczynać od 200 wiadomości ani traktować pięciu przykładów jako pomiaru jakości. Pierwszy etap ma status `ENGINEERING_PILOT`: sprawdza, czy request, schema, retry, budżet, scorer i raport działają poprawnie.

Przed implementacją wprowadzono pięć korekt:

1. Runner nie dostaje labeli ani ścieżki do scoring bundle. Syntetyczne labele smoke są w osobnym katalogu i są otwierane dopiero przez komendę `score`. W prawdziwym blind confirmation scoring bundle musi być poza mountem/użytkownikiem runnera, nie tylko w innym folderze repo.
2. Każdy timeout, 429, 5xx, refusal i invalid output tworzy terminalny `ResultRecord` i pozostaje w mianowniku. Każdy outbound attempt jest liczony przed wysłaniem.
3. Pierwszy test zachowuje obecny produktowy endpoint Chat Completions i prompt. Zmiana na Responses API byłaby osobnym eksperymentem, bo jednoczesna zmiana modelu/endpointu/kontraktu zaciera przyczynę różnicy.
4. Alias `gpt-4o-mini` zastąpiono w kampanii przypiętym snapshotem `gpt-4o-mini-2024-07-18`. OpenAI wymienia go jako snapshot wspierający Structured Outputs; zamrożona cena to 0,15 USD/M input tokens i 0,60 USD/M output tokens.
5. Crew nie wchodzi jeszcze do płatnego porównania. Aktualny Crew dziedziczy inny domyślny model, ma ukryte retry i korzysta z live RDAP/WHOIS. Najpierw potrzebuje jawnego model injection, frozen tools i limitu LLM calls/workflow.

## Co jest gotowe

Gotowy jest kompletny pierwszy przepływ:

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
| `phishing_bench/` | transport, kontrakty, ledger, runner i scorer |
| `tests/test_benchmark.py` | deterministyczne testy bez API i bez kosztu |

Harness używa wyłącznie biblioteki standardowej Pythona. Nie instaluje OpenAI SDK, więc nie występują niewidoczne automatyczne retry. Transport może połączyć się wyłącznie z `https://api.openai.com/v1/chat/completions`, ignoruje proxy z environment, nie podąża za redirectem i nigdy nie pobiera URL-i znajdujących się w wiadomościach. Live run odmawia startu, jeżeli aktywne jest `SSLKEYLOGFILE`.

## Jak wykonać test

Wszystkie polecenia uruchamiaj z głównego katalogu repozytorium. Runner wymaga Pythona 3.10+, a testy driftu używają także Node.js dostępnego już w projekcie rozszerzenia.

### 1. Testy lokalne — 0 USD

```bash
python3 -m unittest discover -s benchmarks/tests -v
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
- pełne score/report na mockowanym providerze.

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

## Co jest mierzone

| Obszar | Pomiar w smoke | Interpretacja |
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

Pięciomailowy raport celowo nie zawiera precision, recall, F1 ani FPR. Dla 50 benign nawet wynik 0 false positives daje jednostronną górną granicę 95% około 5,8%, więc późniejszy `50/50` confirmation także nie dowodzi `FPR ≤ 2%`.

## Gdzie są wyniki

Domyślnie każdy live run trafia do ignorowanego przez Git katalogu:

```text
benchmark-runs/<campaign>__<UTC>__<id>/
├── run_manifest.json      # kod/git/config/model/endpoint i hashe zamrożonych assetów
├── budget_ledger.json     # attempts, koszt observed i rezerwacja, stop reason
├── attempts.jsonl         # append-only started/finished event dla każdej próby
├── results.jsonl          # źródło prawdy: jeden ResultRecord na próbkę
└── scoring/
    ├── scored_results.jsonl
    ├── metrics.json
    ├── metrics.csv
    └── report.md
```

Najpierw otwórz `scoring/report.md`, potem `scoring/metrics.json`. Do audytu retry i błędów użyj `attempts.jsonl`; do własnej analizy per wiadomość użyj `results.jsonl` i `scored_results.jsonl`. Wszystkie artefakty runu mają uprawnienia katalogu `0700` i plików `0600`.

Statusy końcowe:

- `READINESS_PASS` — przewód, schema, action mapping i pięć golden actions przeszły;
- `READINESS_PASS_WITH_GOLDEN_MISMATCH` — harness działa, ale co najmniej jedna oczekiwana akcja wymaga ręcznej inspekcji;
- `READINESS_FAIL` — brak rekordu, invalid output, błąd techniczny albo `allow` na zamrożonym prompt-injection probe;
- `SECURITY_FAIL` — krytyczne zdarzenie; nie rozszerzaj testu;
- `INVALID` — drift modelu/konfiguracji albo niespójny protokół; runu nie wolno naprawiać przez usuwanie rekordów;
- `INCONCLUSIVE` — jedyny uczciwy wniosek porównawczy przy jednym modelu i pięciu rekordach.

## Zaktualizowana kolejność dalszych prac

1. Uruchomić powyższe testy lokalne i jeden live smoke OpenAI Direct.
2. Ręcznie przejrzeć dokładnie pięć wyników, usage i provider dashboard. Nie stroić promptu po każdym pojedynczym błędzie.
3. Przygotować wersjonowany pilot 20–30 wiadomości i zamrozić go przed calls. Nadal raportować go jako pilot, nie ranking.
4. Dodać jawny `crewai.LLM` z tym samym snapshotem do wszystkich trzech agentów, wyłączyć ukryte retry, dodać timeout/max tokens i twardy limit calls/workflow.
5. Wstrzyknąć frozen domain tools z wersjonowanym `as_of`; live RDAP/WHOIS pozostawić do osobnego operational track.
6. Uruchomić te same 5, a potem te same 20–30 rekordów przez Crew offline. Delta Direct–Crew ma nazwę `system_bundle_delta`, bo Crew dostaje dodatkowe evidence.
7. Dopiero po przejściu pilotów zamrozić kampanię `BUDGET_30H`: selection 100 i oddzielny blind confirmation 100, maksymalnie 200 unikalnych wiadomości na model.
8. Selection służy wyłącznie do shortlisty. Formalny wynik pochodzi tylko z blind confirmation; Crew-40 i stability-12 są eksploracyjne.
9. Przy jednym modelu status może być najwyżej screeningowy. Bez baseline/challengera nie wolno użyć `PROVISIONAL_BEST_FOR_FOLLOWUP`.

W blind confirmation hash scoring bundle musi zostać prerejestrowany w zaufanym miejscu przed pierwszym call, niezależnie od repo i operatora runnera. Sąsiedni `scoring_manifest.json` wystarcza do jawnego syntetycznego smoke, ale nie jest granicą bezpieczeństwa dla ukrytych labeli.

Budowa harnessu, danych i anotacji jest przygotowaniem przed startem 30-godzinnego zegara. Zegar właściwej kampanii powinien ruszyć dopiero wtedy, gdy Direct, Crew offline, scorer i 200 zanonimizowanych rekordów przechodzą readiness gate.

## Źródła wersji i ceny

- OpenAI, [GPT-4o mini — snapshot, endpoints, Structured Outputs i cena](https://developers.openai.com/api/docs/models/gpt-4o-mini)
- OpenAI, [Chat Completions API](https://developers.openai.com/api/reference/cli/resources/chat/subresources/completions)
- OpenAI, [kontrola danych API](https://developers.openai.com/api/docs/guides/your-data)

Cena i dostępność modelu są częścią zamrożonego manifestu kampanii, ale przed każdym nowym campaign ID trzeba je ponownie zweryfikować w oficjalnej dokumentacji.
