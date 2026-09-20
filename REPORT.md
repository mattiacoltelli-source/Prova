# Report accuratezza — aggiornato al 2026-09-20T22:25:50.012024+00:00

**Previsioni valutate: 59 — accuratezza complessiva: 35.6%**

## Per asset / orizzonte

| Asset | Orizzonte | N | Accuratezza |
|---|---|---|---|
| AAPL | 1d | 12 | 41.7% |
| AAPL | 7d | 8 | 62.5% |
| MSFT | 1d | 11 | 18.2% |
| MSFT | 7d | 8 | 25.0% |
| NVDA | 1d | 12 | 33.3% |
| NVDA | 7d | 8 | 37.5% |

## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)

| Predetto \ Reale | UP | DOWN | FLAT |
|---|---|---|---|
| UP | 8 | 13 | 14 |
| DOWN | 0 | 0 | 0 |
| FLAT | 5 | 6 | 13 |

## Calibrazione (confidence dichiarata vs accuratezza reale)

| Fascia confidence | N | Accuratezza |
|---|---|---|
| bassa (0-49) | 1 | 0.0% |
| media (50-74) | 49 | 36.7% |
| alta (75-100) | 9 | 33.3% |

## Probabilità (Brier Score, Log Loss)

- Non ancora calcolabili: nessuna previsione valutata ha le probabilità salvate (introdotte il 2026-09-18).

## Accuratezza per versione del prompt

Cambiare il prompt cambia l'esperimento: un unico numero di accuratezza
sopra versioni diverse nasconderebbe l'effetto del cambio. Le versioni sono
descritte in `src/config.py` (`PROMPT_VERSION`).

| Versione | N | Accuratezza |
|---|---|---|
| v1 | 57 | 36.8% |
| v2 | 2 | 0.0% |

## Confronto con baseline naive

- Random (3 classi equiprobabili): 33.3%
- Persistenza (ripete l'ultimo esito reale osservato): 62.3% (n=53)
- Classe più frequente (frequenza storica su decenni di prezzi, pesata sullo stesso mix asset/orizzonte): 45.9% (n=59)
- **Agente AI: 35.6%**

> La baseline "classe più frequente" è la più dura delle tre: è
> l'accuratezza di chi prevede sempre la stessa classe senza
> guardare né prezzi né notizie. Batterla è il minimo perché
> l'agente stia aggiungendo qualcosa. Dettaglio per asset e
> orizzonte in `data/baseline.json` (rigenerabile con
> `python -m src.baseline_run`).

