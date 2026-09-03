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
   Un solo slot al giorno (16:30 ET, dopo la chiusura — `src/config.py:
   PREDICTION_SLOTS_ET`)
   genera tutti e 3 gli orizzonti (1g/7g/1m) per tutti gli asset:
   rigenerarli più volte nello stesso giorno cambiava pochissimo il
   risultato per 7g/1m (prezzo di partenza quasi identico a poche ore di
   distanza) e triplicava senza motivo chiamate AI e quota sulle fonti
   dati gratuite.
2. **`evaluate.yml`** (scheduled, giornaliero) controlla `data/pending.json`
   per le previsioni il cui orizzonte è scaduto, recupera il prezzo reale,
   calcola l'esito (corretto/errato) usando **la stessa soglia di
   volatilità congelata al momento della previsione** (mai ricalcolata a
   posteriori, per evitare look-ahead bias), lo appende a
   `data/<asset>/outcomes.jsonl` e rigenera `REPORT.md` con le statistiche
   di accuratezza.

La soglia di volatilità (banda FLAT) è basata sull'ATR% a 14 giorni
(`src/volatility.py`), scalato per la radice dei giorni di trading
dell'orizzonte — più reattivo a un cambio di regime di volatilità e include
i gap overnight, a differenza di una deviazione standard chiusura-chiusura
a finestra fissa usata in una versione precedente.

> **Nota storica (2026-09-02)**: lo stimatore della soglia è cambiato da
> deviazione standard a ATR. Lo storico precedente (poche previsioni/esiti
> reali) è stato azzerato invece di essere mantenuto, perché le soglie
> congelate con la vecchia formula non sarebbero più state confrontabili
> con quelle nuove nello stesso report. Resta comunque recuperabile nella
> cronologia Git (commit `4dd63e2` e precedenti su `Main`).

> **Nota storica (2026-09-03)**: `VOLATILITY_K` ricalibrato da 0.5 a 0.4
> (prima ricalibrazione manuale, non ancora basata sulla tabella di
> calibrazione — con 1-2 giorni di dati reali era ancora troppo presto) e
> slot di previsione spostato da 15:45 a 16:30 ET, dopo la chiusura invece
> che 15 minuti prima: il prezzo di partenza ora coincide esattamente con
> quello poi usato in valutazione (a mercato aperto i due potevano
> differire leggermente), e il modello vede eventuali utili trimestrali
> pubblicati alla campana (AMC). Storico azzerato di nuovo insieme al
> cambio, stesso motivo del precedente. Recuperabile su `Main` fino al
> commit `aa1cb1f`.

## Fonti dati (tutte gratuite, nessun abbonamento)

| Categoria | Fonte | Fallback | Note |
|---|---|---|---|
| Prezzo (OHLCV giornaliero) | Yahoo Finance (endpoint pubblico) | Twelve Data → Finnhub | nessuna key per la primaria |
| News | Finnhub News | Alpha Vantage Sentiment → GDELT | sentiment -1..+1 quando la fonte è Alpha Vantage |
| Fondamentali | SEC EDGAR (XBRL company facts) | Alpha Vantage | nessuna key per la primaria |
| Consenso analisti | Alpha Vantage (EARNINGS_ESTIMATES + EARNINGS_CALENDAR) | — | 1 fetch/giorno per asset (cache), stima EPS + revisioni + prossimo bilancio |
| Transazioni insider | SEC EDGAR (Form 4) | — | nessuna key; solo transazioni discrezionali (P/S) |
| Macro | FRED | — | 9 serie: tassi 10Y/2Y, spread di curva, CPI, disoccupazione, VIX, indice dollaro, fed funds rate, fiducia dei consumatori |
| Indicatori tecnici | calcolati localmente da OHLCV già scaricato | — | nessuna fonte/key in più |
| Benchmark di calcolo | Yahoo Finance: SPY (mercato), SMH/XLK (settore) | — | solo per forza relativa/beta, non ricevono previsioni |

**Indicatori tecnici** (`src/technicals.py`, tutti derivati dall'OHLCV già
scaricato, nessuna API in più): On-Balance Volume (trend
accumulazione/distribuzione), Chaikin Money Flow, forza relativa e beta
rispetto all'S&P 500 e al proprio settore (SMH per NVDA, XLK per
MSFT/AAPL), medie mobili SMA 50/200 ed EMA 9/21, RSI 14, MACD (12/26/9),
ATR 14 (volatilità media giornaliera, usato anche come base della soglia
FLAT), Bande di Bollinger (%B), distanza da massimo/minimo a 52 settimane,
volume relativo rispetto alla propria media recente. Forza relativa e beta
confrontano le due serie di prezzo per **data in comune**, non per indice
posizionale: due ticker distinti non hanno sempre lo stesso identico
calendario di barre (una fonte gratuita può mancare un singolo giorno per
un titolo e non per l'altro — osservato realmente tra NVDA e SMH).
Allineare per indice avrebbe sfasato silenziosamente tutto il confronto
dopo un giorno mancante.

**Consenso analisti** (`fetch_analyst_outlook()` in `fundamentals.py`):
prossima data di bilancio, stima EPS media, numero di analisti e revisioni
al rialzo/ribasso negli ultimi 30gg. Aggiornato al massimo una volta al
giorno per asset (cache in
`data/_state/analyst_outlook_<asset>_<data>.json`), per restare ben sotto
il tetto gratuito di 25 chiamate/giorno di Alpha Vantage (condiviso con
fondamentali/news di riserva).

**Transazioni insider** (`fetch_insider_summary()` in
`src/data_sources/insider.py`): acquisti/vendite sul mercato aperto di
dirigenti, amministratori e azionisti >10% negli ultimi 30gg. Contano
solo le transazioni discrezionali (codice P/S): escluse deliberatamente
vesting di RSU, esercizio di opzioni, ritenute fiscali e donazioni (codici
A/F/M/G/C), che avvengono su calendari predeterminati o sono automatiche e
non riflettono una scelta dell'insider sul titolo.

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

## Robustezza & osservabilità

- **Retry di rete**: tutte le chiamate alle fonti dati (`src/data_sources/http.py`)
  ritentano una volta in caso di errore di rete (timeout, DNS, connessione
  caduta) prima di considerare la fonte non disponibile e passare al
  fallback successivo. Una risposta HTTP arrivata (anche un errore come
  429/500) non viene ritentata: è già un esito definitivo.
- **Dati mancanti nell'ultimo segnale**: se per una previsione recente una
  fonte opzionale (news, macro, fondamentali, stime analisti) non era
  disponibile, la dashboard lo segnala con una nota sotto il nome
  dell'asset — nessuna previsione "silenziosamente" più povera di dati
  senza che sia visibile.
- **Notifica su fallimento run**: se `predict.yml` o `evaluate.yml` falliscono
  con un errore non gestito (non i normali skip per singolo asset/orizzonte,
  quelli sono attesi), viene inviato un messaggio Telegram con il link al
  run. Richiede i secret `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` nel repo:
  se non sono configurati, la notifica viene saltata senza far fallire il job.
- **Isolamento per asset nella dashboard**: il rendering di ciascuna card
  (`index.html`) è racchiuso in un `try/catch` indipendente — un errore su
  un asset (es. Chart.js non caricato dal CDN) non blocca più il rendering
  degli asset successivi.

## Dashboard: range FLAT e filtro per orizzonte

Il dettaglio di ogni previsione (tocca una riga in "Ultimi Risultati
Valutati"/"Ultimi Segnali Generati") mostra ora l'intervallo di prezzo
effettivo entro cui la previsione resta FLAT (es. "tra $223.72 e $229.65"),
calcolato da `price_at_generation` e `volatility_threshold_pct` già salvati
— nessun dato nuovo, solo più leggibile della sola percentuale ±.

Un filtro per orizzonte (Tutti/1 giorno/7 giorni/1 mese) sopra le card
degli asset ricalcola, senza nuove chiamate di rete, l'accuratezza, i
grafici e le tabelle di ciascun asset limitandoli all'orizzonte scelto —
utile per capire se l'AI è più affidabile su previsioni giornaliere,
settimanali o mensili.

Il pannello informativo ("Che dati analizza l'AI?") mostra anche gli orari
delle previsioni convertiti in ora italiana, ricalcolati dinamicamente ad
ogni caricamento a partire dagli slot in ora US/Eastern
(`src/config.py: PREDICTION_SLOTS_ET`) — restano corretti anche nelle
settimane in cui USA e Italia non hanno ancora fatto entrambe il cambio
tra ora legale e solare (offset non sempre fisso a 6 ore).

## Esecuzione manuale / test

Entrambi i workflow supportano `workflow_dispatch` con input `dry_run`
(default `true`): esegue l'intera pipeline (raccolta dati, calcolo,
eventuale chiamata al modello) ma non scrive nulla su `data/`, utile per
verificare che tutto funzioni prima di affidarsi allo scheduler automatico.
Fa eccezione la chiamata Alpha Vantage per le stime analisti: in un
dry-run senza cache del giorno viene saltata del tutto (nessun fetch,
nessuna cache scritta), per non consumare la quota gratuita di 25
richieste/giorno che serve ai run reali — se la cache del giorno esiste
già, viene comunque riusata per un test realistico a costo zero.

## Note

- Nessuna raccomandazione di investimento: l'unico scopo è misurare
  l'accuratezza predittiva dell'AI nel tempo.
- I dati di prezzo usati sono "delayed" (~15 min), coerente con l'uso di
  sole fonti gratuite — accettabile per orizzonti ≥ 1 giorno.
