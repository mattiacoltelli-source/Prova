# Report accuratezza — aggiornato al 2026-09-09T21:45:20.525962+00:00

**Previsioni valutate: 12 — accuratezza complessiva: 8.3%**

## Per asset / orizzonte

| Asset | Orizzonte | N | Accuratezza |
|---|---|---|---|
| AAPL | 1d | 4 | 0.0% |
| MSFT | 1d | 4 | 0.0% |
| NVDA | 1d | 4 | 25.0% |

## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)

| Predetto \ Reale | UP | DOWN | FLAT |
|---|---|---|---|
| UP | 0 | 6 | 3 |
| DOWN | 0 | 0 | 0 |
| FLAT | 0 | 2 | 1 |

## Calibrazione (confidence dichiarata vs accuratezza reale)

| Fascia confidence | N | Accuratezza |
|---|---|---|
| bassa (0-49) | 0 | 0.0% |
| media (50-74) | 10 | 10.0% |
| alta (75-100) | 2 | 0.0% |

## Confronto con baseline naive

- Random (3 classi equiprobabili): 33.3%
- Persistenza (ripete l'ultimo esito reale osservato): 55.6% (n=9)
- **Agente AI: 8.3%**

