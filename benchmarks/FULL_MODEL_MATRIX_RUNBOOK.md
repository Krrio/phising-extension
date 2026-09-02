# Pełna macierz benchmarków Direct i CrewAI

Stan planu: 2026-09-02. Ten dokument jest operacyjną instrukcją dla czterech
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
| GPT-5.4 Nano | wykonane: `READINESS_PASS → PILOT_HOLD` | v1: auth fail `_001`, truncation fail `_002`; wspólny concise-v2 `_003` gotowy; pilot v2 zablokowany |
| GPT-5.4 Mini | wykonane: `READINESS_PASS → PILOT_HOLD` | v1 zamknięty bez live runu; concise-v2 smoke gotowy; pilot v2 zablokowany |
| Gemini 3.1 Flash-Lite | wykonane: `READINESS_PASS → PILOT_HOLD` | v1 zamknięty bez live runu; concise-v2 smoke gotowy; pilot v2 zablokowany |
| Gemini 3.7 Flash | native Direct wykonany: `READINESS_PASS → PILOT_HOLD` (29/30 success) | v1 zamknięty bez live runu; concise-v2 smoke gotowy; pilot v2 zablokowany |

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
długości raportów pośrednich, została wykonana przed pilotami i obowiązuje
identycznie Nano, Mini, Gemini 3.1 oraz Gemini 3.7. Limit 500, dane, schema,
decision policy, trzy role, zero retry i pozostałe zabezpieczenia nie zmieniają
się. Po smoke Nano v2 nie wolno już stroić tego protokołu między modelami.

## Co jest identyczne

We wszystkich ośmiu ramionach porównania zamrożone są:

- dokładnie te same 5 rekordów smoke i te same 30 rekordów pilota, w tej samej
  kolejności i z tymi samymi anonimowymi UUID;
- ten sam strict response schema;
- ta sama decision policy mapująca wynik na `allow`, `warn` albo `hide`;
- ten sam oddzielny scoring bundle i te same bramki jakości;
- te same mianowniki: timeout, 429, 5xx, refusal i invalid output nie znikają z
  wyniku;
- `concurrency=1`, maksymalnie 500 output tokens, syntetyczne dane i domeny
  zarezerwowane;
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
| Gemini 3.7 Native Direct | 5 / 0,05 USD | 30 / 0,65 USD | 0,287302 USD |
| CrewAI + GPT-5.4 Nano | 15 / 0,10 USD | 90 / 0,50 USD | 0,233779 USD |
| CrewAI + GPT-5.4 Mini | 15 / 0,25 USD | 90 / 1,00 USD | 0,866828 USD |
| CrewAI + Gemini 3.1 | 15 / 0,10 USD | 90 / 0,50 USD | 0,290597 USD |
| CrewAI + Gemini 3.7 | 15 / 0,25 USD | 90 / 1,00 USD | 0,831391 USD |
| **Łącznie** | **65 / 0,75 USD** | **390 / 3,65 USD** | **2,509897 USD** |

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
`2,4883375 USD`.

Pilot Native Direct zakończył się 29/30 `success` i jednym
`incomplete_output` (`case_038`, finish reason `length`) bez retry i bez braków
usage. Opisowa confusion matrix po zastosowaniu zamrożonej akcji awaryjnej to
`TP=15, FP=0, TN=15, FN=0`, ale bramka `technical_failures_zero` wymusiła
`PILOT_HOLD`. Observed cost wyniósł `0,0735135 USD`, a mediana latency sukcesów
`9903,467 ms`. Po zastąpieniu rezerwy pilota kosztem zaobserwowanym łączny znany
lub konserwatywnie zarezerwowany koszt całej serii wynosi `2,31591325 USD`.

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
kosztem observed łączny znany lub konserwatywnie zarezerwowany koszt serii
wynosi `2,1503934 USD`.

Hard cap to awaryjny sufit, a nie prognoza rachunku. Konserwatywna rezerwa
zakłada skrajnie niekorzystny token count i maksymalny output każdego calla;
observed cost z usage i billing providera są właściwym wynikiem kosztowym.
Pozostały twardy sufit aktywnych kampanii wynosi 3,10 USD. Suma skonfigurowanych
ceilingów wraz z zakończonymi kampaniami oraz dodatkowymi smoke Nano `_001` i
`_002` wynosi 4,65 USD. Faktyczny observed cost pięciu zakończonych kampanii z
kompletnym usage to `0,14024555 USD`; nieudane próby bez usage zachowują osobne
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
| CrewAI + Gemini 3.7 | `BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_SMOKE_002` | `BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_PILOT_030_002` |

Gemini 3.7 Native Direct smoke `_002` i pilot są zakończone oraz zamknięte przed
ponowieniem. Nano CrewAI `_SMOKE_001` i `_SMOKE_002` są zamkniętymi wynikami
negatywnymi v1, a `_SMOKE_003` jest zamkniętym `READINESS_PASS` concise-v2.
Pilot Nano v2 jest zamkniętym `PILOT_HOLD`; nie wolno go stroić ani ponawiać na
tych samych 30 przypadkach. Wszystkie nierunowane ID v1 Mini/Gemini także są
programowo zamknięte, aby nie mieszać protokołów. Pozostałe trzy smoke
concise-v2 są aktywne, a ich piloty pozostają `LIVE_BLOCKED`, dopóki własny
smoke nie uzyska audytowanego `READINESS_PASS`.

## Etap 0 — czysty commit i kontrola bez kosztu

Najpierw zatwierdź i wypchnij implementację. `git status --short` powinien nic
nie zwrócić; dzięki temu każdy run zapisze `dirty=false` i jednoznaczny commit.
Klucze API nie mogą znajdować się w pliku, commicie ani historii terminala.

```bash
env -u OPENAI_API_KEY -u GEMINI_API_KEY PYTHONWARNINGS=ignore \
  backend/guardian/.venv/bin/python -m unittest discover -s benchmarks/tests -q

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py validate \
  --campaign benchmarks/campaigns/BUDGET_30H_CREWAI_GOOGLE_GEMINI31_FLASH_LITE_OFFLINE_SMOKE_002/runtime_config.json

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py run \
  --campaign benchmarks/campaigns/BUDGET_30H_CREWAI_GOOGLE_GEMINI31_FLASH_LITE_OFFLINE_SMOKE_002/runtime_config.json
```

Ostatnia komenda jest dry-runem. Bez `--live` nie wykonuje requestu.

## Etap 1 — pozostałe smoke pojedynczo

Gemini 3.7 Native Direct jest już zakończony; nie uruchamiaj ponownie jego smoke
ani pilota. Ramię Nano CrewAI także jest zakończone i zamknięte. Następny
prerejestrowany test to smoke CrewAI + Gemini 3.1. Wczytaj klucz bez
wyświetlania go i wykonaj dokładnie jeden campaign ID:

Harness odrzuci przed requestem oczywistą zamianę kluczy (`AIza…` jako OpenAI
albo `sk-…` jako Gemini), ale operator nadal odpowiada za użycie właściwego,
aktywnego klucza i jego rotację po ekspozycji.

```bash
CAMPAIGN_ID="BUDGET_30H_CREWAI_GOOGLE_GEMINI31_FLASH_LITE_OFFLINE_SMOKE_002"
CONFIG="benchmarks/campaigns/$CAMPAIGN_ID/runtime_config.json"

unset OPENAI_API_KEY GEMINI_API_KEY
read -s GEMINI_API_KEY
echo
export GEMINI_API_KEY

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py run \
  --campaign "$CONFIG" \
  --live \
  --confirm-campaign "$CAMPAIGN_ID"

unset GEMINI_API_KEY
```

Po runie policz wynik. Nie wpisuj dosłownego placeholdera ścieżki:

```bash
RUN_DIR="$(find "$PWD/benchmark-runs" -maxdepth 1 -type d \
  -name "${CAMPAIGN_ID}__*" -print | sort | tail -n 1)"

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py score \
  --run-dir "$RUN_DIR" \
  --labels benchmarks/secure_scoring/openai_smoke_v1/labels.jsonl

cat "$RUN_DIR/scoring/report.md"
```

Kolejne smoke uruchamiaj tą samą procedurą, jeden po drugim. Dla OpenAI użyj
`read -s OPENAI_API_KEY`, `export OPENAI_API_KEY` i na końcu
`unset OPENAI_API_KEY`; dla Google analogicznie `GEMINI_API_KEY`.

Rekomendowana kolejność po CrewAI + Gemini 3.1:

1. `BUDGET_30H_CREWAI_OPENAI_GPT54_MINI_OFFLINE_SMOKE_002`;
2. `BUDGET_30H_CREWAI_GOOGLE_GEMINI37_FLASH_OFFLINE_SMOKE_002`.

Dla każdego ID ustaw:

```bash
CAMPAIGN_ID="TU_DOKŁADNY_ID_Z_LISTY"
CONFIG="benchmarks/campaigns/$CAMPAIGN_ID/runtime_config.json"
```

Do pilota można przejść tylko wtedy, gdy raport smoke pokazuje:

- `READINESS_PASS`;
- 5/5 terminalnych rekordów i `success=5`;
- 5/5 strict schema output;
- zero błędów technicznych, retry i krytycznych security events;
- dokładnie 5 attempts dla Direct albo 15 calls i 5 rozpoczętych workflows dla
  CrewAI;
- usage/koszt dla każdego calla;
- 5/5 zgodnych golden actions po ręcznej inspekcji.

`READINESS_FAIL`, `SECURITY_FAIL`, `INVALID`, brak usage albo inna liczba calli
zatrzymują dane ramię. Nie ponawiaj automatycznie tego samego campaign ID.
Podeślij `report.md`; po audycie odblokowywany jest wyłącznie odpowiadający mu
pilot.

## Etap 2 — piloty pojedynczo

Pilot Gemini 3.7 Native Direct jest zakończony i nie wolno go ponawiać. Po
przejściu kolejnego smoke CrewAI odblokuj wyłącznie odpowiadający mu pilot i
użyj jego dokładnego ID z tabeli:

```bash
CAMPAIGN_ID="TU_DOKŁADNY_ODBLOKOWANY_PILOT_ID"
CONFIG="benchmarks/campaigns/$CAMPAIGN_ID/runtime_config.json"

read -s OPENAI_API_KEY
echo
export OPENAI_API_KEY

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py run \
  --campaign "$CONFIG" \
  --live \
  --confirm-campaign "$CAMPAIGN_ID"

unset OPENAI_API_KEY
```

Dla kampanii Google zamień nazwę zmiennej klucza na `GEMINI_API_KEY`. Następnie
wykonaj scoring pilotowy:

```bash
RUN_DIR="$(find "$PWD/benchmark-runs" -maxdepth 1 -type d \
  -name "${CAMPAIGN_ID}__*" -print | sort | tail -n 1)"

backend/guardian/.venv/bin/python benchmarks/benchmark_cli.py score \
  --run-dir "$RUN_DIR" \
  --labels benchmarks/secure_scoring/openai_pilot_030_v1/labels.jsonl

cat "$RUN_DIR/scoring/report.md"
```

`PILOT_HOLD` jest pełnym, zachowywanym wynikiem jakości. Nie wolno poprawiać
promptu i powtarzać tych samych 30 przypadków, bo byłoby to strojenie na zbiorze
testowym. `INVALID`, `SECURITY_FAIL` lub błąd techniczny wymagają osobnej analizy
i nowego campaign ID.

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

Po zakończeniu i policzeniu wszystkich nowych pilotów ustaw ścieżki do pięciu
nowych runów. Trzy istniejące Direct są już gotowe:

```bash
NANO_DIRECT="$PWD/benchmark-runs/BUDGET_30H_OPENAI_GPT54_NANO_PILOT_030_001__20260828T093323Z__823da122"
MINI_DIRECT="$PWD/benchmark-runs/BUDGET_30H_OPENAI_GPT54_MINI_PILOT_030_001__20260829T074842Z__c4257a16"
G31_DIRECT="$PWD/benchmark-runs/BUDGET_30H_GOOGLE_GEMINI31_FLASH_LITE_PILOT_030_001__20260831T100549Z__e0e9e283"

NANO_CREW="TU_ŚCIEŻKA_NOWEGO_PILOTA"
MINI_CREW="TU_ŚCIEŻKA_NOWEGO_PILOTA"
G31_CREW="TU_ŚCIEŻKA_NOWEGO_PILOTA"
G37_DIRECT="TU_ŚCIEŻKA_NOWEGO_PILOTA"
G37_CREW="TU_ŚCIEŻKA_NOWEGO_PILOTA"

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

Nie uruchamiaj komendy z wartościami `TU_ŚCIEŻKA...`; najpierw wstaw rzeczywiste
katalogi zwrócone przez runner. `compare` działa offline i nie generuje kosztu.

## Zasada zatrzymania

Po każdym smoke i pilocie usuń klucz ze środowiska, przeczytaj raport i sprawdź
dashboard providera. Kolejnej kampanii nie uruchamiaj, dopóki bieżąca nie ma
wyjaśnionych: statusu, liczby calli, usage, kosztu, błędów i zdarzeń security.
To ogranicza zarówno koszt, jak i ryzyko powielenia problemu technicznego na 30
wiadomościach.
