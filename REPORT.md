# Report accuratezza — aggiornato al 2026-09-22T22:56:02.911908+00:00

**Previsioni valutate: 71 — accuratezza complessiva: 38.0%**

## Per asset / orizzonte

| Asset | Orizzonte | N | Accuratezza |
|---|---|---|---|
| AAPL | 1d | 14 | 50.0% |
| AAPL | 7d | 10 | 60.0% |
| MSFT | 1d | 13 | 30.8% |
| MSFT | 7d | 10 | 20.0% |
| NVDA | 1d | 14 | 35.7% |
| NVDA | 7d | 10 | 30.0% |

## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)

| Predetto \ Reale | UP | DOWN | FLAT |
|---|---|---|---|
| UP | 9 | 13 | 16 |
| DOWN | 0 | 0 | 0 |
| FLAT | 9 | 6 | 18 |

## Calibrazione (confidence dichiarata vs accuratezza reale)

| Fascia confidence | N | Accuratezza |
|---|---|---|
| bassa (0-49) | 7 | 71.4% |
| media (50-74) | 55 | 34.5% |
| alta (75-100) | 9 | 33.3% |

## Probabilità (Brier Score, Log Loss)

- Brier Score: **0.5073** (n=6; range 0-2, più basso è meglio)
- Log Loss: **0.8595** (n=6; più basso è meglio)
- Riferimento "non informativo" (probabilità sempre 33.3%/33.3%/33.3%): Brier 0.667, Log Loss 1.099 — l'agente deve fare meglio di questo per aggiungere valore.
- 65 previsioni valutate sono precedenti all'introduzione delle probabilità (2026-09-18) ed escluse da queste due metriche.

## Accuratezza per versione del prompt

Cambiare il prompt cambia l'esperimento: un unico numero di accuratezza
sopra versioni diverse nasconderebbe l'effetto del cambio. Le versioni sono
descritte in `src/config.py` (`PROMPT_VERSION`).

| Versione | N | Accuratezza |
|---|---|---|
| v1 | 63 | 34.9% |
| v2 | 8 | 62.5% |

## Confronto con baseline naive

- Random (3 classi equiprobabili): 33.3%
- Persistenza (ripete l'ultimo esito reale osservato): 63.1% (n=65)
- Classe più frequente (frequenza storica su decenni di prezzi, pesata sullo stesso mix asset/orizzonte): 45.8% (n=71)
- **Agente AI: 38.0%**

> La baseline "classe più frequente" è la più dura delle tre: è
> l'accuratezza di chi prevede sempre la stessa classe senza
> guardare né prezzi né notizie. Batterla è il minimo perché
> l'agente stia aggiungendo qualcosa. Dettaglio per asset e
> orizzonte in `data/baseline.json` (rigenerabile con
> `python -m src.baseline_run`).

