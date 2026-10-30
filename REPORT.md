# Report accuratezza — aggiornato al 2026-10-30T10:23:52.716836+00:00

**Previsioni valutate: 204 — accuratezza complessiva: 41.7%**

## Per asset / orizzonte

| Asset | Orizzonte | N | Accuratezza |
|---|---|---|---|
| AAPL | 1d | 39 | 43.6% |
| AAPL | 1m | 20 | 35.0% |
| AAPL | 7d | 23 | 60.9% |
| AMD | 1d | 19 | 26.3% |
| AMD | 7d | 4 | 50.0% |
| MU | 1d | 14 | 42.9% |
| MU | 7d | 3 | 0.0% |
| NVDA | 1d | 39 | 41.0% |
| NVDA | 1m | 20 | 50.0% |
| NVDA | 7d | 23 | 34.8% |

## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)

| Predetto \ Reale | UP | DOWN | FLAT |
|---|---|---|---|
| UP | 16 | 15 | 32 |
| DOWN | 4 | 2 | 2 |
| FLAT | 36 | 30 | 67 |

## Calibrazione (confidence dichiarata vs accuratezza reale)

| Fascia confidence | N | Accuratezza |
|---|---|---|
| bassa (0-49) | 130 | 37.7% |
| media (50-74) | 63 | 47.6% |
| alta (75-100) | 11 | 54.5% |

## Probabilità (Brier Score, Log Loss)

- Brier Score: **0.6521** (n=132; range 0-2, più basso è meglio)
- Log Loss: **1.0749** (n=132; più basso è meglio)
- Riferimento "non informativo" (probabilità sempre 33.3%/33.3%/33.3%): Brier 0.667, Log Loss 1.099 — l'agente deve fare meglio di questo per aggiungere valore.
- 72 previsioni valutate sono precedenti all'introduzione delle probabilità (2026-09-18) ed escluse da queste due metriche.

## Accuratezza per versione del prompt

Cambiare il prompt cambia l'esperimento: un unico numero di accuratezza
sopra versioni diverse nasconderebbe l'effetto del cambio. Le versioni sono
descritte in `src/config.py` (`PROMPT_VERSION`).

| Versione | N | Accuratezza |
|---|---|---|
| v1 | 66 | 48.5% |
| v2 | 118 | 39.8% |
| v3 | 20 | 30.0% |

## Confronto con baseline naive

- Random (3 classi equiprobabili): 33.3%
- Persistenza (ripete l'ultimo esito reale osservato): 50.5% (n=194)
- Classe più frequente (frequenza storica su decenni di prezzi, pesata sullo stesso mix asset/orizzonte): 44.6% (n=204)
- Chronos-Bolt-tiny (Amazon, open-source — previsione numerica pura su serie storiche, zero news/macro/fondamentali): 38.1% (n=42)
- **Agente AI: 41.7%**

> La baseline "classe più frequente" è la più dura delle tre: è
> l'accuratezza di chi prevede sempre la stessa classe senza
> guardare né prezzi né notizie. Batterla è il minimo perché
> l'agente stia aggiungendo qualcosa. Dettaglio per asset e
> orizzonte in `data/baseline.json` (rigenerabile con
> `python -m src.baseline_run`).

