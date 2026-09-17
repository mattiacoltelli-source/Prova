# Snapshot TradingView — 2026-09-17

Dati scaricati una volta sola da TradingView (MCP, account personale) e
committati qui. **Non è un feed**: nessun workflow li aggiorna, nessun
codice li rigenera. Sono una fotografia datata.

## Perché esistono

L'abbonamento TradingView scade a metà ottobre 2026. Questi file contengono
le sole cose che le fonti gratuite già integrate nel progetto **non danno**,
scaricate finché l'accesso era attivo. Una volta committati restano
disponibili per sempre, indipendentemente dall'abbonamento.

Criterio di selezione: scaricare da TradingView solo ciò che Yahoo, SEC
EDGAR, Finnhub, Alpha Vantage, GDELT e FRED non coprono. Tutto il resto
continua a passare dalle fonti gratuite, che restano la spina dorsale del
progetto.

## File

| File | Contenuto | Invecchia? |
|---|---|---|
| `fundamentals.json` | Fondamentali THK/Harmonic Drive (16 anni di bilanci annuali + trimestrali recenti), snapshot TTM di TER/VRT, rating analisti | Lentamente — i bilanci passati non cambiano più |
| `calendars.json` | Date trimestrali attese + calendario macro USA ad alta importanza | Earnings: fino alla prossima trimestrale. **Macro: scade il 2026-10-17** |
| `news_tokyo.json` | Titoli agganciati al simbolo per i due ticker Tokyo | Sì, sono notizie |

Solo metadati e valori aggregati: titoli, date, cifre di bilancio. Nessun
testo integrale di articoli.

## Il buco che chiudono

`src/config.py` documenta il problema: THK e Harmonic Drive sono quotate a
Tokyo, quindi **SEC EDGAR non le copre** e su piano gratuito
**Finnhub/Alpha Vantage non hanno né fondamentali né news** per quei ticker
— resta solo GDELT, che cerca per testo libero e non per simbolo. Per questo
i loro fondamentali erano inseriti a mano in `index.html` (fonte
stockanalysis.com) con scadenza automatica a 6 mesi.

`fundamentals.json` contiene gli stessi dati da fonte strutturata, più 16
anni di storico, crescita anno su anno, margini, rating analisti e range dei
target che l'inserimento manuale non aveva.

**`index.html` lo legge direttamente** (dal 2026-09-17): la costante
`ROBOTICS_FUNDAMENTALS` scritta a mano non esiste più. Le card costruiscono
un contenitore vuoto e una singola `fetch` lo riempie, così il resto della
catena di rendering resta sincrono.

## Verifiche fatte prima di committare

**Riscontro incrociato con i valori manuali** — dove i due si sovrappongono
coincidono, il che dà fiducia a entrambi:

| | Manuale (stockanalysis.com) | TradingView |
|---|---|---|
| TER EPS TTM | 7,29 | 7,2887 |
| TER ricavi TTM | 4,46 mld | 4.462.783.000 |
| VRT EPS TTM | 4,42 | 4,4194 |
| VRT target analisti | 338,15 | 339,178 |

**Coerenza interna** — serie annuali e trimestrali allineate ai rispettivi
label, somma della distribuzione buy/hold/sell uguale al totale analisti.

## Tre limiti trovati, da non dimenticare

1. **I price target dei ticker Tokyo sono esclusi.** TradingView stesso
   segnala `target_mismatch` su TSE:6481 e TSE:6324: il target è incoerente
   con il prezzo quotato, probabile disallineamento di valuta o unità nel
   feed. L'endpoint `financials` per THK restituiva comunque un target di
   8642 (+44%), che l'endpoint `forecasts` rifiuta di riportare. **Il valore
   non è propagato**: due endpoint della stessa fonte che si contraddicono
   sono un motivo sufficiente per non fidarsi di nessuno dei due.

2. **Il calendario earnings non copre Tokyo.** La chiamata con 7 simboli ne
   restituisce 5: THK e Harmonic Drive mancano. Le loro date vanno prese
   dalle news (Quartr e Reuters pubblicano i risultati) o dall'investor
   relations.

3. **I TTM di THK sono vuoti.** `get_financials` su TSE:6481 restituisce
   `null` su P/E, EPS, ricavi e margini TTM — mentre funzionano per
   TSE:6324. Per THK vanno usate le serie annuali/trimestrali, che sono
   complete.

## Rigenerare

Non è rigenerabile senza abbonamento TradingView attivo. Se serve
aggiornarlo dopo la scadenza, le alternative per singolo dato sono:

- **Fondamentali Tokyo**: EDINET (ufficiale, gratuito, ma richiede
  registrazione e parsing XBRL), oppure di nuovo inserimento manuale.
- **Date earnings**: investor relations delle società.
- **Calendario macro**: nessuna fonte gratuita equivalente per le date
  *programmate*. FRED (già integrato in `src/data_sources/macro.py`) dà i
  valori pubblicati, non il calendario in avanti.
