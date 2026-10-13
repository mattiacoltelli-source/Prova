# Report accuratezza — aggiornato al 2026-10-13T23:43:15.729624+00:00

**Previsioni valutate: 130 — accuratezza complessiva: 47.7%**

## Per asset / orizzonte

| Asset | Orizzonte | N | Accuratezza |
|---|---|---|---|
| AAPL | 1d | 29 | 44.8% |
| AAPL | 1m | 8 | 37.5% |
| AAPL | 7d | 21 | 61.9% |
| AMD | 1d | 9 | 33.3% |
| AMD | 7d | 1 | 100.0% |
| MU | 1d | 4 | 50.0% |
| NVDA | 1d | 29 | 44.8% |
| NVDA | 1m | 8 | 75.0% |
| NVDA | 7d | 21 | 38.1% |

## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)

| Predetto \ Reale | UP | DOWN | FLAT |
|---|---|---|---|
| UP | 13 | 10 | 18 |
| DOWN | 0 | 1 | 0 |
| FLAT | 25 | 15 | 48 |

## Calibrazione (confidence dichiarata vs accuratezza reale)

| Fascia confidence | N | Accuratezza |
|---|---|---|
| bassa (0-49) | 64 | 50.0% |
| media (50-74) | 56 | 44.6% |
| alta (75-100) | 10 | 50.0% |

## Probabilità (Brier Score, Log Loss)

- Brier Score: **0.6112** (n=66; range 0-2, più basso è meglio)
- Log Loss: **1.0115** (n=66; più basso è meglio)
- Riferimento "non informativo" (probabilità sempre 33.3%/33.3%/33.3%): Brier 0.667, Log Loss 1.099 — l'agente deve fare meglio di questo per aggiungere valore.
- 64 previsioni valutate sono precedenti all'introduzione delle probabilità (2026-09-18) ed escluse da queste due metriche.

## Accuratezza per versione del prompt

Cambiare il prompt cambia l'esperimento: un unico numero di accuratezza
sopra versioni diverse nasconderebbe l'effetto del cambio. Le versioni sono
descritte in `src/config.py` (`PROMPT_VERSION`).

| Versione | N | Accuratezza |
|---|---|---|
| v1 | 60 | 45.0% |
| v2 | 70 | 50.0% |

## Confronto con baseline naive

- Random (3 classi equiprobabili): 33.3%
- Persistenza (ripete l'ultimo esito reale osservato): 53.7% (n=121)
- Classe più frequente (frequenza storica su decenni di prezzi, pesata sullo stesso mix asset/orizzonte): 45.0% (n=130)
- **Agente AI: 47.7%**

> La baseline "classe più frequente" è la più dura delle tre: è
> l'accuratezza di chi prevede sempre la stessa classe senza
> guardare né prezzi né notizie. Batterla è il minimo perché
> l'agente stia aggiungendo qualcosa. Dettaglio per asset e
> orizzonte in `data/baseline.json` (rigenerabile con
> `python -m src.baseline_run`).

