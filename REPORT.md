# Report accuratezza — aggiornato al 2026-09-30T20:30:09.997312+00:00

**Previsioni valutate: 107 — accuratezza complessiva: 46.7%**

## Per asset / orizzonte

| Asset | Orizzonte | N | Accuratezza |
|---|---|---|---|
| AAPL | 1d | 20 | 50.0% |
| AAPL | 7d | 16 | 62.5% |
| MSFT | 1d | 19 | 42.1% |
| MSFT | 7d | 16 | 25.0% |
| NVDA | 1d | 20 | 50.0% |
| NVDA | 7d | 16 | 50.0% |

## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)

| Predetto \ Reale | UP | DOWN | FLAT |
|---|---|---|---|
| UP | 9 | 13 | 18 |
| DOWN | 0 | 0 | 0 |
| FLAT | 18 | 8 | 41 |

## Calibrazione (confidence dichiarata vs accuratezza reale)

| Fascia confidence | N | Accuratezza |
|---|---|---|
| bassa (0-49) | 38 | 71.1% |
| media (50-74) | 59 | 33.9% |
| alta (75-100) | 10 | 30.0% |

## Probabilità (Brier Score, Log Loss)

- Brier Score: **0.558** (n=36; range 0-2, più basso è meglio)
- Log Loss: **0.9319** (n=36; più basso è meglio)
- Riferimento "non informativo" (probabilità sempre 33.3%/33.3%/33.3%): Brier 0.667, Log Loss 1.099 — l'agente deve fare meglio di questo per aggiungere valore.
- 71 previsioni valutate sono precedenti all'introduzione delle probabilità (2026-09-18) ed escluse da queste due metriche.

## Accuratezza per versione del prompt

Cambiare il prompt cambia l'esperimento: un unico numero di accuratezza
sopra versioni diverse nasconderebbe l'effetto del cambio. Le versioni sono
descritte in `src/config.py` (`PROMPT_VERSION`).

| Versione | N | Accuratezza |
|---|---|---|
| v1 | 66 | 33.3% |
| v2 | 41 | 68.3% |

## Confronto con baseline naive

- Random (3 classi equiprobabili): 33.3%
- Persistenza (ripete l'ultimo esito reale osservato): 60.4% (n=101)
- Classe più frequente (frequenza storica su decenni di prezzi, pesata sullo stesso mix asset/orizzonte): 45.8% (n=107)
- **Agente AI: 46.7%**

> La baseline "classe più frequente" è la più dura delle tre: è
> l'accuratezza di chi prevede sempre la stessa classe senza
> guardare né prezzi né notizie. Batterla è il minimo perché
> l'agente stia aggiungendo qualcosa. Dettaglio per asset e
> orizzonte in `data/baseline.json` (rigenerabile con
> `python -m src.baseline_run`).

