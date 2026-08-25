# BUDGET_30H_OPENAI_SMOKE_001

Status: `ENGINEERING_PILOT`. Ten etap sprawdza przewód pomiarowy, a nie skuteczność modelu i nie tworzy rankingu.

## Zamrożony zakres

- 5 w pełni syntetycznych wiadomości: phishing credential, BEC, benign, hard benign i prompt injection;
- jeden adapter Direct zgodny z obecną ścieżką produktu: OpenAI Chat Completions;
- przypięty model `gpt-4o-mini-2024-07-18`;
- prompt v1 skopiowany z bieżącego Direct flow;
- `R=1`, concurrency `1`, maksymalnie jeden retry na próbkę;
- maksymalnie 10 outbound attempts, 15 minut i 0,05 USD;
- `store=false`, bez tools, bez live URL fetch, bez conversation/state;
- runner nie zna ścieżki ani zawartości scoring bundle.

## Kryterium ukończenia

Run musi utworzyć dokładnie pięć terminalnych `ResultRecord`, append-only `attempts.jsonl`, ledger budżetu i manifest. Scorer sprawdza zgodność action mapping, kompletność, błędy, retry, tokeny, koszt, latency i zdarzenia bezpieczeństwa. Dla pięciu rekordów nie wolno publikować precision, recall, F1, FPR ani p95/p99.

## Następna bramka

Po poprawnym live smoke: ręczna inspekcja pięciu wyników, następnie pilot 20–30 wiadomości. Crew offline i frozen tools są osobnym kolejnym etapem; aktualny Crew nie ma jeszcze jawnego model injection i nie może być uczciwie porównywany z Direct.
