# Report accuratezza — aggiornato al 2026-09-15T22:53:43.192674+00:00

**Previsioni valutate: 39 — accuratezza complessiva: 28.2%**

## Per asset / orizzonte

| Asset | Orizzonte | N | Accuratezza |
|---|---|---|---|
| AAPL | 1d | 9 | 33.3% |
| AAPL | 7d | 4 | 75.0% |
| MSFT | 1d | 9 | 22.2% |
| MSFT | 7d | 4 | 0.0% |
| NVDA | 1d | 9 | 33.3% |
| NVDA | 7d | 4 | 0.0% |

## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)

| Predetto \ Reale | UP | DOWN | FLAT |
|---|---|---|---|
| UP | 5 | 12 | 9 |
| DOWN | 0 | 0 | 0 |
| FLAT | 2 | 5 | 6 |

## Calibrazione (confidence dichiarata vs accuratezza reale)

| Fascia confidence | N | Accuratezza |
|---|---|---|
| bassa (0-49) | 0 | 0.0% |
| media (50-74) | 33 | 24.2% |
| alta (75-100) | 6 | 50.0% |

## Confronto con baseline naive

- Random (3 classi equiprobabili): 33.3%
- Persistenza (ripete l'ultimo esito reale osservato): 57.6% (n=33)
- **Agente AI: 28.2%**

