# Agente predittivo AI — SPY & AAPL

Esperimento reale (non un backtest) di previsione AI sui mercati finanziari.
L'agente raccoglie dati reali, produce previsioni classificate su più
orizzonti temporali, le salva in modo immutabile e, dopo che l'orizzonte è
trascorso, confronta automaticamente previsione e risultato reale per
costruire uno storico di accuratezza verificabile.

**Obiettivo del progetto**: misurare quanto è realmente accurata un'AI nel
prevedere la direzione del prezzo, non generare segnali di trading.

## Asset

- **SPY** — SPDR S&P 500 ETF Trust
- **AAPL** — Apple Inc.
- **NVDA** — NVIDIA Corporation
- **MSFT** — Microsoft Corporation

## Indicatori Tecnici e Calcolo delle Previsioni

Per aumentare l'accuratezza delle previsioni, l'agente calcola e analizza i seguenti indicatori tecnici basati sulle serie storiche dei prezzi:

1. **Relative Strength Index (RSI - 14 periodi)**:
   $$\text{RSI} = 100 - \left( \frac{100}{1 + \frac{\text{Media Guadagni}}{\text{Media Perdite}}} \right)$$
   Misure di ipercomprato (>70) e ipervenduto (<30).

2. **MACD (Moving Average Convergence Divergence - 12, 26, 9)**:
   - Linea MACD: $\text{EMA}_{12} - \text{EMA}_{26}$
   - Linea di Segnale: $\text{EMA}_9(\text{MACD})$
   - Istogramma: $\text{MACD} - \text{Linea di Segnale}$

3. **Medie Mobili Semplici (SMA 50 e SMA 200)**:
   - Identificazione del trend di medio e lungo termine e intersezioni (Golden Cross / Death Cross).

4. **Bande di Bollinger (20 periodi, 2 deviazioni standard)**:
   - Banda Superiore/Inferiore: $\text{SMA}_{20} \pm 2 \times \sigma_{20}$
   - Misura della volatilità a breve termine e livelli dinamici di supporto/resistenza.

### Soglia di Volatilità e Definizione delle Classi (UP / DOWN / FLAT)

Per evitare previsioni di movimento insignificanti, la classificazione usa una soglia basata sulla volatilità storica annua $\sigma_{ann}$:
$$\text{Soglia}(t) = K \times \left( \frac{\sigma_{ann}}{\sqrt{252}} \right) \times \sqrt{t}$$
- Se $\frac{P_{pred} - P_{init}}{P_{init}} > \text{Soglia}(t) \implies \mathbf{UP}$
- Se $\frac{P_{pred} - P_{init}}{P_{init}} < -\text{Soglia}(t) \implies \mathbf{DOWN}$
- Altrimenti $\implies \mathbf{FLAT}$

### Prompting e Ragionamento AI (Chain-of-Thought)

Il modello Claude riceve tutti gli indicatori tecnici, le news recenti, il sentiment e i dati macroeconomici (FRED) e segue un processo di ragionamento guidato (Chain-of-Thought):
1. **Analisi Trend e Momentum**: RSI, SMA 50/200, MACD.
2. **Analisi Volatilità e Bande**: Posizione rispetto alle Bande di Bollinger.
3. **Sentimento e Macro**: Impatto delle notizie recenti e dei tassi/PIL.
4. **Calibrazione della Confidenza**: Valutazione della convergenza tra i vari fattori.

## Tecniche avanzate per aumentare l'Accuratezza delle Previsioni

Per migliorare ulteriormente le prestazioni predittive dell'agente:

1. **Classificazione dei Regimi di Mercato (Market Regime Filter)**:
   - Distinguere mercati in trend forte (Trending / High Volatility) da mercati laterali (Sideways / Consolidation). Nei periodi laterali le rotture tecniche generano falsi segnali; adattare la soglia di confidenza in base al regime aumenta la precisione.

2. **Sentimento Quantitativo Multi-Fonte**:
   - Integrare social sentiment (es. StockTwits, Reddit financial subreddits) pesato per il volume di menzioni e l'affidabilità delle fonti.

3. **Correlazione Multi-Timeframe e Cross-Asset**:
   - Verificare l'allineamento dei segnali su orizzonti multipli (es. 1D vs 7D) e con asset correlati (es. rendimenti dei Treasury 10Y, indice VIX, dollaro DXY).

4. **Calendario Economico ed Event Risk Weighting**:
   - Aumentare l'incertezza e ridurre la confidenza automatica in prossimità di eventi macroeconomici chiave (decisioni tassi FOMC, rilascio CPI, pubblicazione trimestrali Earnings Reports).

5. **Calibrazione della Confidenza (Ensemble / Multi-Sampling)**:
   - Eseguire multiple generazioni con temperatura non nulla (es. self-consistency sampling) e mediare le probabilità predittive per eliminare le allucinazioni isolate.

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
| Macro | FRED | — |

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
