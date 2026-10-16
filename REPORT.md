# Report accuratezza — aggiornato al 2026-10-16T08:27:08.755722+00:00

**Previsioni valutate: 144 — accuratezza complessiva: 48.6%**

## Per asset / orizzonte

| Asset | Orizzonte | N | Accuratezza |
|---|---|---|---|
| AAPL | 1d | 31 | 48.4% |
| AAPL | 1m | 10 | 50.0% |
| AAPL | 7d | 21 | 61.9% |
| AMD | 1d | 11 | 36.4% |
| AMD | 7d | 2 | 50.0% |
| MU | 1d | 6 | 50.0% |
| MU | 7d | 1 | 0.0% |
| NVDA | 1d | 31 | 41.9% |
| NVDA | 1m | 10 | 80.0% |
| NVDA | 7d | 21 | 38.1% |

## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)

| Predetto \ Reale | UP | DOWN | FLAT |
|---|---|---|---|
| UP | 13 | 12 | 18 |
| DOWN | 0 | 1 | 0 |
| FLAT | 25 | 19 | 56 |

## Calibrazione (confidence dichiarata vs accuratezza reale)

| Fascia confidence | N | Accuratezza |
|---|---|---|
| bassa (0-49) | 74 | 48.6% |
| media (50-74) | 60 | 48.3% |
| alta (75-100) | 10 | 50.0% |

## Probabilità (Brier Score, Log Loss)

- Brier Score: **0.6285** (n=76; range 0-2, più basso è meglio)
- Log Loss: **1.0409** (n=76; più basso è meglio)
- Riferimento "non informativo" (probabilità sempre 33.3%/33.3%/33.3%): Brier 0.667, Log Loss 1.099 — l'agente deve fare meglio di questo per aggiungere valore.
- 68 previsioni valutate sono precedenti all'introduzione delle probabilità (2026-09-18) ed escluse da queste due metriche.

## Accuratezza per versione del prompt

Cambiare il prompt cambia l'esperimento: un unico numero di accuratezza
sopra versioni diverse nasconderebbe l'effetto del cambio. Le versioni sono
descritte in `src/config.py` (`PROMPT_VERSION`).

| Versione | N | Accuratezza |
|---|---|---|
| v1 | 64 | 48.4% |
| v2 | 80 | 48.8% |

## Confronto con baseline naive

- Random (3 classi equiprobabili): 33.3%
- Persistenza (ripete l'ultimo esito reale osservato): 54.5% (n=134)
- Classe più frequente (frequenza storica su decenni di prezzi, pesata sullo stesso mix asset/orizzonte): 44.9% (n=144)
- Chronos-Bolt-tiny (Amazon, open-source — previsione numerica pura su serie storiche, zero news/macro/fondamentali): 50.0% (n=4)
- **Agente AI: 48.6%**

> La baseline "classe più frequente" è la più dura delle tre: è
> l'accuratezza di chi prevede sempre la stessa classe senza
> guardare né prezzi né notizie. Batterla è il minimo perché
> l'agente stia aggiungendo qualcosa. Dettaglio per asset e
> orizzonte in `data/baseline.json` (rigenerabile con
> `python -m src.baseline_run`).

