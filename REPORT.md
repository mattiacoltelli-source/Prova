# Report accuratezza — aggiornato al 2026-09-17T08:52:15.791776+00:00

**Previsioni valutate: 45 — accuratezza complessiva: 33.3%**

## Per asset / orizzonte

| Asset | Orizzonte | N | Accuratezza |
|---|---|---|---|
| AAPL | 1d | 10 | 40.0% |
| AAPL | 7d | 5 | 80.0% |
| MSFT | 1d | 10 | 20.0% |
| MSFT | 7d | 5 | 20.0% |
| NVDA | 1d | 10 | 40.0% |
| NVDA | 7d | 5 | 0.0% |

## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)

| Predetto \ Reale | UP | DOWN | FLAT |
|---|---|---|---|
| UP | 6 | 13 | 9 |
| DOWN | 0 | 0 | 0 |
| FLAT | 2 | 6 | 9 |

## Calibrazione (confidence dichiarata vs accuratezza reale)

| Fascia confidence | N | Accuratezza |
|---|---|---|
| bassa (0-49) | 0 | 0.0% |
| media (50-74) | 39 | 30.8% |
| alta (75-100) | 6 | 50.0% |

## Confronto con baseline naive

- Random (3 classi equiprobabili): 33.3%
- Persistenza (ripete l'ultimo esito reale osservato): 64.1% (n=39)
- **Agente AI: 33.3%**

