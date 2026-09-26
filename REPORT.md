# Report accuratezza — aggiornato al 2026-09-26T08:48:00.838395+00:00

**Previsioni valutate: 89 — accuratezza complessiva: 42.7%**

## Per asset / orizzonte

| Asset | Orizzonte | N | Accuratezza |
|---|---|---|---|
| AAPL | 1d | 17 | 52.9% |
| AAPL | 7d | 13 | 53.8% |
| MSFT | 1d | 16 | 37.5% |
| MSFT | 7d | 13 | 23.1% |
| NVDA | 1d | 17 | 47.1% |
| NVDA | 7d | 13 | 38.5% |

## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)

| Predetto \ Reale | UP | DOWN | FLAT |
|---|---|---|---|
| UP | 9 | 13 | 18 |
| DOWN | 0 | 0 | 0 |
| FLAT | 14 | 6 | 29 |

## Calibrazione (confidence dichiarata vs accuratezza reale)

| Fascia confidence | N | Accuratezza |
|---|---|---|
| bassa (0-49) | 20 | 75.0% |
| media (50-74) | 59 | 33.9% |
| alta (75-100) | 10 | 30.0% |

## Probabilità (Brier Score, Log Loss)

- Brier Score: **0.525** (n=18; range 0-2, più basso è meglio)
- Log Loss: **0.8832** (n=18; più basso è meglio)
- Riferimento "non informativo" (probabilità sempre 33.3%/33.3%/33.3%): Brier 0.667, Log Loss 1.099 — l'agente deve fare meglio di questo per aggiungere valore.
- 71 previsioni valutate sono precedenti all'introduzione delle probabilità (2026-09-18) ed escluse da queste due metriche.

## Accuratezza per versione del prompt

Cambiare il prompt cambia l'esperimento: un unico numero di accuratezza
sopra versioni diverse nasconderebbe l'effetto del cambio. Le versioni sono
descritte in `src/config.py` (`PROMPT_VERSION`).

| Versione | N | Accuratezza |
|---|---|---|
| v1 | 66 | 33.3% |
| v2 | 23 | 69.6% |

## Confronto con baseline naive

- Random (3 classi equiprobabili): 33.3%
- Persistenza (ripete l'ultimo esito reale osservato): 62.7% (n=83)
- Classe più frequente (frequenza storica su decenni di prezzi, pesata sullo stesso mix asset/orizzonte): 45.8% (n=89)
- **Agente AI: 42.7%**

> La baseline "classe più frequente" è la più dura delle tre: è
> l'accuratezza di chi prevede sempre la stessa classe senza
> guardare né prezzi né notizie. Batterla è il minimo perché
> l'agente stia aggiungendo qualcosa. Dettaglio per asset e
> orizzonte in `data/baseline.json` (rigenerabile con
> `python -m src.baseline_run`).

