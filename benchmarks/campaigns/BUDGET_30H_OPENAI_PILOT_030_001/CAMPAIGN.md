# BUDGET_30H_OPENAI_PILOT_030_001

Status: `ENGINEERING_PILOT`. Jest to pierwszy pomiar jakości OpenAI Direct na
zamrożonym, syntetycznym zbiorze `n=30`; nadal nie jest to ranking modeli ani
dowód gotowości produkcyjnej.

## Zamrożony zakres

- 30 wiadomości e-mail: 15 malicious i 15 benign, po jednej próbie na rekord;
- wyłącznie dane syntetyczne i domeny `.test`, `.invalid` lub `.example`;
- SMS, QR i niewidoczny załącznik są poza tym tekstowym pilotem;
- runner dostaje tylko widoczną treść oraz sygnały wyliczone przez aktualny kod
  produktu; labele, scenariusze i uzasadnienia są w osobnym bundle scoringowym;
- OpenAI Chat Completions, snapshot `gpt-4o-mini-2024-07-18`, prompt i polityka
  decyzji identyczne jak w udanym smoke;
- `R=1`, concurrency `1`, maksymalnie jeden retry wyłącznie dla błędu
  retryowalnego;
- twarde limity: 60 outbound attempts, 7200 sekund i 0,25 USD;
- `store=false`, brak tools, brak URL fetch i brak conversation state.

## Interpretacja

Scorer liczy confusion matrix oraz opisowe precision, recall, F1, FPR, FNR,
specificity i balanced accuracy. Błędy techniczne pozostają w mianownikach jako
bieżące produktowe `technical_failure_action=allow`. Dla `n=30` raportuje się
medianę i IQR latency, ale nie p95/p99. Wilson 95% jest przedziałem opisowym, a
nie dowodem spełnienia progu produkcyjnego.

Status `PILOT_READY_FOR_SELECTION` pozwala przejść do kolejnego zamrożonego
etapu. `PILOT_HOLD`, `SECURITY_FAIL` albo `INVALID` wymagają analizy artefaktów;
nie wolno usuwać trudnych rekordów ani powtarzać runu tylko po to, aby poprawić
wynik.

## Uruchomienie

Najpierw testy, validate i dry-run bez API. Live run wymaga jawnych flag
`--live` oraz `--confirm-campaign BUDGET_30H_OPENAI_PILOT_030_001`. Dokładne
polecenia i lokalizacje raportów są w `benchmarks/README.md`.
