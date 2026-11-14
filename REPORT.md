# Report accuratezza — aggiornato al 2026-11-14T10:50:09.703107+00:00

**Previsioni valutate: 255 — accuratezza complessiva: 36.9%**

## Per asset / orizzonte

| Asset | Orizzonte | N | Accuratezza |
|---|---|---|---|
| AAPL | 1d | 45 | 42.2% |
| AAPL | 1m | 24 | 37.5% |
| AAPL | 7d | 25 | 56.0% |
| AMD | 1d | 26 | 19.2% |
| AMD | 1m | 5 | 0.0% |
| AMD | 7d | 6 | 33.3% |
| MU | 1d | 21 | 38.1% |
| MU | 1m | 3 | 33.3% |
| MU | 7d | 5 | 0.0% |
| NVDA | 1d | 46 | 39.1% |
| NVDA | 1m | 24 | 41.7% |
| NVDA | 7d | 25 | 32.0% |

## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)

| Predetto \ Reale | UP | DOWN | FLAT |
|---|---|---|---|
| UP | 18 | 24 | 35 |
| DOWN | 10 | 4 | 4 |
| FLAT | 44 | 44 | 72 |

## Calibrazione (confidence dichiarata vs accuratezza reale)

| Fascia confidence | N | Accuratezza |
|---|---|---|
| bassa (0-49) | 179 | 32.4% |
| media (50-74) | 65 | 46.2% |
| alta (75-100) | 11 | 54.5% |

## Probabilità (Brier Score, Log Loss)

- Brier Score: **0.6783** (n=183; range 0-2, più basso è meglio)
- Log Loss: **1.1181** (n=183; più basso è meglio)
- Riferimento "non informativo" (probabilità sempre 33.3%/33.3%/33.3%): Brier 0.667, Log Loss 1.099 — l'agente deve fare meglio di questo per aggiungere valore.
- 72 previsioni valutate sono precedenti all'introduzione delle probabilità (2026-09-18) ed escluse da queste due metriche.

## Accuratezza per versione del prompt

Cambiare il prompt cambia l'esperimento: un unico numero di accuratezza
sopra versioni diverse nasconderebbe l'effetto del cambio. Le versioni sono
descritte in `src/config.py` (`PROMPT_VERSION`).

| Versione | N | Accuratezza |
|---|---|---|
| v1 | 66 | 48.5% |
| v2 | 134 | 37.3% |
| v3 | 55 | 21.8% |

## Confronto con baseline naive

- Random (3 classi equiprobabili): 33.3%
- Persistenza (ripete l'ultimo esito reale osservato): 50.2% (n=243)
- Classe più frequente (frequenza storica su decenni di prezzi, pesata sullo stesso mix asset/orizzonte): 44.5% (n=255)
- Chronos-Bolt-tiny (Amazon, open-source — previsione numerica pura su serie storiche, zero news/macro/fondamentali): 32.1% (n=81)
- **Agente AI: 36.9%**

> La baseline "classe più frequente" è la più dura delle tre: è
> l'accuratezza di chi prevede sempre la stessa classe senza
> guardare né prezzi né notizie. Batterla è il minimo perché
> l'agente stia aggiungendo qualcosa. Dettaglio per asset e
> orizzonte in `data/baseline.json` (rigenerabile con
> `python -m src.baseline_run`).

