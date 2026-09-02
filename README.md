# Agente predittivo AI — NVDA, MSFT & AAPL

Esperimento reale (non un backtest) di previsione AI sui mercati finanziari.
L'agente raccoglie dati reali, produce previsioni classificate su più
orizzonti temporali, le salva in modo immutabile e, dopo che l'orizzonte è
trascorso, confronta automaticamente previsione e risultato reale per
costruire uno storico di accuratezza verificabile.

**Obiettivo del progetto**: misurare quanto è realmente accurata un'AI nel
prevedere la direzione del prezzo, non generare segnali di trading.

## Asset

- **NVDA** — NVIDIA Corporation
- **MSFT** — Microsoft Corporation
- **AAPL** — Apple Inc.

SPY (ETF, tracciato inizialmente) è stato rimosso dal paniere attivo su
richiesta: il suo storico reale (`data/spy/`) resta nel repo per non
perdere previsioni ed esiti già registrati, ma non riceve più nuove
previsioni.

## Orizzonti (fase 1)

1 giorno, 7 giorni, 1 mese. Orizzonti intraday (6h/4h/1h) pianificati per
una fase 2 successiva.

## Come funziona

1. **`predict.yml`** (GitHub Actions, scheduled) raccoglie prezzo, news,
   fondamentali e dati macro da fonti gratuite, calcola una soglia di
   volatilità storica per distinguere UP/DOWN/FLAT, chiama il modello
   Claude per generare una previsione con confidence, e la registra in
   `data/<asset>/predictions.jsonl` come riga append-only con hash-chain.
2. **`evaluate.yml`** (scheduled, giornaliero) controlla `data/pending.json`
   per le previsioni il cui orizzonte è scaduto, recupera il prezzo reale,
   calcola l'esito (corretto/errato) usando **la stessa soglia di
   volatilità congelata al momento della previsione** (mai ricalcolata a
   posteriori, per evitare look-ahead bias), lo appende a
   `data/<asset>/outcomes.jsonl` e rigenera `REPORT.md` con le statistiche
   di accuratezza.

## Fonti dati (tutte gratuite, nessun abbonamento)

| Categoria | Primaria | Fallback |
|---|---|---|
| Prezzo | Yahoo Finance (endpoint pubblico) | Twelve Data → Finnhub |
| News | Finnhub News | Alpha Vantage Sentiment → GDELT |
| Fondamentali | SEC EDGAR | Alpha Vantage |
| Macro | FRED (tassi 10Y/2Y, spread curva, CPI, disoccupazione, VIX, indice dollaro) | — |

Oltre a prezzo/news/fondamentali/macro, ogni previsione include anche
indicatori tecnici calcolati da OHLCV gratuito (`src/technicals.py`), senza
bisogno di nessuna API in più: On-Balance Volume (trend
accumulazione/distribuzione), Chaikin Money Flow, forza relativa e beta
rispetto all'S&P 500 (SPY usato solo come benchmark, non più come asset
attivo), medie mobili SMA 50/200 ed EMA 9/21 (trend di fondo e di breve
termine), RSI 14, MACD (12/26/9), ATR 14 (volatilità media giornaliera in
%), Bande di Bollinger (%B), distanza da massimo/minimo a 52 settimane e
volume relativo rispetto alla propria media recente. Anche il sentiment
delle news (-1..+1, quando la fonte è Alpha Vantage) viene incluso nel
prompt: dato già raccolto, prima scartato.

## Secret richiesti (repo → Settings → Secrets and variables → Actions)

- `FRED_API_KEY`
- `ALPHA_VANTAGE_KEY`
- `TWELVE_DATA_KEY`
- `FINNHUB_KEY`
- `ANTHROPIC_API_KEY`

## Tetto di spesa AI

Oltre al limite impostato manualmente in console.anthropic.com, il codice
applica un tetto indipendente (`src/budget.py`): numero massimo di chiamate
al modello per giorno e `max_tokens` per chiamata. Se il tetto viene
superato, lo slot di previsione viene saltato e loggato — non viene mai
generata una previsione "finta" per aggirare il limite.

## Integrità dello storico

Ogni file `predictions.jsonl` / `outcomes.jsonl` è una catena di record
hash-linked (append-only): ogni riga contiene l'hash della riga precedente
e il proprio hash. Qualsiasi modifica retroattiva ai dati rompe la catena
ed è immediatamente rilevabile ricalcolandola (`src/storage.py` include la
funzione di verifica).

## Esecuzione manuale / test

Entrambi i workflow supportano `workflow_dispatch` con input `dry_run`
(default `true`): esegue l'intera pipeline (raccolta dati, calcolo,
eventuale chiamata al modello) ma non scrive nulla su `data/`, utile per
verificare che tutto funzioni prima di affidarsi allo scheduler automatico.

## Note

- Nessuna raccomandazione di investimento: l'unico scopo è misurare
  l'accuratezza predittiva dell'AI nel tempo.
- I dati di prezzo usati sono "delayed" (~15 min), coerente con l'uso di
  sole fonti gratuite — accettabile per orizzonti ≥ 1 giorno.
