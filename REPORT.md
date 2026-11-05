# Report accuratezza — aggiornato al 2026-11-05T11:25:43.374981+00:00

**Previsioni valutate: 216 — accuratezza complessiva: 39.4%**

## Per asset / orizzonte

| Asset | Orizzonte | N | Accuratezza |
|---|---|---|---|
| AAPL | 1d | 40 | 42.5% |
| AAPL | 1m | 21 | 33.3% |
| AAPL | 7d | 24 | 58.3% |
| AMD | 1d | 20 | 25.0% |
| AMD | 1m | 2 | 0.0% |
| AMD | 7d | 5 | 40.0% |
| MU | 1d | 15 | 40.0% |
| MU | 7d | 4 | 0.0% |
| NVDA | 1d | 40 | 40.0% |
| NVDA | 1m | 21 | 47.6% |
| NVDA | 7d | 24 | 33.3% |

## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)

| Predetto \ Reale | UP | DOWN | FLAT |
|---|---|---|---|
| UP | 16 | 19 | 33 |
| DOWN | 4 | 2 | 3 |
| FLAT | 37 | 35 | 67 |

## Calibrazione (confidence dichiarata vs accuratezza reale)

| Fascia confidence | N | Accuratezza |
|---|---|---|
| bassa (0-49) | 141 | 34.8% |
| media (50-74) | 64 | 46.9% |
| alta (75-100) | 11 | 54.5% |

## Probabilità (Brier Score, Log Loss)

- Brier Score: **0.666** (n=144; range 0-2, più basso è meglio)
- Log Loss: **1.0977** (n=144; più basso è meglio)
- Riferimento "non informativo" (probabilità sempre 33.3%/33.3%/33.3%): Brier 0.667, Log Loss 1.099 — l'agente deve fare meglio di questo per aggiungere valore.
- 72 previsioni valutate sono precedenti all'introduzione delle probabilità (2026-09-18) ed escluse da queste due metriche.

## Accuratezza per versione del prompt

Cambiare il prompt cambia l'esperimento: un unico numero di accuratezza
sopra versioni diverse nasconderebbe l'effetto del cambio. Le versioni sono
descritte in `src/config.py` (`PROMPT_VERSION`).

| Versione | N | Accuratezza |
|---|---|---|
| v1 | 66 | 48.5% |
| v2 | 122 | 38.5% |
| v3 | 28 | 21.4% |

## Confronto con baseline naive

- Random (3 classi equiprobabili): 33.3%
- Persistenza (ripete l'ultimo esito reale osservato): 49.8% (n=205)
- Classe più frequente (frequenza storica su decenni di prezzi, pesata sullo stesso mix asset/orizzonte): 44.6% (n=216)
- Chronos-Bolt-tiny (Amazon, open-source — previsione numerica pura su serie storiche, zero news/macro/fondamentali): 34.0% (n=50)
- **Agente AI: 39.4%**

> La baseline "classe più frequente" è la più dura delle tre: è
> l'accuratezza di chi prevede sempre la stessa classe senza
> guardare né prezzi né notizie. Batterla è il minimo perché
> l'agente stia aggiungendo qualcosa. Dettaglio per asset e
> orizzonte in `data/baseline.json` (rigenerabile con
> `python -m src.baseline_run`).

