# Report accuratezza — aggiornato al 2026-09-11T22:34:25.780348+00:00

**Previsioni valutate: 27 — accuratezza complessiva: 29.6%**

## Per asset / orizzonte

| Asset | Orizzonte | N | Accuratezza |
|---|---|---|---|
| AAPL | 1d | 6 | 33.3% |
| AAPL | 7d | 3 | 66.7% |
| MSFT | 1d | 6 | 33.3% |
| MSFT | 7d | 3 | 0.0% |
| NVDA | 1d | 6 | 33.3% |
| NVDA | 7d | 3 | 0.0% |

## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)

| Predetto \ Reale | UP | DOWN | FLAT |
|---|---|---|---|
| UP | 4 | 10 | 6 |
| DOWN | 0 | 0 | 0 |
| FLAT | 0 | 3 | 4 |

## Calibrazione (confidence dichiarata vs accuratezza reale)

| Fascia confidence | N | Accuratezza |
|---|---|---|
| bassa (0-49) | 0 | 0.0% |
| media (50-74) | 22 | 27.3% |
| alta (75-100) | 5 | 40.0% |

## Confronto con baseline naive

- Random (3 classi equiprobabili): 33.3%
- Persistenza (ripete l'ultimo esito reale osservato): 57.1% (n=21)
- **Agente AI: 29.6%**

