# Report accuratezza — aggiornato al 2026-10-20T23:10:18.279907+00:00

**Previsioni valutate: 156 — accuratezza complessiva: 48.7%**

## Per asset / orizzonte

| Asset | Orizzonte | N | Accuratezza |
|---|---|---|---|
| AAPL | 1d | 32 | 50.0% |
| AAPL | 1m | 13 | 46.2% |
| AAPL | 7d | 22 | 63.6% |
| AMD | 1d | 12 | 33.3% |
| AMD | 7d | 2 | 50.0% |
| MU | 1d | 7 | 57.1% |
| MU | 7d | 1 | 0.0% |
| NVDA | 1d | 32 | 40.6% |
| NVDA | 1m | 13 | 76.9% |
| NVDA | 7d | 22 | 36.4% |

## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)

| Predetto \ Reale | UP | DOWN | FLAT |
|---|---|---|---|
| UP | 13 | 12 | 21 |
| DOWN | 0 | 2 | 0 |
| FLAT | 25 | 22 | 61 |

## Calibrazione (confidence dichiarata vs accuratezza reale)

| Fascia confidence | N | Accuratezza |
|---|---|---|
| bassa (0-49) | 83 | 48.2% |
| media (50-74) | 62 | 48.4% |
| alta (75-100) | 11 | 54.5% |

## Probabilità (Brier Score, Log Loss)

- Brier Score: **0.6297** (n=84; range 0-2, più basso è meglio)
- Log Loss: **1.0434** (n=84; più basso è meglio)
- Riferimento "non informativo" (probabilità sempre 33.3%/33.3%/33.3%): Brier 0.667, Log Loss 1.099 — l'agente deve fare meglio di questo per aggiungere valore.
- 72 previsioni valutate sono precedenti all'introduzione delle probabilità (2026-09-18) ed escluse da queste due metriche.

## Accuratezza per versione del prompt

Cambiare il prompt cambia l'esperimento: un unico numero di accuratezza
sopra versioni diverse nasconderebbe l'effetto del cambio. Le versioni sono
descritte in `src/config.py` (`PROMPT_VERSION`).

| Versione | N | Accuratezza |
|---|---|---|
| v1 | 66 | 48.5% |
| v2 | 90 | 48.9% |

## Confronto con baseline naive

- Random (3 classi equiprobabili): 33.3%
- Persistenza (ripete l'ultimo esito reale osservato): 56.2% (n=146)
- Classe più frequente (frequenza storica su decenni di prezzi, pesata sullo stesso mix asset/orizzonte): 44.7% (n=156)
- Chronos-Bolt-tiny (Amazon, open-source — previsione numerica pura su serie storiche, zero news/macro/fondamentali): 37.5% (n=8)
- **Agente AI: 48.7%**

> La baseline "classe più frequente" è la più dura delle tre: è
> l'accuratezza di chi prevede sempre la stessa classe senza
> guardare né prezzi né notizie. Batterla è il minimo perché
> l'agente stia aggiungendo qualcosa. Dettaglio per asset e
> orizzonte in `data/baseline.json` (rigenerabile con
> `python -m src.baseline_run`).

