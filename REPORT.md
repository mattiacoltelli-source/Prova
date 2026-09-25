# Report accuratezza — aggiornato al 2026-09-25T09:03:11.723904+00:00

**Previsioni valutate: 83 — accuratezza complessiva: 42.2%**

## Per asset / orizzonte

| Asset | Orizzonte | N | Accuratezza |
|---|---|---|---|
| AAPL | 1d | 16 | 56.2% |
| AAPL | 7d | 12 | 50.0% |
| MSFT | 1d | 15 | 40.0% |
| MSFT | 7d | 12 | 25.0% |
| NVDA | 1d | 16 | 43.8% |
| NVDA | 7d | 12 | 33.3% |

## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)

| Predetto \ Reale | UP | DOWN | FLAT |
|---|---|---|---|
| UP | 9 | 13 | 18 |
| DOWN | 0 | 0 | 0 |
| FLAT | 11 | 6 | 26 |

## Calibrazione (confidence dichiarata vs accuratezza reale)

| Fascia confidence | N | Accuratezza |
|---|---|---|
| bassa (0-49) | 14 | 85.7% |
| media (50-74) | 59 | 33.9% |
| alta (75-100) | 10 | 30.0% |

## Probabilità (Brier Score, Log Loss)

- Brier Score: **0.4892** (n=12; range 0-2, più basso è meglio)
- Log Loss: **0.837** (n=12; più basso è meglio)
- Riferimento "non informativo" (probabilità sempre 33.3%/33.3%/33.3%): Brier 0.667, Log Loss 1.099 — l'agente deve fare meglio di questo per aggiungere valore.
- 71 previsioni valutate sono precedenti all'introduzione delle probabilità (2026-09-18) ed escluse da queste due metriche.

## Accuratezza per versione del prompt

Cambiare il prompt cambia l'esperimento: un unico numero di accuratezza
sopra versioni diverse nasconderebbe l'effetto del cambio. Le versioni sono
descritte in `src/config.py` (`PROMPT_VERSION`).

| Versione | N | Accuratezza |
|---|---|---|
| v1 | 66 | 33.3% |
| v2 | 17 | 76.5% |

## Confronto con baseline naive

- Random (3 classi equiprobabili): 33.3%
- Persistenza (ripete l'ultimo esito reale osservato): 63.6% (n=77)
- Classe più frequente (frequenza storica su decenni di prezzi, pesata sullo stesso mix asset/orizzonte): 45.8% (n=83)
- **Agente AI: 42.2%**

> La baseline "classe più frequente" è la più dura delle tre: è
> l'accuratezza di chi prevede sempre la stessa classe senza
> guardare né prezzi né notizie. Batterla è il minimo perché
> l'agente stia aggiungendo qualcosa. Dettaglio per asset e
> orizzonte in `data/baseline.json` (rigenerabile con
> `python -m src.baseline_run`).

