# Report accuratezza — aggiornato al 2026-10-14T23:12:33.104874+00:00

**Previsioni valutate: 138 — accuratezza complessiva: 47.1%**

## Per asset / orizzonte

| Asset | Orizzonte | N | Accuratezza |
|---|---|---|---|
| AAPL | 1d | 30 | 46.7% |
| AAPL | 1m | 9 | 44.4% |
| AAPL | 7d | 21 | 61.9% |
| AMD | 1d | 10 | 30.0% |
| AMD | 7d | 2 | 50.0% |
| MU | 1d | 5 | 40.0% |
| MU | 7d | 1 | 0.0% |
| NVDA | 1d | 30 | 43.3% |
| NVDA | 1m | 9 | 77.8% |
| NVDA | 7d | 21 | 38.1% |

## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)

| Predetto \ Reale | UP | DOWN | FLAT |
|---|---|---|---|
| UP | 13 | 12 | 18 |
| DOWN | 0 | 1 | 0 |
| FLAT | 25 | 18 | 51 |

## Calibrazione (confidence dichiarata vs accuratezza reale)

| Fascia confidence | N | Accuratezza |
|---|---|---|
| bassa (0-49) | 70 | 47.1% |
| media (50-74) | 58 | 46.6% |
| alta (75-100) | 10 | 50.0% |

## Probabilità (Brier Score, Log Loss)

- Brier Score: **0.6288** (n=72; range 0-2, più basso è meglio)
- Log Loss: **1.0408** (n=72; più basso è meglio)
- Riferimento "non informativo" (probabilità sempre 33.3%/33.3%/33.3%): Brier 0.667, Log Loss 1.099 — l'agente deve fare meglio di questo per aggiungere valore.
- 66 previsioni valutate sono precedenti all'introduzione delle probabilità (2026-09-18) ed escluse da queste due metriche.

## Accuratezza per versione del prompt

Cambiare il prompt cambia l'esperimento: un unico numero di accuratezza
sopra versioni diverse nasconderebbe l'effetto del cambio. Le versioni sono
descritte in `src/config.py` (`PROMPT_VERSION`).

| Versione | N | Accuratezza |
|---|---|---|
| v1 | 62 | 46.8% |
| v2 | 76 | 47.4% |

## Confronto con baseline naive

- Random (3 classi equiprobabili): 33.3%
- Persistenza (ripete l'ultimo esito reale osservato): 53.9% (n=128)
- Classe più frequente (frequenza storica su decenni di prezzi, pesata sullo stesso mix asset/orizzonte): 44.9% (n=138)
- **Agente AI: 47.1%**

> La baseline "classe più frequente" è la più dura delle tre: è
> l'accuratezza di chi prevede sempre la stessa classe senza
> guardare né prezzi né notizie. Batterla è il minimo perché
> l'agente stia aggiungendo qualcosa. Dettaglio per asset e
> orizzonte in `data/baseline.json` (rigenerabile con
> `python -m src.baseline_run`).

