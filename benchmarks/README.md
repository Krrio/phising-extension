# Benchmark phishing — instrukcja operacyjna

> **Aktualizacja 2026-09-01:** zatwierdzona rozbudowa do symetrycznej macierzy
> GPT-5.4 Nano, GPT-5.4 Mini, Gemini 3.1 i Gemini 3.7 — każdy jako Direct i
> CrewAI, każdy ze smoke `n=5` i pilotem `n=30` — jest opisana w
> [`FULL_MODEL_MATRIX_RUNBOOK.md`](FULL_MODEL_MATRIX_RUNBOOK.md). Ten runbook
> zastępuje starsze rekomendacje z końca niniejszego dokumentu dotyczące
> ograniczenia kolejnej serii do 1–2 adapterów. Historyczne wyniki poniżej
> pozostają bez zmian i nie są przeznaczone do rerunu.

## Werdykt wobec specyfikacji z PDF

Specyfikacja jest dobra jako przewodnik implementacyjny i zgadza się z normatywnym `BENCHMARK_SPEC.md`. Nie należy jednak zaczynać od 200 wiadomości ani traktować pięciu przykładów jako pomiaru jakości. Smoke `n=5` sprawdza przewód, a zamrożony pilot `n=30` daje pierwszy opisowy pomiar jakości w budżecie. Oba etapy mają status `ENGINEERING_PILOT` i żaden nie jest jeszcze rankingiem modeli.

Przed implementacją wprowadzono pięć korekt:

1. Runner nie dostaje labeli ani ścieżki do scoring bundle. Syntetyczne labele smoke są w osobnym katalogu i są otwierane dopiero przez komendę `score`. W prawdziwym blind confirmation scoring bundle musi być poza mountem/użytkownikiem runnera, nie tylko w innym folderze repo.
2. Każdy timeout, 429, 5xx, refusal i invalid output tworzy terminalny `ResultRecord` i pozostaje w mianowniku. Każdy outbound attempt jest liczony przed wysłaniem.
3. Pierwszy test zachowuje obecny produktowy endpoint Chat Completions i prompt. Zmiana na Responses API byłaby osobnym eksperymentem, bo jednoczesna zmiana modelu/endpointu/kontraktu zaciera przyczynę różnicy.
4. Alias `gpt-4o-mini` zastąpiono w kampanii przypiętym snapshotem `gpt-4o-mini-2024-07-18`. OpenAI wymienia go jako snapshot wspierający Structured Outputs; zamrożona cena to 0,15 USD/M input tokens i 0,60 USD/M output tokens.
5. Produkcyjny Crew nie jest używany w benchmarku, bo dziedziczy inne ustawienia i korzysta z live RDAP/WHOIS. Powstał osobny, utwardzony profil `CrewAI Offline`: ten sam snapshot modelu i dane co Direct, trzy jawne wywołania na próbkę, zero retry, zamrożony evidence domenowy, wyłączona telemetria oraz twardy limit wywołań. Przed pilotem `n=30` musi przejść własny smoke `n=5`.

## Co jest gotowe

Gotowe, wykonane i policzone jest osiem torów: bazowy OpenAI Direct, CrewAI Offline z OpenAI, OpenAI Direct z przypiętymi `gpt-5.4-nano-2026-03-17` i `gpt-5.4-mini-2026-03-17`, Google Direct `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite` i natywny `gemini-3.7-flash` oraz CrewAI Offline z natywnym Google `gemini-3.5-flash-lite`. Każdy przeszedł smoke `n=5` i pilot jakości `n=30`; pilot Gemini 3.7 miał 29/30 sukcesów i jeden `incomplete_output`, a pozostałe siedem było technicznie kompletne. Wszystkie piloty zachowują status `PILOT_HOLD`. Historyczny eksport `SEVEN_WAY_PILOT_030_001` nadal obejmuje poprzednie siedem wariantów; Gemini 3.7 trafi do nowego eksportu dopiero razem z pozostałymi ramionami pełnej macierzy. Osobne `FIVE_DIRECT_PILOT_030_001` oraz `GEMINI35_DIRECT_VS_CREWAI_GEMINI_PILOT_030_001` rozdzielają porównanie modeli Direct od porównania całych system bundles.

Oba smoke Gemini 3.7 są zachowanymi negatywnymi wynikami technicznymi. `SMOKE_001` zakończył 10/10 prób timeoutem po 45 s, a diagnostyczny `SMOKE_002` zakończył 5/5 prób timeoutem po 120 s mimo wyłączenia retry. W obu runach brak odpowiedzi i usage; łączna konserwatywna rezerwa nierozstrzygniętego kosztu to `0,124812 USD`. Tor Direct Gemini 3.7 przez synchroniczne stateless Interactions API jest zamknięty, a pilot zablokowany.

Przygotowana 1 września 2026 rozbudowa nie zmienia tych historycznych wyników.
Dodaje osobno wersjonowany Direct Gemini 3.7 przez natywne GenerateContent v1
oraz brakujące pary CrewAI dla GPT-5.4 Nano, GPT-5.4 Mini, Gemini 3.1 i Gemini
3.7. Natywny Direct Gemini 3.7 zakończył smoke `_002` i pilot n=30; oba ID są
zamknięte przed ponowieniem. Pierwszy smoke CrewAI + GPT-5.4 Nano (`_001`)
zakończył się pięcioma błędami `401`, ponieważ do zmiennej `OPENAI_API_KEY`
omyłkowo wczytano klucz Gemini. Nie jest to wynik modelu ani frameworka;
kampania jest zamknięta. `_002` użył poprawnego klucza i wykonał 15/15 calli,
ale zakończył się `READINESS_FAIL`, ponieważ 9/10 raportów specjalistów doszło
do dokładnego limitu 500 tokenów z `finish_reason=length`; observed cost wyniósł
`0,011212 USD`. Wszystkich pięć orkiestratorów miało `stop`, lecz fail-closed
gate nie akceptuje decyzji opartej na uciętym materiale.

Engineering smoke uzasadnił wspólny concise-v2 prompt/profile: jeden akapit i
maksymalnie 600 znaków dla raportu specjalisty, bez zmiany limitu 500 tokenów,
danych, schema, decision policy, liczby ról ani retry. V2 ma osobne campaign IDs
i obowiązuje identycznie GPT-5.4 Nano, GPT-5.4 Mini, Gemini 3.1 i Gemini 3.7.
Stare ID v1 są zamknięte; nowe smoke są gotowe, a ich piloty pozostają
`LIVE_BLOCKED` do czasu przejścia własnego smoke. Dokładny stan, budżet i
komendy zawiera
[`FULL_MODEL_MATRIX_RUNBOOK.md`](FULL_MODEL_MATRIX_RUNBOOK.md).

Pilot natywnego Direct Gemini 3.7 zakończył 30/30 rekordów i 30 attempts bez
retry: 29 `success` oraz jeden `incomplete_output` (`case_038`, finish reason
`length`, 485 output tokens + 375 reasoning tokens). Zamrożona akcja techniczna
`allow` pozostawiła opisową confusion matrix `TP=15, FP=0, TN=15, FN=0`, ale
bramka `technical_failures_zero` nie przeszła, więc status to `PILOT_HOLD`, nie
pełny sukces jakości. Usage jest kompletne, observed cost wyniósł
`0,0735135 USD`, mediana latency sukcesów `9903,467 ms`, a zdarzeń security nie
było. Run pozostaje pełnym wynikiem i nie wolno go powtarzać na tym samym
zbiorze.

Pierwszy live smoke CrewAI Offline + natywny Google `gemini-3.5-flash-lite` jest zachowanym `READINESS_FAIL`: cztery pierwsze calle zakończyły się `504 DEADLINE_EXCEEDED` przy lokalnym limicie 45 s, a piąty jawnym `503 UNAVAILABLE`. Osobny `SMOKE_002` z timeoutem 120 s i zero retry zakończył się `READINESS_PASS`: 5/5 wyników, 15/15 poprawnych calli, brak błędów i zdarzeń security, observed cost `0,0112299 USD`, mediana end-to-end `4469,763 ms`. Pilot `PILOT_030_002` zachował tę samą politykę i zakończył 30/30 workflow bez błędów, 90/90 calli, kosztem `0,0656925 USD` i medianą `4188,024 ms`. Oba zakończone campaign IDs oraz stary pilot 45 s są teraz programowo zablokowane przed rerunem.

Aktualne wyniki opisowe pilotów na tych samych 30 syntetycznych wiadomościach:

| Wariant | TP / FP / TN / FN | F1 | FPR | Koszt observed | Mediana latency | Status |
|---|---:|---:|---:|---:|---:|---|
| Direct `gpt-4o-mini-2024-07-18` | 15 / 3 / 12 / 0 | 0,909091 | 0,200000 | 0,00773385 USD | 2291,351 ms | `PILOT_HOLD` |
| CrewAI Offline, ten sam model | 15 / 7 / 8 / 0 | 0,810811 | 0,466667 | 0,02364090 USD | 6981,653 ms | `PILOT_HOLD` |
| Direct `gpt-5.4-nano-2026-03-17` | 15 / 11 / 4 / 0 | 0,731707 | 0,733333 | 0,00964995 USD | 1314,905 ms | `PILOT_HOLD` |
| Direct `gpt-5.4-mini-2026-03-17` | 15 / 1 / 14 / 0 | 0,967742 | 0,066667 | 0,03107325 USD | 1290,606 ms | `PILOT_HOLD` |
| Direct `gemini-3.5-flash-lite` | 15 / 3 / 12 / 0 | 0,909091 | 0,200000 | 0,02756290 USD | 1238,923 ms | `PILOT_HOLD` |
| Direct `gemini-3.1-flash-lite` | 15 / 3 / 12 / 0 | 0,909091 | 0,200000 | 0,02177500 USD | 3279,744 ms | `PILOT_HOLD` |
| CrewAI Offline + `gemini-3.5-flash-lite` | 15 / 2 / 13 / 0 | 0,937500 | 0,133333 | 0,06569250 USD | 4188,024 ms | `PILOT_HOLD` |

Wszystkie siedem wariantów miało recall `1,0`, ale mały, challenge-enriched pilot nie pozwala ogłosić zwycięzcy ani gotowości produkcyjnej. Mini miało najmniej false positives, lecz nie przeszło bramki `benign_hide_zero`: przekazany do IT phishing (`case_032`) został ukryty przez wszystkie siedem wariantów zamiast dopuszczony lub ostrzeżony. Gemini 3.1 dodatkowo ukrył benign `case_038`, podczas gdy Gemini 3.5 Direct i CrewAI+Gemini tylko ostrzegły, a Mini dopuściło tę wiadomość. Nano miało 11/15 benign z akcją `warn` albo `hide`, w tym dwa `hide`.

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
| `campaigns/BUDGET_30H_GOOGLE_GEMINI35_FLASH_LITE_SMOKE_001/` | historyczny pierwszy smoke Gemini; zachowany `READINESS_FAIL`, nie uruchamiać ponownie |
| `campaigns/BUDGET_30H_GOOGLE_GEMINI35_FLASH_LITE_SMOKE_002/` | zakończony negatywny smoke diagnostyczny: 1 attempt, bezpieczny keyset bez `id`, protocol fail-fast |
| `campaigns/BUDGET_30H_GOOGLE_GEMINI35_FLASH_LITE_SMOKE_003/` | zakończony `READINESS_PASS`: wąska, audytowalna obsługa braku `id` tylko dla kompletnego stateless response |
| `campaigns/BUDGET_30H_GOOGLE_GEMINI35_FLASH_LITE_PILOT_030_002/` | zakończony `PILOT_HOLD`: 30/30 sukcesów, ten sam zestaw i frozen assets, bez retry i błędów technicznych |
| `campaigns/BUDGET_30H_GOOGLE_GEMINI31_FLASH_LITE_{SMOKE_001,PILOT_030_001}/` | zakończony Direct challenger: smoke `READINESS_PASS`, pilot 30/30 technicznie poprawny i `PILOT_HOLD` |
| `campaigns/BUDGET_30H_GOOGLE_GEMINI37_FLASH_SMOKE_001/` | zachowany `READINESS_FAIL`: 10 timeoutów po 45 s; nie uruchamiać ponownie |
| `campaigns/BUDGET_30H_GOOGLE_GEMINI37_FLASH_SMOKE_002/` | zachowany `READINESS_FAIL`: 5 timeoutów po 120 s, zero retry, usage nieznane; nie uruchamiać ponownie |
| `campaigns/BUDGET_30H_GOOGLE_GEMINI37_FLASH_PILOT_030_001/` | zablokowany po dwóch negatywnych smoke; nie uruchamiać |
| `campaigns/BUDGET_30H_GOOGLE_NATIVE_GEMINI37_FLASH_SMOKE_001/` | zachowany `READINESS_FAIL`: pierwszy request GenerateContent zwrócił HTTP 503, a fail-fast zatrzymał pozostałe cztery próbki; nie uruchamiać ponownie |
| `campaigns/BUDGET_30H_GOOGLE_NATIVE_GEMINI37_FLASH_SMOKE_002/` | zakończony `READINESS_PASS`: 5/5 sukcesów, zero retry i błędów, koszt `0,0114915 USD`, mediana `11774,448 ms`; nie uruchamiać ponownie |
| `campaigns/BUDGET_30H_GOOGLE_NATIVE_GEMINI37_FLASH_PILOT_030_001/` | zakończony `PILOT_HOLD`: 29/30 sukcesów, jeden `incomplete_output`, koszt `0,0735135 USD`, mediana sukcesów `9903,467 ms`; nie uruchamiać ponownie |
| `campaigns/BUDGET_30H_CREWAI_OFFLINE_SMOKE_001/` | utwardzony profil Crew, prompt, frozen evidence i kampania smoke 5 × 3 calls |
| `campaigns/BUDGET_30H_CREWAI_OFFLINE_PILOT_030_001/` | ten sam zestaw 30 co Direct, limit 90 calls / 0,25 USD / 2 h |
| `campaigns/BUDGET_30H_CREWAI_GOOGLE_GEMINI35_FLASH_LITE_OFFLINE_SMOKE_001/` | zachowany `READINESS_FAIL`: 5 calli pierwszej roli, 4 × 504 i 1 × 503, bez retry; nie uruchamiać ponownie |
| `campaigns/BUDGET_30H_CREWAI_GOOGLE_GEMINI35_FLASH_LITE_OFFLINE_SMOKE_002/` | zakończony `READINESS_PASS`: 5/5 sukcesów, 15/15 calli, zero retry i błędów, koszt `0,0112299 USD`; programowo `LIVE_BLOCKED` |
| `campaigns/BUDGET_30H_CREWAI_GOOGLE_GEMINI35_FLASH_LITE_OFFLINE_PILOT_030_001/` | pierwotny pilot 45 s; programowo `LIVE_BLOCKED`, nie uruchamiać |
| `campaigns/BUDGET_30H_CREWAI_GOOGLE_GEMINI35_FLASH_LITE_OFFLINE_PILOT_030_002/` | zakończony `PILOT_HOLD`: 30/30 sukcesów, 90 calli, koszt `0,0656925 USD`; programowo `LIVE_BLOCKED` |
| `campaigns/BUDGET_30H_CREWAI_OPENAI_GPT54_NANO_OFFLINE_SMOKE_001/` | zachowany `READINESS_FAIL`: 5/5 błędów uwierzytelnienia po użyciu klucza Gemini wobec OpenAI, bez wyniku modelu; nie uruchamiać ponownie |
| `campaigns/BUDGET_30H_CREWAI_OPENAI_GPT54_NANO_OFFLINE_SMOKE_002/` | zachowany `READINESS_FAIL`: 15/15 calli, lecz 9/10 raportów specjalistów zakończonych `length`; koszt `0,011212 USD`; nie uruchamiać ponownie |
| `campaigns/BUDGET_30H_CREWAI_OPENAI_GPT54_NANO_OFFLINE_SMOKE_003/` | zakończony `READINESS_PASS`: 5/5 sukcesów, 15/15 calli zakończonych `stop`, koszt `0,00627115 USD`, mediana `5249,214 ms`; programowo `LIVE_BLOCKED` |
| `campaigns/BUDGET_30H_CREWAI_OPENAI_GPT54_NANO_OFFLINE_PILOT_030_002/` | zakończony `PILOT_HOLD`: 30/30 sukcesów, TP=15, FP=10, TN=5, FN=0, koszt `0,0377574 USD`; programowo `LIVE_BLOCKED` |
| `campaigns/BUDGET_30H_CREWAI_OFFLINE_SMOKE_001/{crew_system_prompt_v2.txt,crew_profile_v2.json}` | wspólny, zamrożony kontrakt krótkich raportów specjalistów dla czterech nowych ramion CrewAI |
| `campaigns/BUDGET_30H_CREWAI_{OPENAI,GOOGLE}_*/` | nowe concise-v2 smoke/pilot mają osobne ID; ramię Nano jest zamknięte, pozostałe smoke są aktywne, a ich piloty czekają na własne bramki |
| `backend/guardian/src/guardian_classic/benchmark_crew.py` | benchmarkowa fabryka trzech agentów; nie zmienia produkcyjnego Crew |
| `phishing_bench/crewai_offline.py` | izolacja procesu, egress guard, call budget i artefakty CrewAI |
| `phishing_bench/gemini_direct.py` | bezpośrednie transporty Gemini Interactions i natywnego GenerateContent z izolacją sieci, jawnymi kontraktami, limitem odpowiedzi i bezpiecznym parsowaniem usage |
| `phishing_bench/comparison.py` | offline integrity gate i eksport wielu modeli/silników do CSV/JSON/Markdown |
| `phishing_bench/` | transport, kontrakty, ledger, runner i scorer |
| `tests/test_benchmark.py` | deterministyczne testy bez API i bez kosztu |
| `tests/test_crewai_offline.py` | pełny kickoff CrewAI z zamockowaną wyłącznie granicą providera oraz testy telemetrii, egressu i budżetu |
| `tests/test_comparison.py` | porównania sparowane, wykrywanie manipulacji i bezpieczny eksport CSV |
| `tests/test_gpt54_nano_campaign.py` | drift modelu/requestu/cen oraz pełny mockowany run i scoring GPT-5.4 nano |
| `tests/test_gpt54_mini_campaign.py` | drift, budżet, pełny mockowany pilot/scoring i porównanie Mini–Nano |
| `tests/test_gemini_campaign.py` | kontrakt kampanii Gemini, readiness, protocol fail-fast, pełny mockowany pilot/scoring i porównanie cross-provider |
| `tests/test_gemini_transport.py` | auth i rewizja w nagłówkach, TLS/egress/proxy, retry, bezpieczny fingerprint, limity odpowiedzi, tool blocking i mapowanie usage Gemini |
| `tests/test_gemini_challenger_campaigns.py` | kontrakty, ceny, expiry, payloady oraz pełny mockowany scoring Gemini 3.1 i 3.7 |
| `tests/test_crewai_gemini.py` | natywne GenerateContent v1, `store=false`, TLS/proxy/Vertex, call ceiling, cleanup, usage i pełny mockowany pilot CrewAI+Gemini |

Adaptery Direct używają wyłącznie biblioteki standardowej Pythona i nie mają niewidocznych retry SDK. Każdy ma osobną dokładną allowlistę egressu: OpenAI tylko `api.openai.com`, a Gemini tylko `generativelanguage.googleapis.com`. Oba ignorują proxy, nie pobierają URL-i z wiadomości i odmawiają live runu przy aktywnym `SSLKEYLOGFILE`. Tor CrewAI działa w przypiętym środowisku backendu (`crewai==1.15.8`); OpenAI używa Chat Completions, a Google przypiętego `google-genai==1.65.0` i natywnego GenerateContent v1. Oba wymuszają trzy calls, zero retry, brak narzędzi agentów, `store=false`, wyłączoną telemetrię i dokładny egress. Google dodatkowo czyści ambient Vertex/Google Cloud, wymusza HTTPX bez proxy/redirectów i sprawdza rzeczywisty root request body z `store=false`.

Przed importem CrewAI i przed każdym realnym transportem harness odrzuca też
jednoznaczny cross-provider key swap: klucz Google o formacie `AIza…` w
`OPENAI_API_KEY` albo klucz OpenAI `sk-…` w `GEMINI_API_KEY`. Błąd nie wypisuje
klucza i kończy się przed requestem. Jest to bezpiecznik dla oczywistych pomyłek,
nie zamiennik poprawnego zarządzania i rotacji sekretów.

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
- usuwanie sekretów oraz zamaskowanych przez providera fragmentów kluczy z artefaktów;
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
- wyłączenie anonimowej telemetrii/tracingu CrewAI oraz blokadę każdego hosta poza wybranym OpenAI/Google endpointem;
- dokładny payload Gemini Interactions, brak `temperature`, tools i stanu, `store=false`, model-specific `minimal`/`low` thinking oraz przekazywanie klucza wyłącznie w nagłówku;
- parser statusu, structured output i usage Gemini, w tym cached oraz thought tokens, bez zapisywania sekretów i surowych błędów providera.
- natywny CrewAI+Gemini GenerateContent v1: `store=false` na wire body, pojedyncza próba, HTTPX bez proxy/redirectów, `use_vertexai=false`, strict schema tylko na orkiestratorze i cleanup obu klientów SDK.

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

Gemini `gemini-3.5-flash-lite` jest pierwszym direct challengerem spoza OpenAI. Google opisuje go jako stabilny, niskokosztowy model do zadań o dużym wolumenie; wspiera Structured Outputs i parametr `thinking_level`. Kampania używa Interactions API, przypina `thinking_level="minimal"`, nie wysyła `temperature`, nie udostępnia tools i ustawia `store=false`. Ten sam prompt, schema, decision policy oraz próbki pozwalają mierzyć zmianę providera/modelu zamiast zmianę logiki produktu.

Historyczny `SMOKE_001` wykonał 10 prób i każdą zakończył `invalid_provider_response`, ponieważ w odpowiedzi nie było oczekiwanego top-level `id`. `SMOKE_002` dodał bezpieczny fingerprint oraz fail-fast i zakończył się `READINESS_FAIL` po dokładnie jednym outbound attempt; pozostałe cztery rekordy dostały `campaign_stopped`. Provider zwrócił HTTP `200` oraz dokładnie siedem nazw pól: `created,model,object,status,steps,updated,usage`, ale nadal bez `id`. To wyklucza brak środków jako przyczynę tego runu: billing/auth powinien dać błąd HTTP, a nie sukces `200`. Koszt `_002` pozostaje nieznany, ponieważ parser świadomie nie odczytywał `usage` po odrzuceniu metadanych. Surowe odpowiedzi celowo nie są zapisywane.

Oficjalny kontrakt nadal opisuje `id`, więc nie traktujemy jego braku jako ogólnej nowej reguły Gemini. `SMOKE_003` dopuszcza brak `id` wyłącznie dla żądania `store=false` i dokładnie zaobserwowanego kompletnego kształtu stateless; `id=null`, brak któregokolwiek z siedmiu pól, dodatkowe pole, niewłaściwe `object`, model, status, timestampy, steps lub usage nadal kończą kampanię. Każdy zaakceptowany brak `id` jest zapisany per rekord jako `provider_metadata_omission` z severity `info` i hashem odpowiedzi, bez jej treści. Nagłówek `Api-Revision: 2026-05-20` pozostaje jawnym znacznikiem oczekiwanego kontraktu. Błędy protokołu i usage nie są retryowane; pierwszy taki błąd zatrzymuje pozostałe rekordy. Nieretryowalny błąd billing/auth/config także kończy kampanię po jednym requestcie, a `429` lub `5xx` dostaje tylko jeden retry przed zatrzymaniem.

Zamrożona standardowa cena Paid Tier sprawdzona 29 sierpnia 2026 wynosi `0,30 USD/M` input, `0,03 USD/M` cached input oraz `2,50 USD/M` output, wliczając thinking tokens. Oficjalne źródła: [model Gemini 3.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite), [Interactions API](https://ai.google.dev/gemini-api/docs/interactions-overview), [REST API v1](https://ai.google.dev/api/interactions-api-v1), [zmiany protokołu z maja 2026](https://ai.google.dev/gemini-api/docs/interactions-breaking-changes-may-2026), [Structured Outputs](https://ai.google.dev/gemini-api/docs/structured-output), [thinking](https://ai.google.dev/gemini-api/docs/generate-content/thinking) i [cennik](https://ai.google.dev/gemini-api/docs/pricing).

Google wskazuje, że w Free Tier przesłane treści mogą być używane do ulepszania produktów, a w Paid Tier — nie. Dlatego live benchmark wykonuj wyłącznie w osobnym płatnym projekcie z project-scoped kluczem i nadal wysyłaj tylko syntetyczne dane z domenami zarezerwowanymi. `store=false` wyłącza stan interakcji po stronie API, ale nie zastępuje warunków przetwarzania danych ani umowy z providerem.

### 1. Testy, validate i dry-run Gemini — 0 USD

Nie wykonuj live runu, dopóki pełny zestaw testów, oba `validate` i smoke dry-run nie przejdą lokalnie. Klucz nie jest do nich potrzebny:

```bash
GEMINI_SMOKE_CONFIG="benchmarks/campaigns/BUDGET_30H_GOOGLE_GEMINI35_FLASH_LITE_SMOKE_003/runtime_config.json"
GEMINI_PILOT_CONFIG="benchmarks/campaigns/BUDGET_30H_GOOGLE_GEMINI35_FLASH_LITE_PILOT_030_002/runtime_config.json"

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

Oczekiwany kontrakt smoke to 5 rekordów, model `gemini-3.5-flash-lite`, endpoint `/v1/interactions`, nagłówek `Api-Revision: 2026-05-20`, strict `response_format`, `thinking_level="minimal"`, `seed=0`, brak `temperature`, tools i zapisu stanu oraz maksymalnie 10 attempts. Twardy cap smoke wynosi `0,10 USD`; przy fatalnym błędzie protokołu `_003` kończy się jednak po pierwszym outbound attempt. Pilot ma 30 rekordów, maksymalnie 60 attempts i cap `0,30 USD`.

### 2. Zakończony live smoke Gemini `_003` — nie powtarzać

Run `BUDGET_30H_GOOGLE_GEMINI35_FLASH_LITE_SMOKE_003__20260829T135622Z__f7ccca3b` zakończył się `READINESS_PASS`: 5/5 `success`, 5/5 strict schema, 5/5 golden actions, dokładny model, kompletne usage, zero błędów, retry i krytycznych security events. Każda odpowiedź nie miała `id`, dlatego raport zawiera pięć jawnych `provider_metadata_omission`; wszystkie pozostałe elementy zamrożonego kontraktu przeszły. Zaobserwowany koszt wyniósł `0,0046141 USD`, mediana latency `1259,930 ms`, a commit runu `7880f1f7e5f90cb3c4f2892f972e7e27f1f12180` miał `dirty=false`. Ten smoke jest zamknięty i nie wolno go uruchamiać ponownie.

### 3. Zakończony pilot Gemini `n=30` — nie powtarzać

Run `BUDGET_30H_GOOGLE_GEMINI35_FLASH_LITE_PILOT_030_002__20260829T140152Z__4b11de9e` zakończył się `PILOT_HOLD`, ale technicznie przeszedł 30/30 próbek bez retry, prób o nieznanym koszcie ani krytycznych zdarzeń. Wynik to `TP=15, FP=3, TN=12, FN=0`, precision `0,833333`, recall `1,0`, F1 `0,909091`, FPR `0,2`, koszt `0,0275629 USD` i mediana `1238,923 ms`. Wszystkie 30 braków `id` zostało jawnie zapisanych jako `provider_metadata_omission`.

Jedyna nieprzejściowa bramka to `benign_hide_zero`: przekazany do IT raport o phishingu (`case_032`) został sklasyfikowany jako phishing i ukryty, mimo że golden dopuszcza `allow|warn`. Ten sam błąd popełniło wszystkie sześć wykonanych wariantów. Pozostałe dwa FP Gemini 3.5 to dopuszczalne goldenem ostrzeżenia dla newslettera z click-trackingiem (`case_037`) i rejestracji wydarzenia przez zewnętrzną platformę (`case_038`); w binarnej confusion matrix każde `warn` na benign nadal jest FP. Mini jako jedyne z sześciu dopuściło oba te przypadki. Wynik jest zamknięty: nie stroimy na tych przypadkach i nie uruchamiamy pilota ponownie.

## Kolejna seria Gemini — stan wykonania i dalsza procedura

Seria dodaje dwa Direct challengery i jeden osobny punkt architektury. `gemini-3.1-flash-lite` jest zakończonym tańszym punktem odniesienia, a `gemini-3.7-flash` został technicznie odrzucony w synchronicznym stateless adapterze Interactions po dwóch negatywnych smoke. CrewAI użyje tego samego `gemini-3.5-flash-lite`, który ma już wynik Direct, ale przez natywne GenerateContent v1, trzy sekwencyjne role i inne wire schema. To porównanie jest jawnie oznaczone `cross_api_system_bundle_delta`; nie izoluje samego wpływu frameworka.

Run Gemini 3.1 `BUDGET_30H_GOOGLE_GEMINI31_FLASH_LITE_PILOT_030_001__20260831T100549Z__e0e9e283` zakończył 30/30 rekordów bez retry i błędów technicznych. Wynik to `TP=15, FP=3, TN=12, FN=0`, F1 `0,909091`, FPR `0,2`, koszt `0,021775 USD` i mediana `3279,744 ms`. Dwa benign `hide` (`case_032`, `case_038`) dały `PILOT_HOLD`; run jest zamkniętym wynikiem i nie wolno go powtarzać ani stroić na jego błędach.

Run Gemini 3.7 `BUDGET_30H_GOOGLE_GEMINI37_FLASH_SMOKE_001__20260831T102411Z__ca943616` zakończył wszystkie 10 attempts po `45,05 s` statusem timeout. Brak odpowiedzi, modelu resolved i usage oznacza, że wynik jakości jest nieocenialny, a `$0` w raporcie nie dowodzi zerowego rachunku. Rezerwa nieznanego kosztu wyniosła `0,083208 USD`; rozstrzygający jest dashboard Google. `SMOKE_001` pozostaje bez zmian jako negatywny artefakt.

Diagnostyczny run `BUDGET_30H_GOOGLE_GEMINI37_FLASH_SMOKE_002__20260831T111704Z__e90f86cd` wyłączył retry i podniósł timeout do 120 s. Każdy z pięciu pojedynczych attempts dotarł do limitu 120 s; run trwał `600,352 s`, nie otrzymał odpowiedzi ani usage i zakończył się `READINESS_FAIL`. Rezerwa nieznanego kosztu wyniosła `0,041604 USD`, więc oba smoke 3.7 łącznie rezerwują `0,124812 USD` do sprawdzenia w dashboardzie Google. To wyklucza hipotezę, że sam timeout 45 s lub retry były przyczyną wyniku. Nie mierzymy tu jakości Gemini 3.7; odrzucamy wyłącznie ten synchroniczny stateless adapter i nie uruchamiamy pilota.

| Tor | Thinking | Smoke / pilot ceiling | Twardy cap | Konserwatywna rezerwa z wymaganym marginesem |
|---|---|---:|---:|---:|
| Direct `gemini-3.1-flash-lite` | `minimal` | 10 / 60 attempts | 0,05 / 0,25 USD | 0,0290085 / 0,2070642 USD |
| Direct `gemini-3.7-flash` (`SMOKE_002`) | `low` | 5 zakończonych timeoutem / pilot zablokowany | 0,05 USD / pilot zablokowany | 0,0416040 USD / pilot zablokowany |
| CrewAI + `gemini-3.5-flash-lite` | `minimal` | 15 / 90 calls | 0,10 / 0,50 USD | 0,06636744 / 0,39619152 USD |

Rezerwa zakłada skrajnie konserwatywny rozmiar wejścia i pełne 500 output tokens; nie jest prognozą rachunku. Rzeczywisty koszt pochodzi z usage, a rozstrzygający pozostaje dashboard Google. Zamrożona cena Gemini 3.7 (`0,75 USD/M` input, `0,075 USD/M` cached input, `3,75 USD/M` output) obowiązuje tylko do 31 grudnia 2026. Harness automatycznie odrzuci nowy płatny run po tej dacie; historyczny scoring nadal działa. Gemini 3.1 używa `0,25/0,025/1,50 USD/M`.

### 1. Testy regresji i kontrola zamkniętej kampanii — 0 USD

Poniższe komendy nie wymagają klucza i nie wysyłają requestów. Pilot CrewAI+Gemini został już wykonany; jego dry-run służy teraz wyłącznie do potwierdzenia blokady przed przypadkowym ponowieniem:

```bash
backend/guardian/.venv/bin/python -m unittest discover -s benchmarks/tests -v

CREW_GEMINI_PILOT_CONFIG="benchmarks/campaigns/BUDGET_30H_CREWAI_GOOGLE_GEMINI35_FLASH_LITE_OFFLINE_PILOT_030_002/runtime_config.json"

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py validate --campaign "$CREW_GEMINI_PILOT_CONFIG"
backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py run --campaign "$CREW_GEMINI_PILOT_CONFIG"
```

Oczekiwany status dla tej kampanii to `LIVE_BLOCKED` oraz tekst `DRY-RUN: nie wykonano żadnego requestu`. Każdy przyszły eksperyment wymaga nowego campaign ID; dopiero jego aktywny dry-run może zwrócić `READY_FOR_MANUAL_LIVE_CONFIRMATION`. W CrewAI nadal audytuj `crewai=1.15.8`, `google-genai=1.65.0`, trzy role, `api_version=v1`, `wire_store_false_verified=true`, `provider_max_attempts=1`, `trust_env=false`, `follow_redirects=false`, `async_transport=httpx`, `use_vertexai=false` i `provider_calls_made=0`.

### 2. Direct Gemini 3.1 — etap zakończony

Smoke i pilot zostały wykonane i sprawdzone. Poniższe polecenia pozostają wyłącznie zapisem procedury; nie uruchamiaj ponownie tych campaign IDs.

```bash
read -s GEMINI_API_KEY
export GEMINI_API_KEY

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py run \
  --campaign "$G31_SMOKE_CONFIG" \
  --live \
  --confirm-campaign BUDGET_30H_GOOGLE_GEMINI31_FLASH_LITE_SMOKE_001

unset GEMINI_API_KEY

G31_SMOKE_RUN="$(find "$PWD/benchmark-runs" -maxdepth 1 -type d \
  -name 'BUDGET_30H_GOOGLE_GEMINI31_FLASH_LITE_SMOKE_001__*' \
  -print | sort | tail -n 1)"

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py score \
  --run-dir "$G31_SMOKE_RUN" \
  --labels benchmarks/secure_scoring/openai_smoke_v1/labels.jsonl

cat "$G31_SMOKE_RUN/scoring/report.md"
```

Zatrzymaj się i sprawdź pięć rekordów, `results.jsonl`, `attempts.jsonl`, model, usage, koszt i security events. Pilot wolno uruchomić tylko po `READINESS_PASS` (albo po świadomie zaakceptowanym `READINESS_PASS_WITH_GOLDEN_MISMATCH`) oraz ręcznej inspekcji.

```bash
read -s GEMINI_API_KEY
export GEMINI_API_KEY

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py run \
  --campaign "$G31_PILOT_CONFIG" \
  --live \
  --confirm-campaign BUDGET_30H_GOOGLE_GEMINI31_FLASH_LITE_PILOT_030_001

unset GEMINI_API_KEY

G31_PILOT_RUN="$(find "$PWD/benchmark-runs" -maxdepth 1 -type d \
  -name 'BUDGET_30H_GOOGLE_GEMINI31_FLASH_LITE_PILOT_030_001__*' \
  -print | sort | tail -n 1)"

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py score \
  --run-dir "$G31_PILOT_RUN" \
  --labels benchmarks/secure_scoring/openai_pilot_030_v1/labels.jsonl

cat "$G31_PILOT_RUN/scoring/report.md"
```

### 3. Direct Gemini 3.7 — tor zamknięty technicznie

`SMOKE_001` z timeoutem 45 s i jednym retry zakończył się 10/10 timeoutów. `SMOKE_002` z timeoutem 120 s i bez retry zakończył się 5/5 timeoutów. Oba runy zachowują model, prompt, schema, dataset, Interactions API, `store=false` i `thinking_level=low`; różnica dotyczyła wyłącznie polityki timeout/retry. Nie uruchamiaj ponownie żadnego z tych campaign IDs ani `PILOT_030_001`.

Status tego toru to techniczne odrzucenie synchronicznego stateless Direct adaptera, a nie ocena jakości modelu. Ewentualne `background=true` albo GenerateContent byłoby nowym eksperymentem z innym kontraktem i nowym campaign ID; nie dokładamy go do obecnej serii przed zakończeniem CrewAI+Gemini i sprawdzeniem budżetu.

### 4. CrewAI + Gemini 3.5 — osobny punkt architektury

Ten tor wykonuje trzy płatne calls na wiadomość. Native SDK nie używa Interactions API; harness wymusza GenerateContent v1, root `store=false`, minimal thinking bez zwracania thoughts, jeden fizyczny attempt, brak Vertex/ambient credentials oraz dokładnie jeden call na rolę.

Pierwszy run `BUDGET_30H_CREWAI_GOOGLE_GEMINI35_FLASH_LITE_OFFLINE_SMOKE_001__20260831T113802Z__d92e2bc2` zakończył się `READINESS_FAIL`. Wykonał dokładnie pięć calli `domain_analyst`: cztery `504` po `44,70–44,82 s` i jeden `503` po `10,489 s`. Nie uruchomił `content_analyst` ani `orchestrator`, nie wykonał retry, zapisał pięć terminalnych rekordów oraz dziesięć lokalnych tool events z `network_used=false`. Usage i koszt pięciu calli są nieznane; ledger zachował konserwatywną rezerwę `0,0553062 USD`, więc `$0` observed nie dowodzi braku opłaty.

Google zaleca zwiększenie deadline'u klienta przy `504`, a `503` traktuje jako przejściowy błąd dostępności. Dlatego `SMOKE_001` pozostaje bez zmian i nie wolno go ponawiać. `SMOKE_002` zachował model, dane, prompty, GenerateContent v1, thinking, schema i zero retry, ale użył timeoutu 120 s. Run `BUDGET_30H_CREWAI_GOOGLE_GEMINI35_FLASH_LITE_OFFLINE_SMOKE_002__20260831T165055Z__5327489f` zakończył się `READINESS_PASS`: 5/5 sukcesów, 15/15 calli, observed cost `0,0112299 USD`, mediana end-to-end `4469,763 ms`. Manifest wskazuje czysty commit `d864f5f2d9736670d2b9800f6af4703b82859007`; ręczny audyt potwierdził kolejność trzech ról, pełne usage, `finish_reason=stop`, brak dodatkowych calli i zgodność hashy.

Pilot `BUDGET_30H_CREWAI_GOOGLE_GEMINI35_FLASH_LITE_OFFLINE_PILOT_030_002__20260831T222709Z__c58b03fe` zakończył się technicznie poprawnie: 30/30 wyników `success`, 90/90 calli bez retry i błędów providera, 60 lokalnych tool events z `network_used=false`, pełne usage oraz zero zdarzeń security. Run powstał na czystym commicie `b00a10dc3d493598344a2acbf83663752636ddbf`; wszystkie hashe artefaktów są zgodne. Observed cost wyniósł `0,0656925 USD`, blisko wcześniejszego liniowego oszacowania `0,0673794 USD`; rezerwa ledgeru `0,3301596 USD` nie jest rachunkiem. Cały run trwał `128,460 s`, a mediana end-to-end wyniosła `4188,024 ms`.

Wynik jakości to `TP=15, FP=2, TN=13, FN=0`, precision `0,882353`, recall `1,0`, F1 `0,9375` i FPR `0,133333`. `PILOT_HOLD` wynika wyłącznie z `case_032`: benign zgłoszenie cytowanego phishingu do IT dostało `phishing/hide`, chociaż dopuszczalne było `allow|warn`. Drugi binarny FP, `case_038`, dostał `suspicious/warn`; jest błędem w binarnej confusion matrix, ale poprawną akcją golden. Łączna zgodność golden actions wynosi 29/30.

Scoring rozdziela teraz `planned_workflows`, `started_workflows`, `not_attempted` i `provider_failures`. Rekordy `campaign_stopped` nadal konserwatywnie pozostają błędami technicznymi w mianownikach, ale nie są błędnie przedstawiane jako osobne wywołania providera. `ledger_reserved_or_observed_usd` jest górną rezerwą bezpieczeństwa, nie potwierdzonym rachunkiem; rzeczywisty spend nadal sprawdzaj w dashboardzie Google.

Nie uruchamiaj ponownie `SMOKE_002`, `PILOT_030_001` ani `PILOT_030_002`. CLI i runner zwracają dla nich `LIVE_BLOCKED`; nowy model, prompt, timeout albo architektura wymagają osobnego campaign ID. `PILOT_HOLD` nie jest zgodą na automatyczny rerun.

Po każdym pilocie zachowaj run bez zmian. Nie powtarzaj płatnego testu na podstawie słabego wyniku i nie dostrajaj promptu na tych 30 przypadkach. Nowy model, cena, prompt, provider API lub konfiguracja CrewAI wymagają nowego campaign ID.

## Porównanie wielu modeli i silników — 0 USD

`compare` nie wykonuje requestów i nie potrzebuje klucza API. Pierwszy `--run` jest baseline. Każdy wariant musi być wcześniej policzony przez `score` na dokładnie tym samym zaufanym bundle labeli. Komenda ponownie sprawdza zamknięte artefakty runu, zgodność datasetu, labeli, decision policy, response schema, per-sample input hash oraz matematykę scoringu.

Aktualne eksporty znajdują się w:

- `benchmark-runs/comparisons/FIVE_DIRECT_PILOT_030_001/` — pięć modeli/providerów Direct;
- `benchmark-runs/comparisons/GEMINI35_DIRECT_VS_CREWAI_GEMINI_PILOT_030_001/` — izolowane zestawienie dwóch system bundles z tym samym model ID;
- `benchmark-runs/comparisons/SEVEN_WAY_PILOT_030_001/` — zbiorcza tabela wszystkich siedmiu wariantów.

CrewAI+Gemini względem Gemini 3.5 Direct ma `ΔF1=+0,028409`, `ΔFPR=-0,066667`, koszt `×2,383367` i medianę latency `×3,380375`; binarna decyzja zgadza się w 29/30, a dokładna akcja w 28/30. Względem GPT-5.4 Mini ma `ΔF1=-0,030242`, `ΔFPR=+0,066666`, koszt `×2,114117` i medianę latency `×3,245006`. Są to różnice opisowe na 30 syntetycznych przypadkach, nie dowód przewagi. Całe porównanie pozostaje `INCONCLUSIVE`.

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
| Odstępstwa providera | `provider_metadata_omission` i hash odpowiedzi | jawny sygnał `info`; w Gemini dopuszczony tylko brak `id` w zamrożonym kompletnym kształcie stateless |
| Jakość pilota | TP/FP/TN/FN, precision, recall, F1, FPR, FNR, specificity i balanced accuracy | action `warn`/`hide` jest wynikiem pozytywnym; wszystkie metryki dla `n=30` są opisowe |
| Niepewność pilota | Wilson 95% dla recall, FPR i specificity | pokazuje szerokość niepewności; nie dowodzi progu produkcyjnego |
| Latency pilota | min/mediana/IQR/max tylko dla `success` | bez p95/p99 przy tak małej próbie |
| Workflow CrewAI | liczba i kolejność calls, rola, task, request/response hash, usage, finish reason i latency | sukces wymaga dokładnie 3 calls; zablokowana czwarta próba oznacza drift konfiguracji |
| Frozen tools CrewAI | 2 deterministyczne tool events na próbkę, `network_used=false`, wersja i `as_of` | dowód domenowy jest odtwarzalny; nie mierzy jakości live RDAP/WHOIS |
| Izolacja CrewAI | stan telemetry/tracing, brak proxy/ambient Vertex i socket egress tylko do przypiętego hosta OpenAI albo Google | każda próba innego hosta kończy kampanię jako zdarzenie krytyczne |

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

1. Zachować bez rerunów siedem ukończonych pilotów Direct/CrewAI oraz eksporty `FIVE_DIRECT_PILOT_030_001`, `GEMINI35_DIRECT_VS_CREWAI_GEMINI_PILOT_030_001` i `SEVEN_WAY_PILOT_030_001`; wyniki pozostają opisowe i `INCONCLUSIVE`.
2. Zachować negatywne Gemini 3.5 `SMOKE_001` i `SMOKE_002`, pozytywny `SMOKE_003` oraz zakończony `PILOT_030_002`; żadnego z tych campaign IDs nie uruchamiać ponownie.
3. Zachować zakończony Gemini 3.1 smoke i pilot: 30/30 sukcesów technicznych, `TP=15, FP=3, TN=12, FN=0`, koszt `0,021775 USD`, mediana `3279,744 ms` i `PILOT_HOLD` przez dwa benign `hide`.
4. Zachować oba negatywne smoke Gemini 3.7: `SMOKE_001` ma 10 timeoutów po 45 s i rezerwę nieznanego kosztu `0,083208 USD`; `SMOKE_002` ma 5 timeoutów po 120 s, zero retry i rezerwę `0,041604 USD`. Sprawdzić łącznie maksymalnie `0,124812 USD` w dashboardzie Google, nie uruchamiać tych campaign IDs ponownie i nie uruchamiać pilota 3.7.
5. Zachować negatywny CrewAI+Gemini `SMOKE_001`, pozytywny `SMOKE_002` oraz zakończony `PILOT_030_002`: 30/30 sukcesów, 90/90 calli, `TP=15, FP=2, TN=13, FN=0`, koszt `0,0656925 USD`, mediana `4188,024 ms` i `PILOT_HOLD` przez jeden benign `hide`. Wszystkie trzy zakończone campaign IDs są zamknięte przed rerunem.
6. Ewentualny powrót do Gemini 3.7 przez background execution lub GenerateContent traktować jako nowy eksperyment z osobnym campaign ID dopiero po zakończeniu bieżącej serii i ponownej decyzji budżetowej.
7. Zachować stare eksporty bez nadpisywania oraz nowe eksporty Direct, Gemini architecture i siedmiowariantowy. Para Direct OpenAI–Direct Gemini ma typ `model_or_provider_delta`; każde porównanie CrewAI+OpenAI pozostaje `system_bundle_delta`, a CrewAI+Gemini jest `cross_api_system_bundle_delta`.
8. Dopiero potem zdecydować, czy budżet uzasadnia najwyżej 1–2 kolejne tanie adaptery. Dokładne modele, snapshoty i ceny ponownie zweryfikować przed zamrożeniem każdego campaign ID.
9. Po screeningu wybrać najwyżej dwa warianty według prerejestrowanej polityki obejmującej przede wszystkim FN/recall i FPR, a dopiero potem koszt/latency. Zbudować nowy, niewidziany `binary_quality_v2` i wykonać blind confirmation `n=100` na finalistę. Nie zwiększać automatycznie do 200; druga setka jest dozwolona tylko jako wcześniej zaplanowane powtórzenie lub gdy przedział niepewności jest nadal decyzyjnie zbyt szeroki.
10. `n=30` służy do screeningu i debugowania, `n=100` do ostrożnego confirmation. Żaden wynik syntetyczny sam w sobie nie dowodzi gotowości produkcyjnej; później potrzebny jest osobny, zanonimizowany i zgodnie dopuszczony zestaw z rzeczywistego rozkładu ruchu.

Przy limicie 30 godzin rozsądny zakres to: zachować istniejące siedem pilotów, ewentualnie dołożyć jeszcze najwyżej 1–2 wcześniej zamrożone tanie adaptery, a następnie wykonać `2 × 100` blind confirmation tylko dla finalistów. To daje informację o wielu silnikach bez marnowania budżetu na 100–200 maili dla każdego słabego wariantu.

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
- Google, [Gemini 3.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite), [Interactions API](https://ai.google.dev/gemini-api/docs/interactions-overview), [REST API v1](https://ai.google.dev/api/interactions-api-v1), [zmiany protokołu z maja 2026](https://ai.google.dev/gemini-api/docs/interactions-breaking-changes-may-2026), [thinking](https://ai.google.dev/gemini-api/docs/generate-content/thinking), [ceny](https://ai.google.dev/gemini-api/docs/pricing), [błędy i retry](https://ai.google.dev/gemini-api/docs/troubleshooting) i [Structured Outputs](https://ai.google.dev/gemini-api/docs/structured-output)
- Google, [Gemini 3.1 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite), [Gemini 3.7 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.7-flash), [zmiany i termin ceny 3.7](https://ai.google.dev/gemini-api/docs/latest-model), [background execution i standardowe timeouty](https://ai.google.dev/gemini-api/docs/background-execution) oraz [GenerateContent request `store`](https://ai.google.dev/api/generate-content)
- Mistral, [Mistral Small 4](https://docs.mistral.ai/models/mistral-small-4-0-26-03) i [Structured Outputs](https://docs.mistral.ai/studio/conversations/structured-output/custom)
- CrewAI, [Agents 1.15.8](https://docs.crewai.com/v1.15.8/en/concepts/agents), [Tasks 1.15.8](https://docs.crewai.com/v1.15.8/en/concepts/tasks), [Crews 1.15.8](https://docs.crewai.com/v1.15.8/en/concepts/crews) i [LLMs 1.15.8](https://docs.crewai.com/v1.15.8/en/concepts/llms)
- CrewAI, [changelog](https://docs.crewai.com/en/changelog)
- CrewAI, [aktualne LLM docs 1.15.18](https://docs.crewai.com/v1.15.18/en/concepts/llms) i [changelog 1.15.18](https://docs.crewai.com/v1.15.18/en/changelog) użyte do sprawdzenia driftu względem przypiętego 1.15.8

Cena i dostępność modelu są częścią zamrożonego manifestu kampanii, ale przed każdym nowym campaign ID trzeba je ponownie zweryfikować w oficjalnej dokumentacji. Benchmark przypina CrewAI `1.15.8`, czyli wersję zainstalowaną i zamrożoną w `uv.lock`; nowsza wersja frameworka wymaga osobnego campaign ID i ponownego testu kontraktu.
