# Report accuratezza — aggiornato al 2026-09-18T08:27:42.424006+00:00

**Previsioni valutate: 51 — accuratezza complessiva: 35.3%**

## Per asset / orizzonte

| Asset | Orizzonte | N | Accuratezza |
|---|---|---|---|
| AAPL | 1d | 11 | 45.5% |
| AAPL | 7d | 6 | 83.3% |
| MSFT | 1d | 11 | 18.2% |
| MSFT | 7d | 6 | 16.7% |
| NVDA | 1d | 11 | 36.4% |
| NVDA | 7d | 6 | 16.7% |

## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)

| Predetto \ Reale | UP | DOWN | FLAT |
|---|---|---|---|
| UP | 8 | 13 | 10 |
| DOWN | 0 | 0 | 0 |
| FLAT | 4 | 6 | 10 |

## Calibrazione (confidence dichiarata vs accuratezza reale)

| Fascia confidence | N | Accuratezza |
|---|---|---|
| bassa (0-49) | 0 | 0.0% |
| media (50-74) | 45 | 33.3% |
| alta (75-100) | 6 | 50.0% |

## Confronto con baseline naive

- Random (3 classi equiprobabili): 33.3%
- Persistenza (ripete l'ultimo esito reale osservato): 60.0% (n=45)
- Classe più frequente (frequenza storica su decenni di prezzi, pesata sullo stesso mix asset/orizzonte): 46.0% (n=51)
- **Agente AI: 35.3%**

> La baseline "classe più frequente" è la più dura delle tre: è
> l'accuratezza di chi prevede sempre la stessa classe senza
> guardare né prezzi né notizie. Batterla è il minimo perché
> l'agente stia aggiungendo qualcosa. Dettaglio per asset e
> orizzonte in `data/baseline.json` (rigenerabile con
> `python -m src.baseline_run`).

