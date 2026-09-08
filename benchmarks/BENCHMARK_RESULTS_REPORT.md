# Raport wyników benchmarku Guardian AI

## Porównanie modeli Direct i CrewAI Offline

| Pole | Wartość |
| --- | --- |
| Zakres | GPT-5.4 Nano, GPT-5.4 Mini, Gemini 3.1 Flash-Lite i Gemini 3.7 Flash |
| Architektury | Direct oraz CrewAI Offline dla każdego modelu |
| Eksport źródłowy | `FULL_EIGHT_ARM_PILOT_030_001` |
| Wielkość badania | 8 wariantów × 30 wiadomości = 240 ocen |
| Zbiór na wariant | 15 malicious + 15 benign; te same przypadki dla każdego wariantu |
| Etap | `ENGINEERING_PILOT` |
| Status ramion | 8 × `PILOT_HOLD` |
| Status porównania | `DESCRIPTIVE_ONLY`, `INCONCLUSIVE`, `eligible_for_ranking=false` |
| Data eksportu | 5 września 2026, 14:18:43 UTC |
| Data raportu | 6 września 2026 |

> **Decyzja wykonawcza:** na podstawie obecnego pilota najbardziej
> uzasadnionym kandydatem do następnego, niezależnego etapu testów jest
> **GPT-5.4 Mini Direct**. Jest to rekomendacja screeningowa, a nie potwierdzenie
> gotowości produkcyjnej ani dowód statystycznej przewagi.

## 1. Podsumowanie zarządcze

Benchmark wskazuje pięć najważniejszych wniosków:

1. Wszystkie warianty oznaczyły wszystkie 15 wiadomości malicious co najmniej
   akcją `warn`. W tym zbiorze nie wystąpił żaden FN, dlatego głównym czynnikiem
   różnicującym systemy była liczba fałszywych alarmów na wiadomościach benign.
2. **GPT-5.4 Mini Direct zapewnił najlepszy obserwowany kompromis jakości,
   kompletności technicznej, szybkości i kosztu:** F1 `0,9677`, FPR `6,67%`,
   30/30 sukcesów, brak błędów technicznych, mediana `1,291 s` i koszt
   `0,001036 USD` na wiadomość.
3. **Gemini 3.7 Direct uzyskał najlepsze nominalne metryki** (`F1=1,0`,
   `FPR=0%`), ale zwrócił tylko 29/30 prawidłowych odpowiedzi. Jeden przypadek
   `incomplete_output` został zgodnie z zamrożoną polityką zamapowany na
   `allow`; ponieważ wiadomość była benign, wynik system action został policzony
   jako TN. Wyniku nie należy opisywać jako 30 poprawnych odpowiedzi modelu.
4. **CrewAI nie wykazał konsekwentnej przewagi jakościowej.** Poprawił wynik o
   jeden przypadek dla Nano i Gemini 3.1, a pogorszył o jeden przypadek dla
   Mini i Gemini 3.7. Każdy wariant CrewAI wykonywał trzy wywołania na
   wiadomość i był od `2,09×` do `3,93×` droższy od odpowiadającego mu Direct.
5. Najczęstszy wspólny problem stanowił `case_032` — bezpieczne zgłoszenie
   phishingu przesłane do IT. Siedem z ośmiu wariantów potraktowało cytowaną
   treść jako aktywny phishing i zastosowało `hide`.

Żaden wariant nie przeszedł wszystkich zamrożonych bramek pilota. Wyniki mogą
posłużyć do wskazania kandydatów do niezależnego etapu potwierdzającego, ale nie
stanowią formalnego rankingu ani podstawy do ogłoszenia zwycięzcy
produkcyjnego.

## 2. Cel i zakres badania

Celem testu było porównanie czterech modeli w dwóch sposobach wykonania:

- **Direct** — jedno bezpośrednie wywołanie modelu na wiadomość;
- **CrewAI Offline** — trzy sekwencyjne role i trzy wywołania modelu na
  wiadomość, z zamrożonym lokalnym evidence i bez narzędzi sieciowych.

Każde ramię otrzymało ten sam zestaw 30 wiadomości. Zbiór był celowo
zbilansowany oraz wzbogacony o przypadki trudne:

- 15 wiadomości malicious i 15 benign;
- 12 przypadków `typical`, 11 `edge` i 7 `adversarial`;
- 28 wiadomości w języku polskim i 2 w języku angielskim;
- 2 zamrożone próby bezpieczeństwa typu prompt injection.

Porównanie było sparowane: wynik każdego wariantu można zestawić na poziomie
tej samej wiadomości. Wspólne pozostały hashe datasetu, etykiet, polityki
decyzyjnej i schemy odpowiedzi. Różniły się natomiast modele, adaptery,
profile requestów, prompty architektur oraz liczba wywołań.

Każdy run miał `git_dirty=false`, ale osiem ramion wykonano na różnych
commitach. Wspólne hashe potwierdzają zgodność datasetu, etykiet, polityki
decyzyjnej i schemy, lecz nie dowodzą identyczności całego harnessu i adapterów.
Jest to potencjalny confounder do zamknięcia przez sklasyfikowanie różnic między
commitami przed formalnym etapem porównawczym.

## 3. Jak interpretować metryki

W benchmarku akcje `warn` i `hide` są klasyfikowane jako wynik pozytywny, a
`allow` jako wynik negatywny. Oznacza to, że:

- TP — phishing otrzymał `warn` albo `hide`;
- FN — phishing otrzymał `allow`;
- FP — bezpieczna wiadomość otrzymała `warn` albo `hide`;
- TN — bezpieczna wiadomość otrzymała `allow`.

Najważniejsze metryki to:

- **recall** — udział wykrytych wiadomości malicious; w systemie ochronnym
  przeoczenie phishingu jest błędem o wysokim koszcie;
- **FPR** — udział bezpiecznych wiadomości, które wywołały ostrzeżenie lub
  blokadę; wysoki FPR prowadzi do alert fatigue i utraty zaufania użytkownika;
- **F1** — kompromis precision i recall, ale zależny od sztucznego rozkładu klas
  50/50 w tym pilocie;
- **golden action match** — zgodność z dopuszczalną akcją `allow|warn|hide`;
  nie jest tym samym co binarna poprawność;
- **technical failure** — brak prawidłowego wyniku modelu, zawsze raportowany
  oddzielnie i pozostawiany w mianowniku.

Koszt w raporcie jest kosztem zaobserwowanym na podstawie usage zwróconego
przez providera. Nie należy utożsamiać go z konserwatywną rezerwą ledgera ani z
gwarantowaną przyszłą ceną produkcyjną. Latency jest czasem end-to-end przy
`concurrency=1` i dla rekordów zakończonych sukcesem.

## 4. Wyniki zbiorcze

| Wariant | Sukcesy | TP / FP / TN / FN | Precision | Recall | F1 | FPR | Golden | Koszt observed / próbę | Mediana latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| GPT-5.4 Nano Direct | 30/30 | 15 / 11 / 4 / 0 | 0,5769 | 1,0000 | 0,7317 | 73,33% | 24/30 | 0,000322 USD | 1,315 s |
| GPT-5.4 Nano CrewAI | 30/30 | 15 / 10 / 5 / 0 | 0,6000 | 1,0000 | 0,7500 | 66,67% | 26/30 | 0,001259 USD | 4,920 s |
| **GPT-5.4 Mini Direct** | **30/30** | **15 / 1 / 14 / 0** | **0,9375** | **1,0000** | **0,9677** | **6,67%** | **29/30** | **0,001036 USD** | **1,291 s** |
| GPT-5.4 Mini CrewAI | 30/30 | 15 / 2 / 13 / 0 | 0,8824 | 1,0000 | 0,9375 | 13,33% | 29/30 | 0,004071 USD | 4,095 s |
| Gemini 3.1 Flash-Lite Direct | 30/30 | 15 / 3 / 12 / 0 | 0,8333 | 1,0000 | 0,9091 | 20,00% | 28/30 | 0,000726 USD | 3,280 s |
| Gemini 3.1 Flash-Lite CrewAI | 30/30 | 15 / 2 / 13 / 0 | 0,8824 | 1,0000 | 0,9375 | 13,33% | 29/30 | 0,001516 USD | 3,583 s |
| Gemini 3.7 Flash Direct | 29/30 + 1 błąd | 15 / 0 / 15 / 0¹ | 1,0000 | 1,0000 | 1,0000¹ | 0,00%¹ | 30/30¹ | 0,002450 USD | 9,903 s² |
| Gemini 3.7 Flash CrewAI | 30/30 | 15 / 1 / 14 / 0 | 0,9375 | 1,0000 | 0,9677 | 6,67% | 29/30 | 0,006282 USD | 10,086 s |

¹ Wynik obejmuje benign `case_038`, dla którego model nie zwrócił kompletnej
odpowiedzi. Zamrożona akcja awaryjna `allow` została policzona jako TN i golden
match. Nie jest to poprawna odpowiedź klasyfikacyjna modelu.

² Mediana Gemini 3.7 Direct jest liczona tylko dla 29 sukcesów.

Łączny zaobserwowany koszt ośmiu pilotów wyniósł `0,5298771 USD`.
Konserwatywna suma observed/reserved w ledgerach wyniosła `2,97064305 USD` i
nie jest traktowana jako rzeczywisty rachunek.

## 5. Interpretacja wykresów

### 5.1. F1 — jakość ogólna

![F1 według wariantu](../benchmark-runs/comparisons/FULL_EIGHT_ARM_PILOT_030_001/charts/01_f1.png)

Wykres tworzy trzy wyraźne grupy:

- nominalnie najwyżej znajduje się Gemini 3.7 Direct z `F1=1,0`, ale czerwone
  oznaczenie informuje o błędzie technicznym;
- GPT-5.4 Mini Direct i Gemini 3.7 CrewAI uzyskały identyczne, kompletne
  technicznie `F1=0,9677`;
- oba warianty Nano pozostają wyraźnie niżej (`0,7317–0,7500`).

Ponieważ każdy wariant miał `recall=1,0`, różnice F1 powstały wyłącznie wskutek
fałszywych alarmów. W tym pilocie wykres F1 jest więc przede wszystkim obrazem
zdolności systemu do odróżnienia phishingu od bezpiecznych wiadomości
zawierających podobne sygnały.

### 5.2. False Positive Rate — obciążenie użytkownika

![FPR według wariantu](../benchmark-runs/comparisons/FULL_EIGHT_ARM_PILOT_030_001/charts/02_fpr.png)

FPR jest najbardziej praktyczną osią różnicującą:

- Gemini 3.7 Direct: nominalnie `0/15`, lecz z jednym błędem technicznym na
  wiadomości benign;
- GPT-5.4 Mini Direct i Gemini 3.7 CrewAI: `1/15`, czyli `6,67%`;
- GPT-5.4 Mini CrewAI i Gemini 3.1 CrewAI: `2/15`, czyli `13,33%`;
- Gemini 3.1 Direct: `3/15`, czyli `20%`;
- Nano Direct i CrewAI: odpowiednio `11/15` i `10/15`, czyli `73,33%` i
  `66,67%`.

Warianty Nano ostrzegały lub blokowały większość bezpiecznych wiadomości. Taki
profil grozi dużym alert fatigue i przy obecnych kryteriach uzasadnia
niepromowanie Nano do następnego etapu, mimo niskiego kosztu.

Jeden przypadek benign zmienia FPR aż o `6,67 p.p.`. Przedziały Wilsona 95% są
przez to szerokie:

| Obserwowany FPR | Wilson 95% CI |
| ---: | ---: |
| 0/15 = 0,00% | 0,00–20,39% |
| 1/15 = 6,67% | 1,19–29,82% |
| 2/15 = 13,33% | 3,74–37,88% |
| 3/15 = 20,00% | 7,05–45,19% |

Wynik `0/15` nie dowodzi zatem rzeczywistego FPR równego zero.

### 5.3. Koszt

![Koszt observed na wiadomość](../benchmark-runs/comparisons/FULL_EIGHT_ARM_PILOT_030_001/charts/03_cost_per_message.png)

Najtańszy był GPT-5.4 Nano Direct, ale jego niski koszt łączy się z
nieakceptowalnym FPR. W obszarze wariantów wysokiej jakości koszt wygląda
następująco:

- GPT-5.4 Mini Direct: `0,001036 USD` na wiadomość;
- Gemini 3.7 Direct: `0,002450 USD` na wiadomość;
- GPT-5.4 Mini CrewAI: `0,004071 USD` na wiadomość;
- Gemini 3.7 CrewAI: `0,006282 USD` na wiadomość.

Przy prostym przeskalowaniu obserwowanego usage koszt 1000 podjętych prób
analizy wiadomości wyniósłby około:

| Wariant | Observed koszt / 1000 prób¹ |
| --- | ---: |
| GPT-5.4 Nano Direct | 0,322 USD |
| Gemini 3.1 Direct | 0,726 USD |
| GPT-5.4 Mini Direct | 1,036 USD |
| GPT-5.4 Nano CrewAI | 1,259 USD |
| Gemini 3.1 CrewAI | 1,516 USD |
| Gemini 3.7 Direct | 2,450 USD |
| GPT-5.4 Mini CrewAI | 4,071 USD |
| Gemini 3.7 CrewAI | 6,282 USD |

¹ To liniowa projekcja wartości observed z pilota, nie prognoza faktury ani
gwarancja przyszłych cen. Mianownikiem są wszystkie podjęte próby, dlatego dla
Gemini 3.7 Direct uwzględnia także koszt rekordu zakończonego technicznie
niekompletnym wynikiem.

Wyższy koszt CrewAI wiąże się między innymi z 90 wywołaniami dla 30 wiadomości,
podczas gdy Direct wykonuje 30, oraz z innym profilem tokenów, promptów i cache.
Zwiększony koszt nie przełożył się na regularną poprawę jakości.

### 5.4. Latency

![Mediana latency](../benchmark-runs/comparisons/FULL_EIGHT_ARM_PILOT_030_001/charts/04_latency_median.png)

GPT-5.4 Mini Direct był najszybszym wariantem w całej macierzy:

- mediana `1,291 s`;
- IQR `0,105 s`;
- maksimum `1,598 s`.

GPT-5.4 Nano Direct miał zbliżoną medianę `1,315 s`, ale dużo gorszą jakość.
Gemini 3.7 Direct i CrewAI były najwolniejsze, z medianami odpowiednio
`9,903 s` i `10,086 s`. Gemini 3.7 Direct miał także bardzo długi ogon:
IQR `8,293 s` i maksimum `51,433 s`.

Dla GPT koszt wieloetapowej orkiestracji jest widoczny bezpośrednio: CrewAI
zwiększył medianę `3,74×` dla Nano oraz `3,17×` dla Mini. Dla Gemini różnica
median Direct–CrewAI była mniejsza, jednak oba warianty Gemini 3.7 pozostawały
operacyjnie wolne.

### 5.5. Relacja koszt–jakość

![Koszt a jakość](../benchmark-runs/comparisons/FULL_EIGHT_ARM_PILOT_030_001/charts/05_cost_quality_pareto.png)

Punkty Direct tworzą naturalną ścieżkę koszt–jakość: Nano → Gemini 3.1 → Mini
→ Gemini 3.7. **Wizualnie i według przyjętych kryteriów GPT-5.4 Mini Direct
jest kandydatem na „kolano” tej krzywej:** daje prawie maksymalną obserwowaną
jakość bez gwałtownego wzrostu kosztu i latency. Nie jest to wynik osobnego,
formalnego algorytmu wyznaczania punktu kolanowego.

Przejście z Gemini 3.1 Direct do GPT-5.4 Mini Direct oznaczało:

- wzrost F1 z `0,9091` do `0,9677`;
- spadek FP z 3 do 1;
- skrócenie mediany z `3,280 s` do `1,291 s`;
- wzrost kosztu na wiadomość o około `43%`.

Przejście dalej do Gemini 3.7 Direct dawało nominalnie tylko `+0,0323` F1 i
jeden FP mniej, ale wiązało się z kosztem `2,37×`, medianą latency `7,67×`
oraz jednym błędem technicznym względem GPT-5.4 Mini Direct.

Gemini 3.7 CrewAI uzyskał tę samą macierz błędów co GPT-5.4 Mini Direct, ale
był `6,07×` droższy i `7,82×` wolniejszy medianowo. Z perspektywy samej
klasyfikacji phishingu nie uzasadnia to wyboru bardziej złożonego wariantu.

### 5.6. Heatmapa przypadków

![Heatmapa przypadków](../benchmark-runs/comparisons/FULL_EIGHT_ARM_PILOT_030_001/charts/06_case_heatmap.png)

Prawa połowa heatmapy jest jednolicie oznaczona jako TP: wszystkie 15
wiadomości malicious zostało wykrytych przez wszystkie warianty. Różnice
koncentrują się po stronie benign:

- `case_032`, `forwarded_phishing_report_to_it`: FP i akcja `hide` w 7/8
  wariantów; tylko Gemini 3.7 Direct zwrócił poprawne `allow`;
- `case_037`, `newsletter_with_click_tracking`: FP w 4/8 wariantów;
- `case_038`, `event_registration_via_platform`: FP w 4/8 wariantów, a Gemini
  3.7 Direct zakończył ten przypadek statusem `incomplete_output`;
- warianty Nano dodatkowo nadmiernie reagowały na typowe i brzegowe
  powiadomienia o przesyłkach, rekrutacji, resetach hasła, bankowości,
  fakturach i subskrypcjach.

Najważniejszy failure mode ma charakter kontekstowy: systemy często rozpoznają
słowa i linki typowe dla phishingu, ale nie rozumieją, że użytkownik jedynie
cytuje atak lub zgłasza go zespołowi IT.

Binary correctness i golden action nie są identyczne. Przykładowo `warn` na
wiadomości benign jest binarnym FP, ale w wybranych przypadkach był dozwoloną
akcją ostrożności. Dlatego GPT-5.4 Nano Direct miał 11 binarnych FP, lecz 6
golden-action mismatches. W produkcie należy analizować zarówno obciążenie
alertami, jak i surowość podjętej akcji.

### 5.7. Direct kontra CrewAI

![Direct kontra CrewAI](../benchmark-runs/comparisons/FULL_EIGHT_ARM_PILOT_030_001/charts/07_direct_vs_crewai.png)

| Model | ΔF1 Crew−Direct | ΔFPR | Koszt × | Latency × | Zgodność akcji | Interpretacja |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| GPT-5.4 Nano | +0,0183 | −6,67 p.p. | 3,91× | 3,74× | 25/30 | Jedno FP mniej, lecz nadal bardzo wysoki FPR |
| GPT-5.4 Mini | −0,0302 | +6,67 p.p. | 3,93× | 3,17× | 28/30 | CrewAI pogorszył jakość i efektywność |
| Gemini 3.1 | +0,0284 | −6,67 p.p. | 2,09× | 1,09× | 29/30 | Jedno FP mniej, ale porównanie obejmuje zmianę API |
| Gemini 3.7 | −0,0323 | +6,67 p.p. | 2,56× | 1,02× | 29/30 | CrewAI usunął błąd techniczny, ale ma inny token cap |

Każda para różniła się binarnie tylko na jednym z 30 przypadków, a opisowe
McNemar exact wyniosło `p=1,0`. Tak mała liczba rozbieżności nie daje podstaw
do twierdzenia, że CrewAI trwale poprawia albo pogarsza jakość.

Porównania mają dodatkowe ograniczenia:

- dla GPT są to całe `system_bundle_delta`: CrewAI używa innych promptów,
  trzech ról i dodatkowego frozen evidence;
- Gemini 3.1 Direct korzysta z Interactions v1, a CrewAI z GenerateContent v1,
  dlatego jest to `cross_api_system_bundle_delta`;
- Gemini 3.7 CrewAI ma `max_output_tokens=1000`, a Direct `500`, dlatego jest
  to `token_cap_adjusted_system_bundle_delta`, a nie porównanie
  apples-to-apples.

Wniosek architektoniczny jest mimo to czytelny: **w tym zadaniu nie ma dowodu,
że trzyetapowa orkiestracja CrewAI zapewnia wartość proporcjonalną do kosztu i
złożoności**. Direct powinien pozostać domyślną architekturą klasyfikatora,
chyba że CrewAI dostarcza osobną funkcjonalność, której ten benchmark nie
mierzy.

## 6. Niezawodność i bezpieczeństwo

Siedem wariantów zakończyło wszystkie 30 rekordów sukcesem. Jedynym wyjątkiem
był Gemini 3.7 Direct:

- 29 odpowiedzi `success`;
- 1 `incomplete_output` dla benign `case_038`;
- 29/30 wyników zgodnych ze strict schema;
- mediana latency liczona wyłącznie dla sukcesów;
- awaryjne `allow` pozostało w mianowniku zgodnie z zamrożoną polityką.

Zamrożona reguła scoringu zadziałała zgodnie ze specyfikacją; korzystna była
klasa wiadomości, na której wystąpił błąd. Dla benign fallback `allow` został
policzony jako TN, natomiast identyczny błąd na wiadomości malicious zostałby
policzony jako FN. Dlatego czerwonego oznaczenia technicznego nie wolno
oddzielać od nominalnego `F1=1,0`.

We wszystkich ośmiu ramionach odnotowano:

- zero retry;
- zero prób o nieznanym koszcie;
- zero krytycznych zdarzeń bezpieczeństwa;
- zero akcji `allow` na dwóch security probes.

Brak incydentów w 16 ekspozycjach na dwa security probes nie dowodzi pełnego
bezpieczeństwa rozwiązania. Potwierdza jedynie, że konkretne zamrożone próby
nie zostały przepuszczone w tym pilocie.

## 7. Dlaczego wszystkie warianty mają `PILOT_HOLD`

`PILOT_HOLD` nie oznacza nieważnego runu. Oznacza, że wariant nie przeszedł co
najmniej jednej wcześniej ustalonej bramki i wymaga przeglądu przed etapem
selection.

| Wariant | Główny powód HOLD |
| --- | --- |
| GPT-5.4 Nano Direct | 11 benign `warn|hide` przy limicie 3 oraz benign `hide` przy limicie 0 |
| GPT-5.4 Nano CrewAI | 10 benign `warn|hide` przy limicie 3 oraz benign `hide` przy limicie 0 |
| GPT-5.4 Mini Direct | Jeden benign `hide` (`case_032`) przy limicie 0 |
| GPT-5.4 Mini CrewAI | Jeden benign `hide` (`case_032`) przy limicie 0 |
| Gemini 3.1 Direct | Dwa benign `hide` przy limicie 0 |
| Gemini 3.1 CrewAI | Jeden benign `hide` (`case_032`) przy limicie 0 |
| Gemini 3.7 Direct | Jeden błąd techniczny |
| Gemini 3.7 CrewAI | Jeden benign `hide` (`case_032`) przy limicie 0 |

Próg zera benign `hide` jest rygorystyczną bramką tego pilota, a nie
zatwierdzonym progiem produkcyjnym. Wyników nie należy poprawiać przez strojenie
na obecnych 30 wiadomościach ani przez powtarzanie zakończonych kampanii.

## 8. Ocena poszczególnych wariantów

### GPT-5.4 Mini Direct — rekomendowany kandydat

Najlepszy praktyczny balans w tym pilocie:

- 30/30 sukcesów i zero błędów technicznych;
- 15 TP, 1 FP, 14 TN i 0 FN;
- `F1=0,9677`, `FPR=6,67%`, golden match 29/30;
- najniższa mediana latency w całej macierzy: `1,291 s`;
- umiarkowany koszt: `0,001036 USD` na wiadomość.

Względem Gemini 3.1 Direct Mini dawał wyższą jakość, dwa FP mniej i był `2,54×`
szybszy, przy koszcie wyższym o około `43%`. Względem Gemini 3.7 Direct był
`2,37×` tańszy, `7,67×` szybszy i technicznie kompletny, przy nominalnie jednym
FP więcej.

### Gemini 3.7 Direct — challenger quality-first

Model uzyskał najlepsze obserwowane wartości system action, ale nie najlepszą
niezawodność. Jeden `incomplete_output`, mediana bliska 10 sekund i maksimum
ponad 51 sekund wykluczają obecnie rekomendację jako domyślnego wariantu.
Powinien pozostać drugim kandydatem, ponieważ wszystkie 29 kompletnych,
schema-valid odpowiedzi było binarnie poprawnych.

### Gemini 3.1 CrewAI — najlepszy kompromis wśród CrewAI

Jeżeli architektura CrewAI jest wymaganiem biznesowym, Gemini 3.1 CrewAI jest
najbardziej racjonalnym kosztowo kandydatem:

- `F1=0,9375`, `FPR=13,33%`, 30/30 sukcesów;
- koszt `0,001516 USD` na wiadomość;
- mediana `3,583 s`.

Ma tę samą macierz błędów co GPT-5.4 Mini CrewAI, ale zaobserwowany koszt jest
około `2,68×` niższy, a mediana latency około `12,5%` krótsza. Porównanie z
Gemini 3.1 Direct pozostaje jednak zakłócone zmianą protokołu API.

### Gemini 3.7 CrewAI — najlepsza surowa jakość CrewAI

Gemini 3.7 CrewAI miał najwyższą jakość w grupie CrewAI: `F1=0,9677` i tylko
jeden FP. Jednocześnie był najdroższym wariantem (`0,006282 USD` na wiadomość)
i miał medianę `10,086 s`. Przy identycznej macierzy błędów GPT-5.4 Mini Direct
był `6,07×` tańszy i `7,82×` szybszy.

### Pozostałe warianty

- Gemini 3.1 Direct jest rozsądnym, tańszym wariantem Google, lecz trzy FP i
  mediana `3,280 s` stawiają go za GPT-5.4 Mini Direct.
- GPT-5.4 Mini CrewAI jest praktycznie zdominowany przez swój odpowiednik
  Direct: ma więcej FP, koszt `3,93×` i latency `3,17×`.
- przy obecnych kryteriach obu wariantów Nano nie należy promować do następnego
  etapu z powodu FPR przekraczającego 66%, niezależnie od atrakcyjnego kosztu
  Direct.

## 9. Wnioski końcowe

### 9.1. Co działa najlepiej

| Pytanie | Odpowiedź na podstawie obecnego pilota |
| --- | --- |
| Najlepszy praktyczny wariant ogółem | **GPT-5.4 Mini Direct** |
| Najwyższy nominalny wynik jakości | Gemini 3.7 Direct — warunkowo, z jednym błędem technicznym |
| Najlepsza jakość wśród ramion z 30/30 success | GPT-5.4 Mini Direct i Gemini 3.7 CrewAI — remis F1/FPR |
| Najlepsza surowa jakość CrewAI | Gemini 3.7 CrewAI |
| Najlepszy kompromis wśród CrewAI | Gemini 3.1 CrewAI |
| Najniższy koszt | GPT-5.4 Nano Direct — przy nieakceptowalnym FPR |
| Najniższe latency | **GPT-5.4 Mini Direct** |
| Preferowana architektura klasyfikatora | **Direct** |

**Końcowa rekomendacja:** GPT-5.4 Mini Direct powinien zostać pierwszym
finalistą do blind confirmation. Łączy najwyższą kompletną jakość praktyczną z
najniższą medianą latency, pełną kompletnością techniczną oraz kosztem wyraźnie
niższym od bardziej złożonych wariantów o podobnej jakości.

Gemini 3.7 Direct powinien zostać drugim, warunkowym finalistą. Ma największy
potencjał jakościowy, ale wymaga potwierdzenia niezawodności i charakterystyki
opóźnień. Nie należy go wdrażać na podstawie nominalnego `F1=1,0` z tego pilota.

CrewAI nie powinien być domyślnym wyborem dla samej klasyfikacji phishingu.
Wynik jakości zmieniał się tylko o jeden przypadek w każdej parze, podczas gdy
koszt zawsze wzrastał, a system wykonywał trzykrotnie więcej wywołań. Jego wybór
ma sens wyłącznie wtedy, gdy dodatkowe role realizują wartość biznesową
niewidoczną w obecnych metrykach.

### 9.2. Czego raport nie rozstrzyga

Raport nie dowodzi, że:

- którykolwiek wariant wykrywa 100% phishingu w rzeczywistym ruchu;
- obserwowane różnice są statystycznie istotne;
- którykolwiek wariant jest gotowy produkcyjnie;
- CrewAI sam w sobie poprawia albo pogarsza model;
- koszty i latency pozostaną identyczne przy innym ruchu lub obciążeniu.

Wszystkie warianty widziały tylko 15 wiadomości malicious. Dla recall 15/15
przedział Wilsona 95% wynosi `79,61–100%`. Zbiór 50/50 jest także niepodobny do
realnej skrzynki, gdzie phishing stanowi znacznie mniejszą część ruchu;
precision i F1 nie mogą być przeniesione bezpośrednio na produkcję.

## 10. Rekomendowany następny etap

1. Zachować obecny eksport i wszystkie zakończone runy bez zmian. Nie stroić
   promptów na `case_032` ani nie powtarzać kampanii na tych samych danych.
2. Wybrać dwa ramiona Direct:
   - podstawowy finalista: GPT-5.4 Mini Direct;
   - challenger: Gemini 3.7 Direct.
3. Dla Gemini 3.7 wykonać najpierw mały test techniczny na nowych danych. Każda
   zmiana adaptera, token capu lub obsługi błędów wymaga nowego campaign ID.
4. Przygotować nowy, niewidziany i zaślepiony `binary_quality_v2`. Budżetowym
   punktem startowym może być `n=100` na kandydata: dwa ramiona Direct oznaczają
   łącznie 200 wywołań modelu. Docelową liczebność i udział benign należy jednak
   zatwierdzić po analizie wymaganej precyzji przedziałów ufności lub mocy;
   `n=100` nie gwarantuje rozstrzygającego wyniku.
5. Zwiększyć reprezentację trudnych wiadomości benign, zwłaszcza:
   - zgłoszeń i forwardów phishingu do IT;
   - newsletterów z trackingiem;
   - legalnych platform eventowych i rekrutacyjnych;
   - resetów hasła, faktur i zmian danych płatniczych.
6. Przed uruchomieniem zamrozić kolejność kryteriów: najpierw FN/recall i
   technical-failure rate, następnie FPR/golden actions, a dopiero potem koszt
   i latency.
7. Raportować przedziały ufności, wyniki sparowane, p95 latency, koszt observed
   oraz wszystkie błędy techniczne. Po potwierdzeniu na danych syntetycznych
   przeprowadzić osobną walidację na zanonimizowanych wiadomościach z ruchu
   zbliżonego do docelowego.

## 11. Źródła i powtarzalność

Raport powstał wyłącznie na podstawie lokalnego, zweryfikowanego eksportu:

- [`runs.csv`](../benchmark-runs/comparisons/FULL_EIGHT_ARM_PILOT_030_001/runs.csv)
  — metryki ośmiu wariantów;
- [`cases.csv`](../benchmark-runs/comparisons/FULL_EIGHT_ARM_PILOT_030_001/cases.csv)
  — 240 wyników per-case;
- [`pairwise.csv`](../benchmark-runs/comparisons/FULL_EIGHT_ARM_PILOT_030_001/pairwise.csv)
  — 28 porównań sparowanych;
- [`comparison.json`](../benchmark-runs/comparisons/FULL_EIGHT_ARM_PILOT_030_001/comparison.json)
  — metadane, frozen invariants i hashe artefaktów;
- [`report.md`](../benchmark-runs/comparisons/FULL_EIGHT_ARM_PILOT_030_001/report.md)
  — automatyczny raport źródłowy;
- [`charts/`](../benchmark-runs/comparisons/FULL_EIGHT_ARM_PILOT_030_001/charts/)
  — wykresy PNG/SVG, workbook XLSX i manifest hashy.

Frozen invariants eksportu:

| Artefakt | SHA-256 |
| --- | --- |
| Dataset | `b23f240a0a9372d9414cd623f9717f71172a52952a57a7840bb0b83a23750a6a` |
| Dataset manifest | `8c3497002037989db549adac7f2bac57828652bcab040bb28085a533b807ba29` |
| Labels | `124a1696256f2aa6de8793a9dfac94a20798050b119547f2e0a6d2f03e37d26a` |
| Decision policy | `d8426b02b41576fe3cc38340ed88c8a63e4662707b6b7bb0343f3f41f5dffb15` |
| Response schema | `e0e2fbfc36bd14cf7e29aef12c9f6829732731cf72790f14a8b02699ececb420` |

Pliki w `benchmark-runs/` są lokalnymi, ignorowanymi przez Git artefaktami.
Tekst raportu pozostaje czytelny bez wykresów, ale do publikacji lub deployu
należy bezpiecznie dołączyć zanonimizowany pakiet wyników i obrazy, bez kluczy
API, surowych wiadomości, promptów ani reasoning.
