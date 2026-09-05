# Pełna macierz benchmarków Direct i CrewAI

Stan planu: 2026-09-05. Ten dokument jest operacyjną instrukcją dla czterech
modeli wskazanych do domknięcia:

- `gpt-5.4-nano-2026-03-17`;
- `gpt-5.4-mini-2026-03-17`;
- `gemini-3.1-flash-lite`;
- `gemini-3.7-flash`.

Każdy model ma mieć dwa osobne tory, `Direct` i `CrewAI Offline`, a każdy tor
ma przejść smoke `n=5` oraz pilot jakości `n=30`. Istniejącego kompletnego
zestawu Direct nie uruchamiamy ponownie. Dla Gemini 3.7 zachowujemy oba
nieudane smoke Interactions jako wyniki techniczne i używamy nowego, osobno
zamrożonego Direct przez natywne GenerateContent v1.

## Stan macierzy

| Model | Direct `n=5 → n=30` | CrewAI `n=5 → n=30` |
|---|---|---|
| GPT-5.4 Nano | wykonane: `READINESS_PASS → PILOT_HOLD` | wykonane: concise-v2 `READINESS_PASS → PILOT_HOLD` |
| GPT-5.4 Mini | wykonane: `READINESS_PASS → PILOT_HOLD` | wykonane: concise-v2 `READINESS_PASS → PILOT_HOLD` |
| Gemini 3.1 Flash-Lite | wykonane: `READINESS_PASS → PILOT_HOLD` | wykonane: concise-v2 `READINESS_PASS → PILOT_HOLD` |
| Gemini 3.7 Flash | native Direct wykonany: `READINESS_PASS → PILOT_HOLD` (29/30 success) | wykonane po recovery limitu: `READINESS_PASS → PILOT_HOLD` (30/30 success) |

Gemini 3.5 Flash-Lite ma już wykonane oba tory Direct i CrewAI, więc nie jest
częścią nowych płatnych prób.

`PILOT_HOLD` w istniejących pilotach oznacza wynik jakości niespełniający co
najmniej jednej zamrożonej bramki. Nie oznacza błędu technicznego ani powodu do
automatycznego powtórzenia tych samych danych.

Smoke Nano v1 `_002` wykazał problem protokołu, nie jakości: 9/10 calli
specjalistów zużyło dokładnie 500 output tokens i zakończyło się `length`, choć
wszystkie pięć calli orkiestratora miało `stop`. Nie poluzowujemy po fakcie
bramki kompletności. Wspólny CrewAI concise-v2 ogranicza raport każdego
specjalisty do jednego akapitu i 600 znaków. Zmiana dotyczy wyłącznie formatu i
długości raportów pośrednich, została wykonana przed pilotami i obowiązywała
identycznie Nano, Mini, Gemini 3.1 oraz Gemini 3.7 w protokole v2. Smoke Gemini
3.7 v2 wykazał jednak model-specific problem z budżetem generacji: trzy role
zużyły niemal cały limit 500 na reasoning i zakończyły się `max_tokens`.
Jedyną zmianą parametru inference w recovery v3 jest `max_output_tokens` z 500
na 1000 dla tego modelu;
dane, prompty, schema, decision policy, thinking `low`, timeout, trzy role, zero
retry i pozostałe zabezpieczenia pozostają bez zmian. Jest to jawny
`token-cap-adjusted system bundle`, a nie porównanie apples-to-apples z limitem
500 ani czysta delta frameworka.

## Co jest identyczne

We wszystkich ośmiu ramionach porównania zamrożone są:

- dokładnie te same 5 rekordów smoke i te same 30 rekordów pilota, w tej samej
  kolejności i z tymi samymi anonimowymi UUID;
- ten sam strict response schema;
- ta sama decision policy mapująca wynik na `allow`, `warn` albo `hide`;
- ten sam oddzielny scoring bundle i te same bramki jakości;
- te same mianowniki: timeout, 429, 5xx, refusal i invalid output nie znikają z
  wyniku;
- `concurrency=1`, syntetyczne dane i domeny zarezerwowane; limit odpowiedzi to
  500 tokenów poza jawnym recovery Gemini 3.7 v3, gdzie wynosi 1000;
- brak live RDAP/WHOIS, wyłączona telemetria i zapis stanu, dokładna allowlista
  egressu oraz pełny ledger prób, kosztu i czasu.

Różnica architektoniczna jest jawna i nie może zostać usunięta bez zniszczenia
sensu eksperymentu:

- Direct wykonuje jeden call na wiadomość i używa wspólnego promptu Direct;
- CrewAI wykonuje trzy sekwencyjne calle ról, ma własne prompty ról/zadań i
  zamrożony domain evidence;
- GPT-5.4 Direct i CrewAI używają Chat Completions v1;
- Gemini 3.7 Direct i CrewAI używają natywnego GenerateContent v1;
- istniejący Gemini 3.1 Direct używa Interactions v1, a CrewAI używa
  GenerateContent v1. Ten wariant jest dlatego oznaczony
  `cross_api_system_bundle_delta`, a nie czystą deltą frameworka.

Wynik Direct–CrewAI mierzy cały bundle systemu, nie izolowany wpływ biblioteki
CrewAI.

## Zamrożone kampanie i budżet

| Nowe ramię | Smoke: calls / hard cap | Pilot: calls / hard cap | Konserwatywna rezerwa smoke + pilot |
|---|---:|---:|---:|
| Gemini 3.7 Native Direct | 5 / 0,05 USD | 30 / 0,65 USD | 0,28730175 USD |
| CrewAI + GPT-5.4 Nano | 15 / 0,10 USD | 90 / 0,50 USD | 0,2543172 USD |
| CrewAI + GPT-5.4 Mini | 15 / 0,25 USD | 90 / 1,00 USD | 0,94384575 USD |
| CrewAI + Gemini 3.1 | 15 / 0,10 USD | 90 / 0,50 USD | 0,316269 USD |
| CrewAI + Gemini 3.7 v3, output cap 1000 | 15 / 0,25 USD | 90 / 1,25 USD | 1,184112 USD |
| **Łącznie** | **65 / 0,75 USD** | **390 / 3,90 USD** | **2,9858457 USD** |

Pierwsza natywna próba
`BUDGET_30H_GOOGLE_NATIVE_GEMINI37_FLASH_SMOKE_001__20260901T160523Z__0841f81d`
została zamknięta po jednym `HTTP 503`; fail-fast nie wysłał pozostałych
czterech requestów. Nie uzyskano usage ani wyniku jakości, a ledger zachował
konserwatywną rezerwę `0,008313 USD`.

Osobno zamrożony `_SMOKE_002` przeszedł 5/5: strict schema 5/5, golden actions
5/5, zero błędów, retry, braków usage i zdarzeń bezpieczeństwa. Observed cost
wyniósł `0,0114915 USD`, a mediana latency `11774,448 ms`. Tabela zachowuje
pierwotną konserwatywną rezerwę tego ramienia. Po zastąpieniu rezerwy smoke
kosztem zaobserwowanym oraz dodaniu nieznanej rezerwy `_SMOKE_001`, łączny
znany lub konserwatywnie zarezerwowany koszt całej serii przed pilotem wynosił
`2,68858245 USD`.

Pilot Native Direct zakończył się 29/30 `success` i jednym
`incomplete_output` (`case_038`, finish reason `length`) bez retry i bez braków
usage. Opisowa confusion matrix po zastosowaniu zamrożonej akcji awaryjnej to
`TP=15, FP=0, TN=15, FN=0`, ale bramka `technical_failures_zero` wymusiła
`PILOT_HOLD`. Observed cost wyniósł `0,0735135 USD`, a mediana latency sukcesów
`9903,467 ms`. Po zastąpieniu rezerwy pilota kosztem zaobserwowanym łączny znany
lub konserwatywnie zarezerwowany koszt całej serii wynosi `2,5161582 USD`.

Pierwszy smoke CrewAI + GPT-5.4 Nano użył omyłkowo klucza Gemini i zakończył
się pięcioma odpowiedziami `401 invalid_api_key` przed wykonaniem modelu. Nie
jest to wynik GPT ani CrewAI. Observed usage i koszt wynoszą zero, lecz przy
braku usage ledger zachowuje rezerwę `0,0335568 USD`.

Drugi smoke Nano `_SMOKE_002` użył poprawnego klucza i wykonał dokładnie 15/15
calli bez błędów providera, retry, braków usage ani zdarzeń security. Wszystkie
pięć workflow zakończyło się jednak `incomplete_output`: 4/5 raportów domenowych
i 5/5 raportów treściowych miało `finish_reason=length` przy dokładnie 500
output tokens. Orkiestratory miały `stop`, ale fail-closed gate słusznie nie
oceniał JSON-u powstałego z uciętego materiału. Observed cost wyniósł
`0,011212 USD`; lokalny ledger zachował konserwatywny sufit `0,0335568 USD`.
Run jest zamkniętym `READINESS_FAIL` protokołu v1.

Trzeci smoke Nano `_SMOKE_003` sprawdził wspólny concise-v2 prompt/profile i
zakończył się `READINESS_PASS`: 5/5 workflow oraz 15/15 calli miało `success`
i `finish_reason=stop`, strict schema i golden actions przeszły 5/5, a błędy,
retry, braki usage i zdarzenia security wyniosły zero. Raporty domenowe miały
128–148, treściowe 130–145, a orkiestratory 123–185 output tokens przy
niezmienionym limicie 500. Observed cost wyniósł `0,00627115 USD`, mediana
latency `5249,214 ms`; run powstał na czystym commicie `8a1c966` i jest
zamknięty przed ponowieniem.

Pilot Nano `_PILOT_030_002` jest pełnym, ważnym wynikiem jakości
`PILOT_HOLD`: 30/30 workflow oraz 90/90 calli zakończyło się sukcesem i `stop`,
bez błędów, retry, braków usage ani zdarzeń security. Confusion matrix wynosi
`TP=15, FP=10, TN=5, FN=0`, precision `0,6`, recall `1,0`, F1 `0,75`, FPR
`0,666667` i specificity `0,333333`. Bramki benign przekroczyły limity:
`warn|hide=10/3` oraz `hide=1/0`; jedyny benign `hide` to przekazana do IT
wiadomość phishingowa `case_032`. Dziesięć binary FP i cztery golden action
mismatches są spójne: confusion matrix traktuje każdy benign `warn|hide` jako
positive, podczas gdy frozen golden labels dopuszczają `warn` dla części edge
cases. Observed cost wyniósł `0,0377574 USD`, a mediana latency `4920,023 ms`.
Run powstał na czystym commicie `f6851c3`, jest zamknięty przed ponowieniem i
nie kwalifikuje tego ramienia do selection. Po zastąpieniu rezerwy pilota jego
kosztem observed zachowujemy ten wynik bez dalszego strojenia.

Smoke CrewAI + Gemini 3.1 `_SMOKE_002` zakończył się `READINESS_PASS`: 5/5
workflow i 15/15 calli miało `success` oraz `finish_reason=stop`, strict schema
i golden actions przeszły 5/5, a błędy, retry, braki usage i zdarzenia security
wyniosły zero. Raporty domenowe miały 129–151, treściowe 138–161, a
orkiestratory 105–158 output tokens przy limicie 500. Observed cost wyniósł
`0,007632 USD`, mediana latency `3535,798 ms`; run powstał na czystym commicie
`69d9144` i jest zamknięty przed ponowieniem. Po zastąpieniu rezerwy tego smoke
kosztem observed zachowujemy go jako audytowaną bramkę techniczną.

Pilot CrewAI + Gemini 3.1 `_PILOT_030_002` jest ważnym wynikiem jakości
`PILOT_HOLD`: 30/30 workflow oraz 90/90 calli zakończyło się `success/stop`,
bez błędów, retry, braków usage ani zdarzeń security. Confusion matrix wynosi
`TP=15, FP=2, TN=13, FN=0`, precision `0,882353`, recall `1,0`, F1 `0,9375`,
FPR `0,133333` i specificity `0,866667`. Limit benign `warn|hide` przeszedł
`2/3`, ale bramka benign `hide` nie przeszła `1/0`: `case_032`, czyli
przekazana do IT wiadomość phishingowa, dostała `hide`. Drugie binary FP to
newsletter z trackingiem `case_037`, którego `warn` pozostaje zgodny z frozen
golden action. Observed cost wyniósł `0,04549475 USD`, mediana latency
`3583,168 ms`; run powstał na czystym commicie `1869e26`, jest zamknięty przed
ponowieniem i nie kwalifikuje ramienia do selection. Po zastąpieniu rezerwy
pilota kosztem observed łączny znany lub konserwatywnie zarezerwowany koszt
serii wynosi `2,0874961 USD`.

Smoke CrewAI + GPT-5.4 Mini `_SMOKE_002` zakończył się `READINESS_PASS`: 5/5
workflow i 15/15 calli miało `success` oraz `finish_reason=stop`, strict schema
i golden actions przeszły 5/5, a błędy, retry, braki usage i zdarzenia security
wyniosły zero. Raporty domenowe miały 83–114, treściowe 99–128, a
orkiestratory 104–152 output tokens przy limicie 500. Observed cost wyniósł
`0,02078925 USD`, mediana latency `4607,212 ms`; run powstał na czystym
commicie `ae8a22f` i jest zamknięty przed ponowieniem. Po zastąpieniu rezerwy
smoke kosztem observed łączny znany lub konserwatywnie zarezerwowany koszt
serii wynosi `1,9728511 USD`.

Pilot CrewAI + GPT-5.4 Mini `_PILOT_030_002` jest pełnym, ważnym wynikiem
`PILOT_HOLD`: 30/30 workflow oraz 90/90 calli zakończyło się `success/stop`,
bez błędów, retry, braków usage ani zdarzeń security. Confusion matrix wynosi
`TP=15, FP=2, TN=13, FN=0`, precision `0,882353`, recall `1,0`, F1 `0,9375`,
FPR `0,133333` i specificity `0,866667`. Limit benign `warn|hide` przeszedł
`2/3`, ale bramka benign `hide` nie przeszła `1/0`: przekazana do IT wiadomość
phishingowa `case_032` dostała `hide`. Drugie binary FP to rejestracja na
wydarzenie przez platformę `case_038`, której `warn` pozostaje zgodny z frozen
golden action. Dwa malicious edge cases (`case_023`, `case_029`) dostały
dopuszczalne `warn`; wszystkie 15 malicious pozostało wykrytych. Observed cost
wyniósł `0,12213975 USD`, mediana latency `4095,286 ms`; run powstał na czystym
commicie `3c104f1`, jest zamknięty przed ponowieniem i nie kwalifikuje ramienia
do selection. Po zastąpieniu rezerwy pilota kosztem observed łączny znany lub
konserwatywnie zarezerwowany koszt serii wynosi `1,28657935 USD`.

Smoke CrewAI + Gemini 3.7 `_SMOKE_002` jest zachowanym `READINESS_FAIL`, a nie
wynikiem jakości modelu. Run
`BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_SMOKE_002__20260905T130714Z__c23063b0`
zapisał 5/5 terminalnych rekordów i dokładnie 15 calli bez błędów providera ani
retry, lecz tylko 2/5 workflow zakończyły się `success`. Pozostałe trzy dostały
`incomplete_output`: dwa calle `content_analyst` i jeden `domain_analyst`
zakończyły się `max_tokens` przy limicie 500. Usage jest kompletne: 17447 input,
4016 output (21463 total), w tym 2197 reasoning tokens. Observed cost wyniósł
`0,02814525 USD`, ledger zachował sufit `0,13037175 USD`, a mediana latency dwóch
sukcesów wyniosła `13049,639 ms`. Nie wolno ponawiać `_SMOKE_002` ani uruchamiać
superseded `_PILOT_030_002`.

Recovery używa nowych ID `_SMOKE_003` i `_PILOT_030_003`. Jedyną zmianą
parametru inference względem v2 jest `max_output_tokens=1000`; nowe ID, jawne
disclosure oraz podniesiony hard cap pilota służą zamrożeniu i bezpiecznemu
rozliczeniu tej zmiany. Nie zmieniamy promptów na podstawie wyniku smoke.
Konserwatywna projekcja wynosi odpowiednio
`0,169758 USD` oraz `1,014354 USD`, a wymagane wartości z marginesem to
`0,2037096 USD` i `1,2172248 USD`; twarde capy `0,25 USD` i `1,25 USD` są od
nich wyższe. Konfiguracja ujawnia tę różnicę przez
`same_max_output_tokens=false`, `direct_max_output_tokens=500` oraz
`crewai_max_output_tokens=1000`.

Run recovery
`BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_SMOKE_003__20260905T133129Z__4edc9af3`
uzyskał `READINESS_PASS`: 5/5 wyników, strict schema i golden actions oraz
15/15 calli zakończonych `stop`, bez retry, błędów providera, braków usage i
zdarzeń security. Usage wyniosło 17706 input i 5205 output tokens, w tym 3178
reasoning; pięć calli zużyło ponad poprzedni limit 500, co potwierdza usunięcie
zaobserwowanego ograniczenia v2. Observed cost to `0,03279825 USD`, a mediana
latency `12804,623 ms`. Audyt potwierdził 10/10 lokalnych tool events z
`network_used=false`, zgodność pięciu hashy artefaktów oraz czysty commit
`4f752a5af7b3df64df788cf9abb6abc5ceb7fbeb`. Smoke jest zamknięty przed
ponowieniem; odblokował wyłącznie pilot `_PILOT_030_003`, który został już
wykonany i jest opisany poniżej.

Pilot
`BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_PILOT_030_003__20260905T134533Z__f345115d`
zakończył 30/30 workflow i 90/90 calli ze statusem `success` oraz
`finish_reason=stop`, bez retry, błędów providera, braków usage i zdarzeń
security. Wynik opisowy to `TP=15, FP=1, TN=14, FN=0`, precision `0,9375`,
recall `1,0`, F1 `0,967742`, FPR `0,066667` i golden actions 29/30. Jedyny
błąd to benign/adversarial `case_032`: wiadomość przekazująca phishing do IT
otrzymała `hide` zamiast dopuszczalnego `allow|warn`. Dlatego zamrożona bramka
`benign_hide_zero` nie przeszła i poprawny status to `PILOT_HOLD`.

Usage pilota wyniosło 103278 input i 29604 output tokens, w tym 17493
reasoning (132882 total). Wszystkie 90 calli zakończyło się przed limitem 1000;
24 przekroczyły 500, a maksimum wyniosło 839. Observed cost to
`0,1884735 USD` (`0,00628245 USD` na wiadomość), mediana latency
`10086,1 ms`, a cały run trwał `301,304 s`. Run powstał na czystym commicie
`825a04153e07c4cbfded13f0f8fabf46c10e792e`; audyt potwierdził wszystkie
hashe, 60/60 lokalnych tool events z `network_used=false` i brak sekretów.
Pilot jest zamknięty przed ponowieniem.

Po zastąpieniu obu rezerw recovery ich observed cost, znany lub
konserwatywnie zarezerwowany koszt serii wynosi `0,6275881 USD`.

Hard cap to awaryjny sufit, a nie prognoza rachunku. Konserwatywna rezerwa
zakłada skrajnie niekorzystny token count i maksymalny output każdego calla;
observed cost z usage i billing providera są właściwym wynikiem kosztowym.
Nie pozostała żadna aktywna płatna kampania, więc jej twardy sufit wynosi
`0 USD`. Suma historycznych hard capów
zamrożonego planu to 4,65 USD: smoke 0,75 USD i piloty 3,90 USD. Faktyczny
observed cost dwunastu zakończonych kampanii z kompletnym usage to
`0,5857183 USD`; nieudane próby bez usage zachowują osobne
rezerwy: `0,008313 USD` dla Gemini 3.7 i `0,0335568 USD` dla pierwszego Nano
CrewAI.

Każdy pilot ma tylko 30 wiadomości na ramię. Dla pojedynczego modelu komplet
Direct + CrewAI to 60 ocenianych wiadomości; CrewAI generuje więcej calli, bo
każda wiadomość przechodzi przez trzy role. Maksymalne ścienne limity wszystkich
nowych smoke i pilotów sumują się do 12,5 godziny, więc mieszczą się w limicie
30 godzin. Nie uruchamiamy kampanii równolegle.

## Kampanie

| Tor | Smoke campaign ID | Pilot campaign ID |
|---|---|---|
| Gemini 3.7 Native Direct | `BUDGET_30H_GOOGLE_NATIVE_GEMINI37_FLASH_SMOKE_002` | `BUDGET_30H_GOOGLE_NATIVE_GEMINI37_FLASH_PILOT_030_001` |
| CrewAI + GPT-5.4 Nano | `BUDGET_30H_CREWAI_OPENAI_GPT54_NANO_OFFLINE_SMOKE_003` | `BUDGET_30H_CREWAI_OPENAI_GPT54_NANO_OFFLINE_PILOT_030_002` |
| CrewAI + GPT-5.4 Mini | `BUDGET_30H_CREWAI_OPENAI_GPT54_MINI_OFFLINE_SMOKE_002` | `BUDGET_30H_CREWAI_OPENAI_GPT54_MINI_OFFLINE_PILOT_030_002` |
| CrewAI + Gemini 3.1 | `BUDGET_30H_CREWAI_GOOGLE_GEMINI31_FLASH_LITE_OFFLINE_SMOKE_002` | `BUDGET_30H_CREWAI_GOOGLE_GEMINI31_FLASH_LITE_OFFLINE_PILOT_030_002` |
| CrewAI + Gemini 3.7, token-cap-adjusted v3 | `BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_SMOKE_003` | `BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_PILOT_030_003` |

Gemini 3.7 Native Direct smoke `_002` i pilot są zakończone oraz zamknięte przed
ponowieniem. Nano CrewAI `_SMOKE_001` i `_SMOKE_002` są zamkniętymi wynikami
negatywnymi v1, a `_SMOKE_003` jest zamkniętym `READINESS_PASS` concise-v2.
Pilot Nano v2 jest zamkniętym `PILOT_HOLD`; nie wolno go stroić ani ponawiać na
tych samych 30 przypadkach. Wszystkie nierunowane ID v1 Mini/Gemini także są
programowo zamknięte, aby nie mieszać protokołów. Smoke Gemini 3.1 v2 jest
zamkniętym `READINESS_PASS`, a jego pilot zamkniętym `PILOT_HOLD`; nie wolno
stroić ani ponawiać tych 30 przypadków. Smoke Mini v2 jest zamkniętym
`READINESS_PASS`, a jego pilot zamkniętym `PILOT_HOLD`; nie wolno stroić ani
ponawiać tych 30 przypadków. Gemini 3.7 `_SMOKE_002` jest zamkniętym
`READINESS_FAIL`, a jego `_PILOT_030_002` jest superseded i nie może być
uruchomiony. Token-cap-adjusted `_SMOKE_003` uzyskał audytowany
`READINESS_PASS`, a `_PILOT_030_003` zakończył się technicznie kompletnym
`PILOT_HOLD`; oba są zamknięte przed ponowieniem. Macierz nie ma już aktywnej
płatnej kampanii.

## Etap 0 — końcowa kontrola bez kosztu

Wszystkie płatne runy są zakończone. Po zapisaniu końcowych guardów i
dokumentacji uruchom testy, a następnie zatwierdź i wypchnij zmiany.
`git status --short` powinien być pusty. Klucze API nie mogą znajdować się w
pliku, commicie ani historii terminala.

```bash
env -u OPENAI_API_KEY -u GEMINI_API_KEY PYTHONWARNINGS=ignore \
  backend/guardian/.venv/bin/python -m unittest discover -s benchmarks/tests -q

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py validate \
  --campaign benchmarks/campaigns/BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_PILOT_030_003/runtime_config.json
```

Walidacja powinna zwrócić `LIVE_BLOCKED`, ponieważ pilot jest już zakończony.

## Etap 1 — smoke CrewAI + Gemini 3.7 zakończony

Recovery smoke `_SMOKE_003` został wykonany i audytowany jako
`READINESS_PASS`. Exact run kończy się `__20260905T133129Z__4edc9af3`; jego
wyniki oraz dowody audytu są zapisane wyżej. Campaign ID jest programowo
`LIVE_BLOCKED` i nie wolno uruchamiać go ponownie. Ten etap jest zamknięty.

## Etap 2 — pilot CrewAI + Gemini 3.7 zakończony

Pilot `_PILOT_030_003` został wykonany i audytowany jako technicznie kompletny
`PILOT_HOLD`. Exact run kończy się `__20260905T134533Z__f345115d`; wyniki i
dowody audytu są zapisane wyżej. Campaign ID jest programowo `LIVE_BLOCKED`.
Nie wolno go stroić ani ponawiać na tym samym zbiorze.

## Co mierzymy

- TP, FP, TN, FN oraz precision, recall, F1, FPR, FNR, specificity i balanced
  accuracy dla akcji produktu;
- Wilson 95% CI dla recall, FPR i specificity;
- zgodność strict schema i dokładnego mapowania na `allow|warn|hide`;
- błędy, retry, liczbę rozpoczętych i nieuruchomionych workflows;
- input, cached input, output, reasoning i total tokens;
- observed cost oraz osobno konserwatywną rezerwę ledgera;
- min, medianę, IQR i max latency dla sukcesów;
- zdarzenia bezpieczeństwa, drift modelu i nieautoryzowany egress;
- dla CrewAI: dokładnie trzy role/calle na próbkę i dwa lokalne frozen tool
  events bez użycia sieci.

Przy `n=30` metryki są opisowe. Nie raportujemy przewagi produkcyjnej ani p95 i
p99; końcowy wniosek porównawczy pozostaje `INCONCLUSIVE`.

## Gdzie są wyniki

Każdy run trafia do:

```text
benchmark-runs/<campaign>__<UTC>__<id>/
├── run_manifest.json
├── budget_ledger.json
├── attempts.jsonl
├── results.jsonl
├── calls.jsonl          # CrewAI
├── tool_events.jsonl    # CrewAI
└── scoring/
    ├── scored_results.jsonl
    ├── metrics.json
    ├── metrics.csv
    └── report.md
```

Najpierw czytaj `scoring/report.md`, potem `scoring/metrics.json`. Do wykresów
zbiorczych służą eksporty `runs.csv`, `cases.csv` i `pairwise.csv` tworzone przez
komendę `compare`.

## Końcowy eksport ośmiu ramion

Wszystkie osiem runów jest gotowych. Końcowy eksport został utworzony offline
w `benchmark-runs/comparisons/FULL_EIGHT_ARM_PILOT_030_001/`: zawiera 8
wierszy runów, 240 wierszy per-case i 28 porównań sparowanych. Źródła użyte do
jego utworzenia:

```bash
NANO_DIRECT="$PWD/benchmark-runs/BUDGET_30H_OPENAI_GPT54_NANO_PILOT_030_001__20260828T093323Z__823da122"
MINI_DIRECT="$PWD/benchmark-runs/BUDGET_30H_OPENAI_GPT54_MINI_PILOT_030_001__20260829T074842Z__c4257a16"
G31_DIRECT="$PWD/benchmark-runs/BUDGET_30H_GOOGLE_GEMINI31_FLASH_LITE_PILOT_030_001__20260831T100549Z__e0e9e283"

NANO_CREW="$PWD/benchmark-runs/BUDGET_30H_CREWAI_OPENAI_GPT54_NANO_OFFLINE_PILOT_030_002__20260902T072050Z__195f5483"
MINI_CREW="$PWD/benchmark-runs/BUDGET_30H_CREWAI_OPENAI_GPT54_MINI_OFFLINE_PILOT_030_002__20260902T125258Z__22232745"
G31_CREW="$PWD/benchmark-runs/BUDGET_30H_CREWAI_GOOGLE_GEMINI31_FLASH_LITE_OFFLINE_PILOT_030_002__20260902T075142Z__d4383f53"
G37_DIRECT="$PWD/benchmark-runs/BUDGET_30H_GOOGLE_NATIVE_GEMINI37_FLASH_PILOT_030_001__20260901T162154Z__db1155ac"
G37_CREW="$PWD/benchmark-runs/BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_PILOT_030_003__20260905T134533Z__f345115d"

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py compare \
  --run "gpt54_nano_direct=$NANO_DIRECT" \
  --run "gpt54_nano_crewai=$NANO_CREW" \
  --run "gpt54_mini_direct=$MINI_DIRECT" \
  --run "gpt54_mini_crewai=$MINI_CREW" \
  --run "gemini31_direct=$G31_DIRECT" \
  --run "gemini31_crewai=$G31_CREW" \
  --run "gemini37_direct_native=$G37_DIRECT" \
  --run "gemini37_crewai=$G37_CREW" \
  --labels benchmarks/secure_scoring/openai_pilot_030_v1/labels.jsonl \
  --output-dir benchmark-runs/comparisons/FULL_EIGHT_ARM_PILOT_030_001
```

Powstały też cztery osobne eksporty
`{GPT54_NANO,GPT54_MINI,GEMINI31,GEMINI37}_DIRECT_VS_CREWAI_PILOT_030_001`.
Dzięki temu pary OpenAI mają typ `system_bundle_delta`, Gemini 3.1
`cross_api_system_bundle_delta`, a Gemini 3.7
`token_cap_adjusted_system_bundle_delta`.

`compare` akceptuje zakończony manifest `completed_with_failures`, aby jeden
techniczny błąd Direct Gemini 3.7 pozostał w mianowniku zamiast wykluczyć cały
run; nadal odrzuca `invalid`, `security_fail` i niezakończone runy. Raport oraz
`runs.csv` pokazują 29/30 sukcesów i jeden technical failure tego ramienia.
Eksport zachowuje też jawne oznaczenie, że Gemini 3.7 CrewAI miało output cap
1000, podczas gdy pozostałe ramiona miały 500; nie jest to porównanie
apples-to-apples. Komenda działa offline i nie generuje kosztu. Nie nadpisuj
istniejącego eksportu; przy świadomym odtworzeniu użyj nowego output ID.

## Zasada zatrzymania

Po każdym smoke i pilocie usuń klucz ze środowiska, przeczytaj raport i sprawdź
dashboard providera. Kolejnej kampanii nie uruchamiaj, dopóki bieżąca nie ma
wyjaśnionych: statusu, liczby calli, usage, kosztu, błędów i zdarzeń security.
To ogranicza zarówno koszt, jak i ryzyko powielenia problemu technicznego na 30
wiadomościach.
