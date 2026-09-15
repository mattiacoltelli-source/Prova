# Report accuratezza — aggiornato al 2026-09-15T08:55:29.890633+00:00

**Previsioni valutate: 33 — accuratezza complessiva: 24.2%**

## Per asset / orizzonte

| Asset | Orizzonte | N | Accuratezza |
|---|---|---|---|
| AAPL | 1d | 8 | 25.0% |
| AAPL | 7d | 3 | 66.7% |
| MSFT | 1d | 8 | 25.0% |
| MSFT | 7d | 3 | 0.0% |
| NVDA | 1d | 8 | 25.0% |
| NVDA | 7d | 3 | 0.0% |

## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)

| Predetto \ Reale | UP | DOWN | FLAT |
|---|---|---|---|
| UP | 4 | 10 | 8 |
| DOWN | 0 | 0 | 0 |
| FLAT | 2 | 5 | 4 |

## Calibrazione (confidence dichiarata vs accuratezza reale)

| Fascia confidence | N | Accuratezza |
|---|---|---|
| bassa (0-49) | 0 | 0.0% |
| media (50-74) | 28 | 21.4% |
| alta (75-100) | 5 | 40.0% |

## Confronto con baseline naive

- Random (3 classi equiprobabili): 33.3%
- Persistenza (ripete l'ultimo esito reale osservato): 55.6% (n=27)
- **Agente AI: 24.2%**

