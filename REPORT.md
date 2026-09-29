# Report accuratezza — aggiornato al 2026-09-29T10:05:14.009008+00:00

**Previsioni valutate: 98 — accuratezza complessiva: 44.9%**

## Per asset / orizzonte

| Asset | Orizzonte | N | Accuratezza |
|---|---|---|---|
| AAPL | 1d | 18 | 55.6% |
| AAPL | 7d | 15 | 60.0% |
| MSFT | 1d | 17 | 35.3% |
| MSFT | 7d | 15 | 26.7% |
| NVDA | 1d | 18 | 44.4% |
| NVDA | 7d | 15 | 46.7% |

## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)

| Predetto \ Reale | UP | DOWN | FLAT |
|---|---|---|---|
| UP | 9 | 13 | 18 |
| DOWN | 0 | 0 | 0 |
| FLAT | 16 | 7 | 35 |

## Calibrazione (confidence dichiarata vs accuratezza reale)

| Fascia confidence | N | Accuratezza |
|---|---|---|
| bassa (0-49) | 29 | 72.4% |
| media (50-74) | 59 | 33.9% |
| alta (75-100) | 10 | 30.0% |

## Probabilità (Brier Score, Log Loss)

- Brier Score: **0.5497** (n=27; range 0-2, più basso è meglio)
- Log Loss: **0.9179** (n=27; più basso è meglio)
- Riferimento "non informativo" (probabilità sempre 33.3%/33.3%/33.3%): Brier 0.667, Log Loss 1.099 — l'agente deve fare meglio di questo per aggiungere valore.
- 71 previsioni valutate sono precedenti all'introduzione delle probabilità (2026-09-18) ed escluse da queste due metriche.

## Accuratezza per versione del prompt

Cambiare il prompt cambia l'esperimento: un unico numero di accuratezza
sopra versioni diverse nasconderebbe l'effetto del cambio. Le versioni sono
descritte in `src/config.py` (`PROMPT_VERSION`).

| Versione | N | Accuratezza |
|---|---|---|
| v1 | 66 | 33.3% |
| v2 | 32 | 68.8% |

## Confronto con baseline naive

- Random (3 classi equiprobabili): 33.3%
- Persistenza (ripete l'ultimo esito reale osservato): 60.9% (n=92)
- Classe più frequente (frequenza storica su decenni di prezzi, pesata sullo stesso mix asset/orizzonte): 45.7% (n=98)
- **Agente AI: 44.9%**

> La baseline "classe più frequente" è la più dura delle tre: è
> l'accuratezza di chi prevede sempre la stessa classe senza
> guardare né prezzi né notizie. Batterla è il minimo perché
> l'agente stia aggiungendo qualcosa. Dettaglio per asset e
> orizzonte in `data/baseline.json` (rigenerabile con
> `python -m src.baseline_run`).

