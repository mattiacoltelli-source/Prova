# Report accuratezza — aggiornato al 2026-10-06T23:47:45.187382+00:00

**Previsioni valutate: 144 — accuratezza complessiva: 45.8%**

## Per asset / orizzonte

| Asset | Orizzonte | N | Accuratezza |
|---|---|---|---|
| AAPL | 1d | 24 | 50.0% |
| AAPL | 1m | 3 | 33.3% |
| AAPL | 7d | 20 | 65.0% |
| AMD | 1d | 4 | 75.0% |
| MSFT | 1d | 23 | 47.8% |
| MSFT | 1m | 3 | 33.3% |
| MSFT | 7d | 20 | 25.0% |
| NVDA | 1d | 24 | 45.8% |
| NVDA | 1m | 3 | 33.3% |
| NVDA | 7d | 20 | 40.0% |

## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)

| Predetto \ Reale | UP | DOWN | FLAT |
|---|---|---|---|
| UP | 12 | 13 | 24 |
| DOWN | 0 | 0 | 0 |
| FLAT | 31 | 10 | 54 |

## Calibrazione (confidence dichiarata vs accuratezza reale)

| Fascia confidence | N | Accuratezza |
|---|---|---|
| bassa (0-49) | 64 | 59.4% |
| media (50-74) | 69 | 34.8% |
| alta (75-100) | 11 | 36.4% |

## Probabilità (Brier Score, Log Loss)

- Brier Score: **0.567** (n=64; range 0-2, più basso è meglio)
- Log Loss: **0.9434** (n=64; più basso è meglio)
- Riferimento "non informativo" (probabilità sempre 33.3%/33.3%/33.3%): Brier 0.667, Log Loss 1.099 — l'agente deve fare meglio di questo per aggiungere valore.
- 80 previsioni valutate sono precedenti all'introduzione delle probabilità (2026-09-18) ed escluse da queste due metriche.

## Accuratezza per versione del prompt

Cambiare il prompt cambia l'esperimento: un unico numero di accuratezza
sopra versioni diverse nasconderebbe l'effetto del cambio. Le versioni sono
descritte in `src/config.py` (`PROMPT_VERSION`).

| Versione | N | Accuratezza |
|---|---|---|
| v1 | 75 | 33.3% |
| v2 | 69 | 59.4% |

## Confronto con baseline naive

- Random (3 classi equiprobabili): 33.3%
- Persistenza (ripete l'ultimo esito reale osservato): 57.5% (n=134)
- Classe più frequente (frequenza storica su decenni di prezzi, pesata sullo stesso mix asset/orizzonte): 45.4% (n=140)
- **Agente AI: 45.8%**

> La baseline "classe più frequente" è la più dura delle tre: è
> l'accuratezza di chi prevede sempre la stessa classe senza
> guardare né prezzi né notizie. Batterla è il minimo perché
> l'agente stia aggiungendo qualcosa. Dettaglio per asset e
> orizzonte in `data/baseline.json` (rigenerabile con
> `python -m src.baseline_run`).

