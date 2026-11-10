# Report accuratezza — aggiornato al 2026-11-10T02:43:38.697576+00:00

**Previsioni valutate: 235 — accuratezza complessiva: 37.0%**

## Per asset / orizzonte

| Asset | Orizzonte | N | Accuratezza |
|---|---|---|---|
| AAPL | 1d | 42 | 40.5% |
| AAPL | 1m | 23 | 34.8% |
| AAPL | 7d | 24 | 58.3% |
| AMD | 1d | 23 | 21.7% |
| AMD | 1m | 4 | 0.0% |
| AMD | 7d | 5 | 40.0% |
| MU | 1d | 18 | 33.3% |
| MU | 1m | 2 | 0.0% |
| MU | 7d | 4 | 0.0% |
| NVDA | 1d | 43 | 39.5% |
| NVDA | 1m | 23 | 43.5% |
| NVDA | 7d | 24 | 33.3% |

## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)

| Predetto \ Reale | UP | DOWN | FLAT |
|---|---|---|---|
| UP | 17 | 23 | 34 |
| DOWN | 9 | 3 | 3 |
| FLAT | 38 | 41 | 67 |

## Calibrazione (confidence dichiarata vs accuratezza reale)

| Fascia confidence | N | Accuratezza |
|---|---|---|
| bassa (0-49) | 159 | 32.1% |
| media (50-74) | 65 | 46.2% |
| alta (75-100) | 11 | 54.5% |

## Probabilità (Brier Score, Log Loss)

- Brier Score: **0.6792** (n=163; range 0-2, più basso è meglio)
- Log Loss: **1.1191** (n=163; più basso è meglio)
- Riferimento "non informativo" (probabilità sempre 33.3%/33.3%/33.3%): Brier 0.667, Log Loss 1.099 — l'agente deve fare meglio di questo per aggiungere valore.
- 72 previsioni valutate sono precedenti all'introduzione delle probabilità (2026-09-18) ed escluse da queste due metriche.

## Accuratezza per versione del prompt

Cambiare il prompt cambia l'esperimento: un unico numero di accuratezza
sopra versioni diverse nasconderebbe l'effetto del cambio. Le versioni sono
descritte in `src/config.py` (`PROMPT_VERSION`).

| Versione | N | Accuratezza |
|---|---|---|
| v1 | 66 | 48.5% |
| v2 | 130 | 36.9% |
| v3 | 39 | 17.9% |

## Confronto con baseline naive

- Random (3 classi equiprobabili): 33.3%
- Persistenza (ripete l'ultimo esito reale osservato): 50.2% (n=223)
- Classe più frequente (frequenza storica su decenni di prezzi, pesata sullo stesso mix asset/orizzonte): 44.5% (n=235)
- Chronos-Bolt-tiny (Amazon, open-source — previsione numerica pura su serie storiche, zero news/macro/fondamentali): 32.8% (n=61)
- **Agente AI: 37.0%**

> La baseline "classe più frequente" è la più dura delle tre: è
> l'accuratezza di chi prevede sempre la stessa classe senza
> guardare né prezzi né notizie. Batterla è il minimo perché
> l'agente stia aggiungendo qualcosa. Dettaglio per asset e
> orizzonte in `data/baseline.json` (rigenerabile con
> `python -m src.baseline_run`).

