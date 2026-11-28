# Report accuratezza — aggiornato al 2026-11-28T12:13:30.032746+00:00

**Previsioni valutate: 271 — accuratezza complessiva: 35.8%**

## Per asset / orizzonte

| Asset | Orizzonte | N | Accuratezza |
|---|---|---|---|
| AAPL | 1d | 45 | 42.2% |
| AAPL | 1m | 27 | 37.0% |
| AAPL | 7d | 26 | 57.7% |
| AMD | 1d | 26 | 19.2% |
| AMD | 1m | 8 | 12.5% |
| AMD | 7d | 7 | 28.6% |
| MU | 1d | 21 | 38.1% |
| MU | 1m | 6 | 16.7% |
| MU | 7d | 6 | 0.0% |
| NVDA | 1d | 46 | 39.1% |
| NVDA | 1m | 27 | 37.0% |
| NVDA | 7d | 26 | 30.8% |

## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)

| Predetto \ Reale | UP | DOWN | FLAT |
|---|---|---|---|
| UP | 19 | 28 | 39 |
| DOWN | 10 | 5 | 4 |
| FLAT | 44 | 49 | 73 |

## Calibrazione (confidence dichiarata vs accuratezza reale)

| Fascia confidence | N | Accuratezza |
|---|---|---|
| bassa (0-49) | 195 | 31.3% |
| media (50-74) | 65 | 46.2% |
| alta (75-100) | 11 | 54.5% |

## Probabilità (Brier Score, Log Loss)

- Brier Score: **0.6803** (n=199; range 0-2, più basso è meglio)
- Log Loss: **1.1213** (n=199; più basso è meglio)
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
| v3 | 67 | 22.4% |

## Confronto con baseline naive

- Random (3 classi equiprobabili): 33.3%
- Persistenza (ripete l'ultimo esito reale osservato): 51.0% (n=259)
- Classe più frequente (frequenza storica su decenni di prezzi, pesata sullo stesso mix asset/orizzonte): 44.3% (n=271)
- Chronos-Bolt-tiny (Amazon, open-source — previsione numerica pura su serie storiche, zero news/macro/fondamentali): 32.0% (n=97)
- **Agente AI: 35.8%**

> La baseline "classe più frequente" è la più dura delle tre: è
> l'accuratezza di chi prevede sempre la stessa classe senza
> guardare né prezzi né notizie. Batterla è il minimo perché
> l'agente stia aggiungendo qualcosa. Dettaglio per asset e
> orizzonte in `data/baseline.json` (rigenerabile con
> `python -m src.baseline_run`).

