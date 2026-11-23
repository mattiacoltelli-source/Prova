# Report accuratezza — aggiornato al 2026-11-23T00:49:32.701812+00:00

**Previsioni valutate: 263 — accuratezza complessiva: 36.1%**

## Per asset / orizzonte

| Asset | Orizzonte | N | Accuratezza |
|---|---|---|---|
| AAPL | 1d | 45 | 42.2% |
| AAPL | 1m | 25 | 36.0% |
| AAPL | 7d | 26 | 57.7% |
| AMD | 1d | 26 | 19.2% |
| AMD | 1m | 6 | 0.0% |
| AMD | 7d | 7 | 28.6% |
| MU | 1d | 21 | 38.1% |
| MU | 1m | 4 | 25.0% |
| MU | 7d | 6 | 0.0% |
| NVDA | 1d | 46 | 39.1% |
| NVDA | 1m | 25 | 40.0% |
| NVDA | 7d | 26 | 30.8% |

## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)

| Predetto \ Reale | UP | DOWN | FLAT |
|---|---|---|---|
| UP | 18 | 25 | 38 |
| DOWN | 10 | 4 | 4 |
| FLAT | 44 | 47 | 73 |

## Calibrazione (confidence dichiarata vs accuratezza reale)

| Fascia confidence | N | Accuratezza |
|---|---|---|
| bassa (0-49) | 187 | 31.6% |
| media (50-74) | 65 | 46.2% |
| alta (75-100) | 11 | 54.5% |

## Probabilità (Brier Score, Log Loss)

- Brier Score: **0.6788** (n=191; range 0-2, più basso è meglio)
- Log Loss: **1.119** (n=191; più basso è meglio)
- Riferimento "non informativo" (probabilità sempre 33.3%/33.3%/33.3%): Brier 0.667, Log Loss 1.099 — l'agente deve fare meglio di questo per aggiungere valore.
- 72 previsioni valutate sono precedenti all'introduzione delle probabilità (2026-09-18) ed escluse da queste due metriche.

## Accuratezza per versione del prompt

Cambiare il prompt cambia l'esperimento: un unico numero di accuratezza
sopra versioni diverse nasconderebbe l'effetto del cambio. Le versioni sono
descritte in `src/config.py` (`PROMPT_VERSION`).

| Versione | N | Accuratezza |
|---|---|---|
| v1 | 66 | 48.5% |
| v2 | 138 | 36.2% |
| v3 | 59 | 22.0% |

## Confronto con baseline naive

- Random (3 classi equiprobabili): 33.3%
- Persistenza (ripete l'ultimo esito reale osservato): 50.2% (n=251)
- Classe più frequente (frequenza storica su decenni di prezzi, pesata sullo stesso mix asset/orizzonte): 44.5% (n=263)
- Chronos-Bolt-tiny (Amazon, open-source — previsione numerica pura su serie storiche, zero news/macro/fondamentali): 33.7% (n=89)
- **Agente AI: 36.1%**

> La baseline "classe più frequente" è la più dura delle tre: è
> l'accuratezza di chi prevede sempre la stessa classe senza
> guardare né prezzi né notizie. Batterla è il minimo perché
> l'agente stia aggiungendo qualcosa. Dettaglio per asset e
> orizzonte in `data/baseline.json` (rigenerabile con
> `python -m src.baseline_run`).

