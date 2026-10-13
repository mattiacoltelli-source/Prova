# Report accuratezza — aggiornato al 2026-10-13T02:00:19.308889+00:00

**Previsioni valutate: 124 — accuratezza complessiva: 48.4%**

## Per asset / orizzonte

| Asset | Orizzonte | N | Accuratezza |
|---|---|---|---|
| AAPL | 1d | 28 | 42.9% |
| AAPL | 1m | 8 | 37.5% |
| AAPL | 7d | 20 | 65.0% |
| AMD | 1d | 8 | 37.5% |
| AMD | 7d | 1 | 100.0% |
| MU | 1d | 3 | 33.3% |
| NVDA | 1d | 28 | 46.4% |
| NVDA | 1m | 8 | 75.0% |
| NVDA | 7d | 20 | 40.0% |

## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)

| Predetto \ Reale | UP | DOWN | FLAT |
|---|---|---|---|
| UP | 13 | 10 | 18 |
| DOWN | 0 | 0 | 0 |
| FLAT | 22 | 14 | 47 |

## Calibrazione (confidence dichiarata vs accuratezza reale)

| Fascia confidence | N | Accuratezza |
|---|---|---|
| bassa (0-49) | 58 | 51.7% |
| media (50-74) | 56 | 44.6% |
| alta (75-100) | 10 | 50.0% |

## Probabilità (Brier Score, Log Loss)

- Brier Score: **0.6048** (n=60; range 0-2, più basso è meglio)
- Log Loss: **1.0017** (n=60; più basso è meglio)
- Riferimento "non informativo" (probabilità sempre 33.3%/33.3%/33.3%): Brier 0.667, Log Loss 1.099 — l'agente deve fare meglio di questo per aggiungere valore.
- 64 previsioni valutate sono precedenti all'introduzione delle probabilità (2026-09-18) ed escluse da queste due metriche.

## Accuratezza per versione del prompt

Cambiare il prompt cambia l'esperimento: un unico numero di accuratezza
sopra versioni diverse nasconderebbe l'effetto del cambio. Le versioni sono
descritte in `src/config.py` (`PROMPT_VERSION`).

| Versione | N | Accuratezza |
|---|---|---|
| v1 | 60 | 45.0% |
| v2 | 64 | 51.6% |

## Confronto con baseline naive

- Random (3 classi equiprobabili): 33.3%
- Persistenza (ripete l'ultimo esito reale osservato): 55.7% (n=115)
- Classe più frequente (frequenza storica su decenni di prezzi, pesata sullo stesso mix asset/orizzonte): 44.9% (n=124)
- **Agente AI: 48.4%**

> La baseline "classe più frequente" è la più dura delle tre: è
> l'accuratezza di chi prevede sempre la stessa classe senza
> guardare né prezzi né notizie. Batterla è il minimo perché
> l'agente stia aggiungendo qualcosa. Dettaglio per asset e
> orizzonte in `data/baseline.json` (rigenerabile con
> `python -m src.baseline_run`).

