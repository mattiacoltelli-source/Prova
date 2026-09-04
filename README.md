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
   Un solo slot al giorno (7:00 ET, prima dell'apertura — `src/config.py:
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
3. **`snapshot.yml`** (scheduled, 3 volte al giorno durante l'orario di
   mercato) prende un'istantanea del prezzo corrente per ogni asset — non
   un ticker live, stessa fonte già usata per `price_at_generation`,
   nessuna chiave nuova — e la salva in `data/<asset>/snapshot.json`
   (sovrascritta ad ogni run, non append-only: non è un dato storico da
   preservare). La dashboard la usa per mostrare, accanto al prezzo di
   riferimento, "a che punto è" la previsione a 1 giorno prima ancora che
   l'orizzonte scada — un confronto istantaneo con la stessa soglia
   congelata, non una valutazione (quella resta compito di `evaluate.yml`
   sull'orizzonte completo).

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
> calibrazione — con 1-2 giorni di dati reali era ancora troppo presto). Lo
> slot di previsione, partito da 15:45 ET (prima della chiusura), è stato
> spostato lo stesso giorno prima a 16:30 ET (dopo la chiusura), poi a
> 8:00 ET e infine a **7:00 ET** (prima dell'apertura delle 9:30 ET) — le
> ultime configurazioni intermedie non hanno mai prodotto una previsione
> reale, quindi nessun reset aggiuntivo per i cambi successivi al primo. Il
> prezzo di `prices.fetch_latest_price()` resta congelato all'ultima
> chiusura per tutto l'intervallo tra le due sessioni (16:00 ET di ieri -
> 9:30 ET di oggi), quindi uno slot pre-apertura usa lo stesso prezzo di
> partenza di uno post-chiusura ma vede in più le notizie overnight e gli
> utili pubblicati prima dell'apertura (BMO, "before market open") — con
> la stessa logica che aveva già motivato lo spostamento da pre- a
> post-chiusura per gli utili AMC. 7:00 ET invece di 8:00: un'ora in più
> di margine di recupero (150 minuti contro 90) a fronte di una probabilità
> leggermente più alta di non aver ancora visto gli utili BMO pubblicati a
> ridosso dell'apertura. Ha richiesto anche
> un fix in `predict_run.py` (`_reference_price()`/`_target_at()`): con il
> prezzo congelato pre-apertura, l'orizzonte di ogni previsione va
> ancorato alla data di quella chiusura, non all'orario reale di
> esecuzione dello script, altrimenti l'orizzonte "1g" raddoppierebbe
> silenziosamente a due giorni di trading. Storico azzerato insieme al
> cambio, stesso motivo del precedente. Recuperabile su `Main` fino al
> commit `aa1cb1f`.

> **Bug reale trovato in produzione (2026-09-03)**: il fix sopra copriva
> solo il caso previsto (script partito prima delle 9:30 ET). Un run
> manuale di recupero partito 1 minuto *dopo* l'apertura (9:31 ET, lo
> scheduler di GitHub non era scattato in tempo) ha usato come prezzo di
> riferimento un prezzo intraday di oggi — ma l'orizzonte veniva comunque
> ancorato a "oggi + 1 giorno", finendo per coprire il resto della
> sessione di oggi più l'intera sessione di domani, quasi due giorni di
> trading invece di uno. Riguarda solo le previsioni di NVDA/MSFT/AAPL
> generate quel giorno (`generated_at` 13:31 UTC) — non azzerate, l'entità
> della distorsione è nota e documentata qui, e resta comunque un
> confronto internamente coerente (stessa soglia, stesso prezzo, solo
> l'etichetta "1g" leggermente imprecisa per quel solo batch). Fix:
> `_reference_price()` ora usa sempre l'ultima chiusura storica REALE
> (mai un prezzo intraday, mai la barra parziale di oggi) come prezzo di
> riferimento, a prescindere da quando lo script gira — elimina la
> distinzione prima/dopo apertura invece di provare a mantenerla corretta
> in entrambi i casi.

> **Storico azzerato (2026-09-04)**, a differenza di quanto scritto nella
> nota precedente: il batch del 2026-09-03 13:31 UTC restava comunque
> percepibile come una previsione "1g" che si sovrapponeva a quella del
> giorno successivo — confuso da vedere in dashboard anche se
> internamente coerente, a prescindere dalla correttezza tecnica del
> confronto. Nessun esito era ancora stato valutato (0 righe in
> `outcomes.jsonl` per tutti e tre gli asset), quindi azzerare non ha
> fatto perdere alcuna accuratezza storica reale. Ripulito `predictions.jsonl`,
> `outcomes.jsonl`, `pending.json` e la cache in `data/_state/` per
> NVDA/MSFT/AAPL — SPY non toccato, è già storico archiviato a parte.
> Recuperabile su `Main` fino al commit `00ed2c4`.

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

Il pannello informativo include anche un link diretto alla pagina GitHub
Actions di `predict.yml`, per far partire una previsione manuale (protetta
dal login GitHub) nel caso quella automatica tardasse. "Run workflow" ha
già i default giusti per questo (`dry_run=false`, `force=true`): basta
premere il pulsante, senza toccare nulla. Sicuro in entrambe le direzioni
— le previsioni generate manualmente marcano lo slot del giorno come già
fatto (un run automatico in ritardo che arriva dopo non ne crea una
doppia), e viceversa `force` è comunque un no-op se lo slot di oggi è già
stato fatto (dallo scheduled o da un run manuale precedente), quindi un
tap ripetuto sul pulsante non genera mai un secondo giro di previsioni
reali duplicate.

**Estetica**: la dashboard usa una palette scura raffinata (bordi più
morbidi, ombre leggere al posto dei soli bordi piatti, raggi coerenti,
cifre allineate con `tabular-nums` su prezzi/statistiche/tabelle) —
verificata con la suite Playwright di `qa-agent` (30 test passati, nessuna
rottura) prima di andare in produzione. Le uniche emoji rimaste sono
quelle su cui quella suite si aggancia direttamente (⚠️ dati mancanti,
✅/❌ negli esiti); le altre sono state sostituite con icone SVG inline.

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
