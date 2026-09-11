# Report accuratezza — aggiornato al 2026-09-11T08:16:01.639330+00:00

**Previsioni valutate: 18 — accuratezza complessiva: 16.7%**

## Per asset / orizzonte

| Asset | Orizzonte | N | Accuratezza |
|---|---|---|---|
| AAPL | 1d | 5 | 20.0% |
| AAPL | 7d | 1 | 0.0% |
| MSFT | 1d | 5 | 20.0% |
| MSFT | 7d | 1 | 0.0% |
| NVDA | 1d | 5 | 20.0% |
| NVDA | 7d | 1 | 0.0% |

## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)

| Predetto \ Reale | UP | DOWN | FLAT |
|---|---|---|---|
| UP | 1 | 8 | 4 |
| DOWN | 0 | 0 | 0 |
| FLAT | 0 | 3 | 2 |

## Calibrazione (confidence dichiarata vs accuratezza reale)

| Fascia confidence | N | Accuratezza |
|---|---|---|
| bassa (0-49) | 0 | 0.0% |
| media (50-74) | 15 | 20.0% |
| alta (75-100) | 3 | 0.0% |

## Confronto con baseline naive

- Random (3 classi equiprobabili): 33.3%
- Persistenza (ripete l'ultimo esito reale osservato): 50.0% (n=12)
- **Agente AI: 16.7%**

