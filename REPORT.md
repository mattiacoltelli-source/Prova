# Report accuratezza — aggiornato al 2026-10-06T10:42:47.388513+00:00

**Previsioni valutate: 137 — accuratezza complessiva: 44.5%**

## Per asset / orizzonte

| Asset | Orizzonte | N | Accuratezza |
|---|---|---|---|
| AAPL | 1d | 23 | 47.8% |
| AAPL | 1m | 3 | 33.3% |
| AAPL | 7d | 19 | 63.2% |
| AMD | 1d | 3 | 66.7% |
| MSFT | 1d | 22 | 45.5% |
| MSFT | 1m | 3 | 33.3% |
| MSFT | 7d | 19 | 26.3% |
| NVDA | 1d | 23 | 43.5% |
| NVDA | 1m | 3 | 33.3% |
| NVDA | 7d | 19 | 42.1% |

## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)

| Predetto \ Reale | UP | DOWN | FLAT |
|---|---|---|---|
| UP | 11 | 13 | 24 |
| DOWN | 0 | 0 | 0 |
| FLAT | 29 | 10 | 50 |

## Calibrazione (confidence dichiarata vs accuratezza reale)

| Fascia confidence | N | Accuratezza |
|---|---|---|
| bassa (0-49) | 58 | 58.6% |
| media (50-74) | 68 | 33.8% |
| alta (75-100) | 11 | 36.4% |

## Probabilità (Brier Score, Log Loss)

- Brier Score: **0.5784** (n=57; range 0-2, più basso è meglio)
- Log Loss: **0.9596** (n=57; più basso è meglio)
- Riferimento "non informativo" (probabilità sempre 33.3%/33.3%/33.3%): Brier 0.667, Log Loss 1.099 — l'agente deve fare meglio di questo per aggiungere valore.
- 80 previsioni valutate sono precedenti all'introduzione delle probabilità (2026-09-18) ed escluse da queste due metriche.

## Accuratezza per versione del prompt

Cambiare il prompt cambia l'esperimento: un unico numero di accuratezza
sopra versioni diverse nasconderebbe l'effetto del cambio. Le versioni sono
descritte in `src/config.py` (`PROMPT_VERSION`).

| Versione | N | Accuratezza |
|---|---|---|
| v1 | 75 | 33.3% |
| v2 | 62 | 58.1% |

## Confronto con baseline naive

- Random (3 classi equiprobabili): 33.3%
- Persistenza (ripete l'ultimo esito reale osservato): 57.5% (n=127)
- Classe più frequente (frequenza storica su decenni di prezzi, pesata sullo stesso mix asset/orizzonte): 45.4% (n=134)
- **Agente AI: 44.5%**

> La baseline "classe più frequente" è la più dura delle tre: è
> l'accuratezza di chi prevede sempre la stessa classe senza
> guardare né prezzi né notizie. Batterla è il minimo perché
> l'agente stia aggiungendo qualcosa. Dettaglio per asset e
> orizzonte in `data/baseline.json` (rigenerabile con
> `python -m src.baseline_run`).

