# Report accuratezza — aggiornato al 2026-09-21T23:16:12.369139+00:00

**Previsioni valutate: 65 — accuratezza complessiva: 36.9%**

## Per asset / orizzonte

| Asset | Orizzonte | N | Accuratezza |
|---|---|---|---|
| AAPL | 1d | 13 | 46.2% |
| AAPL | 7d | 9 | 66.7% |
| MSFT | 1d | 12 | 25.0% |
| MSFT | 7d | 9 | 22.2% |
| NVDA | 1d | 13 | 30.8% |
| NVDA | 7d | 9 | 33.3% |

## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)

| Predetto \ Reale | UP | DOWN | FLAT |
|---|---|---|---|
| UP | 9 | 13 | 15 |
| DOWN | 0 | 0 | 0 |
| FLAT | 7 | 6 | 15 |

## Calibrazione (confidence dichiarata vs accuratezza reale)

| Fascia confidence | N | Accuratezza |
|---|---|---|
| bassa (0-49) | 4 | 50.0% |
| media (50-74) | 52 | 36.5% |
| alta (75-100) | 9 | 33.3% |

## Probabilità (Brier Score, Log Loss)

- Brier Score: **0.567** (n=3; range 0-2, più basso è meglio)
- Log Loss: **0.9351** (n=3; più basso è meglio)
- Riferimento "non informativo" (probabilità sempre 33.3%/33.3%/33.3%): Brier 0.667, Log Loss 1.099 — l'agente deve fare meglio di questo per aggiungere valore.
- 62 previsioni valutate sono precedenti all'introduzione delle probabilità (2026-09-18) ed escluse da queste due metriche.

## Accuratezza per versione del prompt

Cambiare il prompt cambia l'esperimento: un unico numero di accuratezza
sopra versioni diverse nasconderebbe l'effetto del cambio. Le versioni sono
descritte in `src/config.py` (`PROMPT_VERSION`).

| Versione | N | Accuratezza |
|---|---|---|
| v1 | 60 | 36.7% |
| v2 | 5 | 40.0% |

## Confronto con baseline naive

- Random (3 classi equiprobabili): 33.3%
- Persistenza (ripete l'ultimo esito reale osservato): 64.4% (n=59)
- Classe più frequente (frequenza storica su decenni di prezzi, pesata sullo stesso mix asset/orizzonte): 45.8% (n=65)
- **Agente AI: 36.9%**

> La baseline "classe più frequente" è la più dura delle tre: è
> l'accuratezza di chi prevede sempre la stessa classe senza
> guardare né prezzi né notizie. Batterla è il minimo perché
> l'agente stia aggiungendo qualcosa. Dettaglio per asset e
> orizzonte in `data/baseline.json` (rigenerabile con
> `python -m src.baseline_run`).

