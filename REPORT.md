# Report accuratezza — aggiornato al 2026-10-23T23:07:34.948010+00:00

**Previsioni valutate: 176 — accuratezza complessiva: 45.5%**

## Per asset / orizzonte

| Asset | Orizzonte | N | Accuratezza |
|---|---|---|---|
| AAPL | 1d | 35 | 48.6% |
| AAPL | 1m | 16 | 37.5% |
| AAPL | 7d | 22 | 63.6% |
| AMD | 1d | 15 | 26.7% |
| AMD | 7d | 3 | 66.7% |
| MU | 1d | 10 | 50.0% |
| MU | 7d | 2 | 0.0% |
| NVDA | 1d | 35 | 40.0% |
| NVDA | 1m | 16 | 62.5% |
| NVDA | 7d | 22 | 36.4% |

## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)

| Predetto \ Reale | UP | DOWN | FLAT |
|---|---|---|---|
| UP | 13 | 13 | 26 |
| DOWN | 1 | 2 | 2 |
| FLAT | 29 | 25 | 65 |

## Calibrazione (confidence dichiarata vs accuratezza reale)

| Fascia confidence | N | Accuratezza |
|---|---|---|
| bassa (0-49) | 102 | 43.1% |
| media (50-74) | 63 | 47.6% |
| alta (75-100) | 11 | 54.5% |

## Probabilità (Brier Score, Log Loss)

- Brier Score: **0.6429** (n=104; range 0-2, più basso è meglio)
- Log Loss: **1.0614** (n=104; più basso è meglio)
- Riferimento "non informativo" (probabilità sempre 33.3%/33.3%/33.3%): Brier 0.667, Log Loss 1.099 — l'agente deve fare meglio di questo per aggiungere valore.
- 72 previsioni valutate sono precedenti all'introduzione delle probabilità (2026-09-18) ed escluse da queste due metriche.

## Accuratezza per versione del prompt

Cambiare il prompt cambia l'esperimento: un unico numero di accuratezza
sopra versioni diverse nasconderebbe l'effetto del cambio. Le versioni sono
descritte in `src/config.py` (`PROMPT_VERSION`).

| Versione | N | Accuratezza |
|---|---|---|
| v1 | 66 | 48.5% |
| v2 | 106 | 43.4% |
| v3 | 4 | 50.0% |

## Confronto con baseline naive

- Random (3 classi equiprobabili): 33.3%
- Persistenza (ripete l'ultimo esito reale osservato): 53.0% (n=166)
- Classe più frequente (frequenza storica su decenni di prezzi, pesata sullo stesso mix asset/orizzonte): 44.7% (n=176)
- Chronos-Bolt-tiny (Amazon, open-source — previsione numerica pura su serie storiche, zero news/macro/fondamentali): 40.9% (n=22)
- **Agente AI: 45.5%**

> La baseline "classe più frequente" è la più dura delle tre: è
> l'accuratezza di chi prevede sempre la stessa classe senza
> guardare né prezzi né notizie. Batterla è il minimo perché
> l'agente stia aggiungendo qualcosa. Dettaglio per asset e
> orizzonte in `data/baseline.json` (rigenerabile con
> `python -m src.baseline_run`).

