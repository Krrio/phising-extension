# Porównanie benchmarków phishing classifier

Status wniosku: `INCONCLUSIVE`

Typ porównania: `system_bundle_delta`. Baseline: `gpt54_nano_direct`.

To jest token-cap-adjusted system bundle dla ramienia `gemini37_crewai`: `max_output_tokens` Direct=500, CrewAI=1000. Porównanie nie jest apples-to-apples ani czystą deltą frameworka; różnice mogą obejmować wpływ odmiennego limitu outputu.

Ten sam profil requestu API: `false`; profile: `chat_completions_gpt54_reasoning_none_v1, chat_completions_gpt54_reasoning_none_v1, chat_completions_gpt54_reasoning_none_v1, chat_completions_gpt54_reasoning_none_v1, gemini_interactions_v1_structured_minimal_v1, crewai_native_gemini_generate_content_structured_minimal_v1, gemini_generate_content_v1_structured_low_v1, crewai_native_gemini_generate_content_structured_low_v1`.

| Wariant | Adapter | Model | Sukcesy | Błędy techniczne | TP | FP | TN | FN | Precision | Recall | F1 | FPR | Koszt USD | Mediana ms | Status |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| gpt54_nano_direct | chat_completions | gpt-5.4-nano-2026-03-17 | 30 | 0 | 15 | 11 | 4 | 0 | 0.576923 | 1.0 | 0.731707 | 0.733333 | 0.00964995 | 1314.905 | PILOT_HOLD |
| gpt54_nano_crewai | crewai_sequential_offline | gpt-5.4-nano-2026-03-17 | 30 | 0 | 15 | 10 | 5 | 0 | 0.6 | 1.0 | 0.75 | 0.666667 | 0.0377574 | 4920.023 | PILOT_HOLD |
| gpt54_mini_direct | chat_completions | gpt-5.4-mini-2026-03-17 | 30 | 0 | 15 | 1 | 14 | 0 | 0.9375 | 1.0 | 0.967742 | 0.066667 | 0.03107325 | 1290.606 | PILOT_HOLD |
| gpt54_mini_crewai | crewai_sequential_offline | gpt-5.4-mini-2026-03-17 | 30 | 0 | 15 | 2 | 13 | 0 | 0.882353 | 1.0 | 0.9375 | 0.133333 | 0.12213975 | 4095.286 | PILOT_HOLD |
| gemini31_direct | gemini_interactions | gemini-3.1-flash-lite | 30 | 0 | 15 | 3 | 12 | 0 | 0.833333 | 1.0 | 0.909091 | 0.2 | 0.021775 | 3279.744 | PILOT_HOLD |
| gemini31_crewai | crewai_sequential_offline | gemini-3.1-flash-lite | 30 | 0 | 15 | 2 | 13 | 0 | 0.882353 | 1.0 | 0.9375 | 0.133333 | 0.04549475 | 3583.168 | PILOT_HOLD |
| gemini37_direct_native | gemini_generate_content | gemini-3.7-flash | 29 | 1 | 15 | 0 | 15 | 0 | 1.0 | 1.0 | 1.0 | 0.0 | 0.0735135 | 9903.467 | PILOT_HOLD |
| gemini37_crewai | crewai_sequential_offline | gemini-3.7-flash | 30 | 0 | 15 | 1 | 14 | 0 | 0.9375 | 1.0 | 0.967742 | 0.066667 | 0.1884735 | 10086.1 | PILOT_HOLD |

## Różnice sparowane

- `gpt54_nano_crewai` względem `gpt54_nano_direct`: ΔF1=0.018293, ΔFPR=-0.066666, koszt ×3.912704, mediana latency ×3.741733; poprawne tylko lewy=0, tylko prawy=1, zgodność akcji=25/30.
- `gpt54_mini_direct` względem `gpt54_nano_direct`: ΔF1=0.236035, ΔFPR=-0.666666, koszt ×3.220043, mediana latency ×0.98152; poprawne tylko lewy=0, tylko prawy=10, zgodność akcji=19/30.
- `gpt54_mini_crewai` względem `gpt54_nano_direct`: ΔF1=0.205793, ΔFPR=-0.6, koszt ×12.657034, mediana latency ×3.114511; poprawne tylko lewy=0, tylko prawy=9, zgodność akcji=19/30.
- `gemini31_direct` względem `gpt54_nano_direct`: ΔF1=0.177384, ΔFPR=-0.533333, koszt ×2.256488, mediana latency ×2.494282; poprawne tylko lewy=0, tylko prawy=8, zgodność akcji=19/30.
- `gemini31_crewai` względem `gpt54_nano_direct`: ΔF1=0.205793, ΔFPR=-0.6, koszt ×4.714506, mediana latency ×2.725039; poprawne tylko lewy=0, tylko prawy=9, zgodność akcji=19/30.
- `gemini37_direct_native` względem `gpt54_nano_direct`: ΔF1=0.268293, ΔFPR=-0.733333, koszt ×7.618019, mediana latency ×7.531698; poprawne tylko lewy=0, tylko prawy=11, zgodność akcji=17/30.
- `gemini37_crewai` względem `gpt54_nano_direct`: ΔF1=0.236035, ΔFPR=-0.666666, koszt ×19.531034, mediana latency ×7.670592; poprawne tylko lewy=0, tylko prawy=10, zgodność akcji=18/30.
- `gpt54_mini_direct` względem `gpt54_nano_crewai`: ΔF1=0.217742, ΔFPR=-0.6, koszt ×0.822971, mediana latency ×0.262317; poprawne tylko lewy=0, tylko prawy=9, zgodność akcji=17/30.
- `gpt54_mini_crewai` względem `gpt54_nano_crewai`: ΔF1=0.1875, ΔFPR=-0.533334, koszt ×3.234856, mediana latency ×0.832371; poprawne tylko lewy=0, tylko prawy=8, zgodność akcji=19/30.
- `gemini31_direct` względem `gpt54_nano_crewai`: ΔF1=0.159091, ΔFPR=-0.466667, koszt ×0.576708, mediana latency ×0.666612; poprawne tylko lewy=0, tylko prawy=7, zgodność akcji=17/30.
- `gemini31_crewai` względem `gpt54_nano_crewai`: ΔF1=0.1875, ΔFPR=-0.533334, koszt ×1.204923, mediana latency ×0.728283; poprawne tylko lewy=0, tylko prawy=8, zgodność akcji=17/30.
- `gemini37_direct_native` względem `gpt54_nano_crewai`: ΔF1=0.25, ΔFPR=-0.666667, koszt ×1.946996, mediana latency ×2.01289; poprawne tylko lewy=0, tylko prawy=10, zgodność akcji=15/30.
- `gemini37_crewai` względem `gpt54_nano_crewai`: ΔF1=0.217742, ΔFPR=-0.6, koszt ×4.991697, mediana latency ×2.050011; poprawne tylko lewy=0, tylko prawy=9, zgodność akcji=16/30.
- `gpt54_mini_crewai` względem `gpt54_mini_direct`: ΔF1=-0.030242, ΔFPR=0.066666, koszt ×3.930704, mediana latency ×3.17315; poprawne tylko lewy=1, tylko prawy=0, zgodność akcji=28/30.
- `gemini31_direct` względem `gpt54_mini_direct`: ΔF1=-0.058651, ΔFPR=0.133333, koszt ×0.700764, mediana latency ×2.541243; poprawne tylko lewy=2, tylko prawy=0, zgodność akcji=27/30.
- `gemini31_crewai` względem `gpt54_mini_direct`: ΔF1=-0.030242, ΔFPR=0.066666, koszt ×1.464113, mediana latency ×2.776345; poprawne tylko lewy=1, tylko prawy=0, zgodność akcji=28/30.
- `gemini37_direct_native` względem `gpt54_mini_direct`: ΔF1=0.032258, ΔFPR=-0.066667, koszt ×2.365813, mediana latency ×7.673501; poprawne tylko lewy=0, tylko prawy=1, zgodność akcji=28/30.
- `gemini37_crewai` względem `gpt54_mini_direct`: ΔF1=0.0, ΔFPR=0.0, koszt ×6.065458, mediana latency ×7.815011; poprawne tylko lewy=0, tylko prawy=0, zgodność akcji=29/30.
- `gemini31_direct` względem `gpt54_mini_crewai`: ΔF1=-0.028409, ΔFPR=0.066667, koszt ×0.178279, mediana latency ×0.800858; poprawne tylko lewy=1, tylko prawy=0, zgodność akcji=26/30.
- `gemini31_crewai` względem `gpt54_mini_crewai`: ΔF1=0.0, ΔFPR=0.0, koszt ×0.372481, mediana latency ×0.874949; poprawne tylko lewy=1, tylko prawy=1, zgodność akcji=26/30.
- `gemini37_direct_native` względem `gpt54_mini_crewai`: ΔF1=0.0625, ΔFPR=-0.133333, koszt ×0.60188, mediana latency ×2.41826; poprawne tylko lewy=0, tylko prawy=2, zgodność akcji=26/30.
- `gemini37_crewai` względem `gpt54_mini_crewai`: ΔF1=0.030242, ΔFPR=-0.066666, koszt ×1.543097, mediana latency ×2.462856; poprawne tylko lewy=0, tylko prawy=1, zgodność akcji=27/30.
- `gemini31_crewai` względem `gemini31_direct`: ΔF1=0.028409, ΔFPR=-0.066667, koszt ×2.089311, mediana latency ×1.092515; poprawne tylko lewy=0, tylko prawy=1, zgodność akcji=29/30.
- `gemini37_direct_native` względem `gemini31_direct`: ΔF1=0.090909, ΔFPR=-0.2, koszt ×3.376051, mediana latency ×3.019585; poprawne tylko lewy=0, tylko prawy=3, zgodność akcji=27/30.
- `gemini37_crewai` względem `gemini31_direct`: ΔF1=0.058651, ΔFPR=-0.133333, koszt ×8.655499, mediana latency ×3.075271; poprawne tylko lewy=0, tylko prawy=2, zgodność akcji=28/30.
- `gemini37_direct_native` względem `gemini31_crewai`: ΔF1=0.0625, ΔFPR=-0.133333, koszt ×1.615868, mediana latency ×2.763886; poprawne tylko lewy=0, tylko prawy=2, zgodność akcji=28/30.
- `gemini37_crewai` względem `gemini31_crewai`: ΔF1=0.030242, ΔFPR=-0.066666, koszt ×4.142753, mediana latency ×2.814855; poprawne tylko lewy=0, tylko prawy=1, zgodność akcji=29/30.
- `gemini37_crewai` względem `gemini37_direct_native`: ΔF1=-0.032258, ΔFPR=0.066667, koszt ×2.563794, mediana latency ×1.018441; poprawne tylko lewy=1, tylko prawy=0, zgodność akcji=29/30.

## Jak używać plików

- `runs.csv`: jeden wiersz na model/silnik — wykresy F1, FPR, kosztu i latency.
- `cases.csv`: format long/tidy — analiza błędów według scenariusza, trudności i klasy.
- `pairwise.csv`: zgodność oraz różnice dwóch wariantów na dokładnie tych samych próbkach.
- `comparison.json`: pełny eksport maszynowy wraz z hashami źródeł.

## Ograniczenie interpretacji

Porównanie ma charakter opisowy: n=30, dane syntetyczne i challenge-enriched. Nie dowodzi przewagi modelu, frameworka ani gotowości produkcyjnej. Cross-provider Direct obejmuje model oraz natywny protokół providera; różne prompty lub architektury oznaczają porównanie całych system bundles, a nie izolowanego wpływu jednego komponentu. Wartość McNemara jest wyłącznie opisowa i nie zmienia statusu `INCONCLUSIVE`.
