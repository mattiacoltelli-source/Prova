# Report accuratezza — aggiornato al 2026-10-27T23:45:57.810214+00:00

**Previsioni valutate: 190 — accuratezza complessiva: 43.2%**

## Per asset / orizzonte

| Asset | Orizzonte | N | Accuratezza |
|---|---|---|---|
| AAPL | 1d | 37 | 45.9% |
| AAPL | 1m | 18 | 33.3% |
| AAPL | 7d | 23 | 60.9% |
| AMD | 1d | 17 | 23.5% |
| AMD | 7d | 3 | 66.7% |
| MU | 1d | 12 | 50.0% |
| MU | 7d | 2 | 0.0% |
| NVDA | 1d | 37 | 40.5% |
| NVDA | 1m | 18 | 55.6% |
| NVDA | 7d | 23 | 34.8% |

## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)

| Predetto \ Reale | UP | DOWN | FLAT |
|---|---|---|---|
| UP | 14 | 13 | 31 |
| DOWN | 4 | 2 | 2 |
| FLAT | 32 | 26 | 66 |

## Calibrazione (confidence dichiarata vs accuratezza reale)

| Fascia confidence | N | Accuratezza |
|---|---|---|
| bassa (0-49) | 116 | 39.7% |
| media (50-74) | 63 | 47.6% |
| alta (75-100) | 11 | 54.5% |

## Probabilità (Brier Score, Log Loss)

- Brier Score: **0.6434** (n=118; range 0-2, più basso è meglio)
- Log Loss: **1.0607** (n=118; più basso è meglio)
- Riferimento "non informativo" (probabilità sempre 33.3%/33.3%/33.3%): Brier 0.667, Log Loss 1.099 — l'agente deve fare meglio di questo per aggiungere valore.
- 72 previsioni valutate sono precedenti all'introduzione delle probabilità (2026-09-18) ed escluse da queste due metriche.

## Accuratezza per versione del prompt

Cambiare il prompt cambia l'esperimento: un unico numero di accuratezza
sopra versioni diverse nasconderebbe l'effetto del cambio. Le versioni sono
descritte in `src/config.py` (`PROMPT_VERSION`).

| Versione | N | Accuratezza |
|---|---|---|
| v1 | 66 | 48.5% |
| v2 | 112 | 41.1% |
| v3 | 12 | 33.3% |

## Confronto con baseline naive

- Random (3 classi equiprobabili): 33.3%
- Persistenza (ripete l'ultimo esito reale osservato): 52.2% (n=180)
- Classe più frequente (frequenza storica su decenni di prezzi, pesata sullo stesso mix asset/orizzonte): 44.7% (n=190)
- Chronos-Bolt-tiny (Amazon, open-source — previsione numerica pura su serie storiche, zero news/macro/fondamentali): 40.6% (n=32)
- **Agente AI: 43.2%**

> La baseline "classe più frequente" è la più dura delle tre: è
> l'accuratezza di chi prevede sempre la stessa classe senza
> guardare né prezzi né notizie. Batterla è il minimo perché
> l'agente stia aggiungendo qualcosa. Dettaglio per asset e
> orizzonte in `data/baseline.json` (rigenerabile con
> `python -m src.baseline_run`).

