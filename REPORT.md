# Report accuratezza — aggiornato al 2026-10-10T23:32:23.394651+00:00

**Previsioni valutate: 114 — accuratezza complessiva: 50.0%**

## Per asset / orizzonte

| Asset | Orizzonte | N | Accuratezza |
|---|---|---|---|
| AAPL | 1d | 27 | 44.4% |
| AAPL | 1m | 5 | 60.0% |
| AAPL | 7d | 20 | 65.0% |
| AMD | 1d | 7 | 42.9% |
| AMD | 7d | 1 | 100.0% |
| MU | 1d | 2 | 50.0% |
| NVDA | 1d | 27 | 48.1% |
| NVDA | 1m | 5 | 60.0% |
| NVDA | 7d | 20 | 40.0% |

## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)

| Predetto \ Reale | UP | DOWN | FLAT |
|---|---|---|---|
| UP | 13 | 10 | 16 |
| DOWN | 0 | 0 | 0 |
| FLAT | 20 | 11 | 44 |

## Calibrazione (confidence dichiarata vs accuratezza reale)

| Fascia confidence | N | Accuratezza |
|---|---|---|
| bassa (0-49) | 54 | 55.6% |
| media (50-74) | 50 | 44.0% |
| alta (75-100) | 10 | 50.0% |

## Probabilità (Brier Score, Log Loss)

- Brier Score: **0.5936** (n=56; range 0-2, più basso è meglio)
- Log Loss: **0.9848** (n=56; più basso è meglio)
- Riferimento "non informativo" (probabilità sempre 33.3%/33.3%/33.3%): Brier 0.667, Log Loss 1.099 — l'agente deve fare meglio di questo per aggiungere valore.
- 58 previsioni valutate sono precedenti all'introduzione delle probabilità (2026-09-18) ed escluse da queste due metriche.

## Accuratezza per versione del prompt

Cambiare il prompt cambia l'esperimento: un unico numero di accuratezza
sopra versioni diverse nasconderebbe l'effetto del cambio. Le versioni sono
descritte in `src/config.py` (`PROMPT_VERSION`).

| Versione | N | Accuratezza |
|---|---|---|
| v1 | 54 | 44.4% |
| v2 | 60 | 55.0% |

## Confronto con baseline naive

- Random (3 classi equiprobabili): 33.3%
- Persistenza (ripete l'ultimo esito reale osservato): 57.1% (n=105)
- Classe più frequente (frequenza storica su decenni di prezzi, pesata sullo stesso mix asset/orizzonte): 45.1% (n=114)
- **Agente AI: 50.0%**

> La baseline "classe più frequente" è la più dura delle tre: è
> l'accuratezza di chi prevede sempre la stessa classe senza
> guardare né prezzi né notizie. Batterla è il minimo perché
> l'agente stia aggiungendo qualcosa. Dettaglio per asset e
> orizzonte in `data/baseline.json` (rigenerabile con
> `python -m src.baseline_run`).

