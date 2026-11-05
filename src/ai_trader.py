"""Esperimento di trading automatico AI su un universo più ampio dei soli
ASSETS: segnale ibrido (previsioni già esistenti + due modelli Anthropic
di costo diverso), decisioni BUY/SELL/HOLD per titolo, un conto Alpaca
paper dedicato, 6 mesi fissi.

Modulo di SOLA DECISIONE: non invia ordini da solo (vedi ai_trader_run.py
per l'orchestrazione — apertura/chiusura posizioni, stop-loss, snapshot).
Separato da predictor.py (previsioni UP/DOWN/FLAT con probabilità, per
report.py) perché qui l'output è un'azione discreta (BUY/SELL/HOLD), non
una distribuzione di probabilità da valutare col Brier Score.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from zoneinfo import ZoneInfo

import anthropic

from . import budget, config, data_health, market_scanner, storage, technicals
from .data_sources import prices


class DecisionParseError(RuntimeError):
    pass


def tradeable_universe() -> list[str]:
    """SCANNER_STOCKS meno i ticker non tradabili su Alpaca (broker USA —
    vedi AI_TRADER_EXCLUDED_TICKERS in config.py). Le crypto di
    SCANNER_CRYPTO restano fuori per ora (formato ticker diverso)."""
    return [s for s in config.SCANNER_STOCKS if s not in config.AI_TRADER_EXCLUDED_TICKERS]


_NY = ZoneInfo("America/New_York")


def last_session_close_utc(now: dt.datetime) -> dt.datetime:
    """Chiusura (16:00 New York, ora legale/solare gestita dal fuso) dell'ultima
    seduta USA già conclusa a `now`: weekend e festività di
    config.AI_TRADER_US_MARKET_HOLIDAYS saltati."""
    d = now.astimezone(_NY).date()
    for _ in range(10):
        if d.weekday() < 5 and d.isoformat() not in config.AI_TRADER_US_MARKET_HOLIDAYS:
            close = dt.datetime.combine(d, dt.time(16, 0), tzinfo=_NY).astimezone(dt.timezone.utc)
            if close <= now:
                return close
        d -= dt.timedelta(days=1)
    return now - dt.timedelta(days=1)


def _fresh_scan() -> dict | None:
    """Scansione nuova, adesso, senza AI (solo Yahoo): usata quando l'ultimo
    file dello Scanner è stato fatto prima della chiusura. Salva il risultato
    come fa scanner_run.py. None se non riesce (rete, Yahoo giù)."""
    try:
        result = market_scanner.scan(market_scanner.all_symbols())
        if not result.get("results"):
            return None
        os.makedirs(os.path.dirname(config.SCANNER_FILE), exist_ok=True)
        with open(config.SCANNER_FILE, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, ensure_ascii=False)
        return result
    except Exception:  # noqa: BLE001 - mai fatale: si ripiega sul file esistente
        return None


def load_scanner_results() -> dict[str, dict]:
    """Dati dello Scanner per i giudizi di oggi, indicizzati per simbolo.

    Freschezza (richiesta da una revisione esterna, 2026-11-05): non basta
    che il file sia "di oggi" — l'ultimo giro programmato dello Scanner
    (19:40 UTC) cade PRIMA della chiusura di Wall Street in ora solare
    (21:00 UTC), quindi prezzo e volume possono essere parziali, con un
    volume odierno sottostimato rispetto alla media (meno titoli segnalati,
    giudizi più prudenti senza che nessuno se ne accorga). Il file è valido
    solo se generato DOPO la chiusura dell'ultima seduta conclusa. Se non lo
    è, si fa una scansione nuova adesso (nessun costo AI). Se anche quella
    fallisce si ripiega sul vecchio criterio (file generato oggi, data UTC),
    con una riga nel registro; senza nemmeno quello: {} — un problema qui non
    deve mai bloccare decide_all() (i 4 ASSETS non dipendono dallo scanner).

    Il controllo sulla data resta dal code review pre-lancio del
    2026-11-01: uno scanner fermo da giorni (market_scanner.yml fallito in
    silenzio) non va letto come se fosse di oggi — build_scanner_prompt dice
    "Variazione da ieri"."""
    if not os.path.exists(config.SCANNER_FILE):
        return {}
    try:
        with open(config.SCANNER_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        generated_at = str(data.get("generated_at", ""))
        now = dt.datetime.now(dt.timezone.utc)
        try:
            generated = dt.datetime.fromisoformat(generated_at)
            if generated.tzinfo is None:
                generated = generated.replace(tzinfo=dt.timezone.utc)
        except ValueError:
            generated = None
        close = last_session_close_utc(now)
        if generated is not None and generated >= close:
            return {row["symbol"]: row for row in data.get("results", [])}
        print(f"Scanner generato prima della chiusura dell'ultima seduta (generated_at={generated_at or 'assente'}, chiusura {close.isoformat()}): scansione nuova.")
        fresh = _fresh_scan()
        if fresh is not None:
            return {row["symbol"]: row for row in fresh.get("results", [])}
        if generated_at.startswith(dt.date.today().isoformat()):
            print("Scansione nuova non riuscita: uso lo Scanner di oggi, che può essere parziale.")
            return {row["symbol"]: row for row in data.get("results", [])}
        print(f"Scanner non aggiornato oggi (generated_at={generated_at or 'assente'}): nessun dato scanner oggi.")
        return {}
    except Exception:  # noqa: BLE001 - degrada a "nessun dato scanner oggi", mai fatale
        return {}


def latest_prediction(asset: str, horizon_code: str = "1d") -> dict | None:
    """L'ultima previsione già generata da predict_run.py per questo asset/
    orizzonte, o None se non ce n'è ancora una. Stessa fonte di verità di
    report.py: legge predictions.jsonl, non ricalcola nulla."""
    records = storage.read_all(config.predictions_file(asset))
    matching = [r for r in records if r.get("horizon") == horizon_code]
    if not matching:
        return None
    return matching[-1]


# Soglia di confidenza sotto la quale una previsione esistente (UP/DOWN) non
# basta da sola a giustificare un'operazione: con un'accuratezza complessiva
# del paniere ASSETS sotto il 50% (vedi REPORT.md), agire su un segnale solo
# debolmente più probabile di un lancio di moneta aggiungerebbe rumore, non
# segnale, alle decisioni di trading.
CORE_ASSET_CONFIDENCE_THRESHOLD = 55


def core_asset_decision(asset: str) -> dict:
    """Decisione per uno dei 4 ASSETS, derivata dalla previsione 1g già
    esistente — nessuna chiamata AI aggiuntiva, nessun costo."""
    pred = latest_prediction(asset, "1d")
    if pred is None:
        return {
            "symbol": asset,
            "model_used": "previsione_esistente",
            "decision": "HOLD",
            "reasoning_short": "Nessuna previsione 1g disponibile ancora per questo asset.",
            "cost_usd": 0.0,
        }
    predicted_class = pred.get("predicted_class")
    confidence = pred.get("confidence", 0)
    if predicted_class == "UP" and confidence >= CORE_ASSET_CONFIDENCE_THRESHOLD:
        decision = "BUY"
    elif predicted_class == "DOWN" and confidence >= CORE_ASSET_CONFIDENCE_THRESHOLD:
        decision = "SELL"
    else:
        decision = "HOLD"
    return {
        "symbol": asset,
        "model_used": "previsione_esistente",
        "decision": decision,
        "reasoning_short": (
            f"Previsione 1g già esistente: {predicted_class} al {confidence}% di confidenza "
            f"(soglia per agire: {CORE_ASSET_CONFIDENCE_THRESHOLD}%)."
        ),
        "cost_usd": 0.0,
    }


def _trend_context(symbol: str) -> dict | None:
    """Contesto di trend (RSI, SMA50/SMA200, rendimento 20gg) dallo storico a
    1 anno. None se i dati non ci sono: il giudizio procede comunque, con la
    riga di trend segnata "non disponibile" (mai un titolo escluso per questo)."""
    bars = prices.fetch_daily_history(symbol, range_="1y")
    if len(bars) < 21:
        return None
    last = bars[-1]["close"]
    ret20 = (last / bars[-21]["close"] - 1.0) * 100.0
    sma50 = technicals.compute_sma(bars, 50)
    sma200 = technicals.compute_sma(bars, 200)
    rsi = technicals.compute_rsi(bars)

    def vs(sma):
        return None if not sma else round((last / sma - 1.0) * 100.0, 1)

    return {
        "rsi": None if rsi is None else round(rsi, 0),
        "vs_sma50_pct": vs(sma50),
        "vs_sma200_pct": vs(sma200),
        "ret20_pct": round(ret20, 1),
    }


def _fmt(value, suffix=""):
    return "non disponibile" if value is None else f"{value}{suffix}"


def build_scanner_prompt(symbol: str, row: dict, thresholds: dict, trend: dict | None = None) -> str:
    flagged_line = "SÌ — uno o più segnali sopra soglia oggi" if row.get("flagged") else "no, nessun segnale sopra soglia oggi"
    trend = trend or {}
    return f"""Devi dare un giudizio BUY/SELL/HOLD su {symbol} per un conto di trading PAPER
(denaro finto su Alpaca, nessuna operazione reale). Non è consulenza finanziaria: è un
esperimento che misura quanto un giudizio automatico regge nel tempo.

Segnali quantitativi di oggi (da uno scanner su volume/gap/breakout):
- Prezzo attuale: {row.get('price')} {row.get('currency', 'USD')}
- Variazione da ieri: {row.get('change_pct')}%
- Volume odierno vs media {config.SCANNER_LOOKBACK_DAYS}gg: {row.get('volume_ratio')}x (soglia segnalazione: {thresholds.get('volume_ratio')}x)
- Gap apertura vs chiusura precedente: {row.get('gap_pct')}% (soglia: {thresholds.get('gap_pct')}%)
- Posizione vs massimo di {config.SCANNER_LOOKBACK_DAYS}gg (breakout): {row.get('breakout_pct')}% (soglia: {thresholds.get('breakout_pct')}%)
- Segnalato come anomalo oggi dallo scanner: {flagged_line}

Contesto di trend:
- RSI(14): {_fmt(trend.get('rsi'))}
- Prezzo vs media a 50 giorni: {_fmt(trend.get('vs_sma50_pct'), '%')}
- Prezzo vs media a 200 giorni: {_fmt(trend.get('vs_sma200_pct'), '%')}
- Rendimento ultimi 20 giorni: {_fmt(trend.get('ret20_pct'), '%')}

Regola: BUY se il trend è positivo (prezzo sopra la media a 50 giorni, rendimento a 20
giorni positivo, RSI non in ipercomprato oltre 75) E c'è almeno una conferma, anche
moderata, da volume sopra la media, gap positivo o vicinanza al massimo recente: non
servono segnali estremi. SELL se il trend è chiaramente negativo (prezzo sotto la media
a 50 giorni con rendimento a 20 giorni negativo) e c'è conferma al ribasso. HOLD se il
trend è incerto, se mancano conferme o se i segnali sono contrastanti. Se un dato di
trend è non disponibile, decidi con quelli presenti e in dubbio scegli HOLD.

Rispondi ESCLUSIVAMENTE con un oggetto JSON valido, nessun altro testo:
{{"decision": "BUY"|"SELL"|"HOLD", "reasoning_short": "<massimo 2 frasi>"}}
"""


def _extract_json(text: str) -> dict:
    text = text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass  # JSON malformato (es. virgola mancante): provo il recupero sotto
    # Risposta troncata o malformata: recupero la decisione se è già scritta
    # in chiaro. La decisione viene prima del testo nel formato richiesto,
    # quindi una troncatura nel ragionamento non la invalida.
    dec = re.search(r'"decision"\s*:\s*"(BUY|SELL|HOLD)"', text, re.IGNORECASE)
    if dec:
        reason = re.search(r'"reasoning_short"\s*:\s*"([^"]*)', text)
        reasoning = (reason.group(1).strip() if reason else "") or "(ragionamento troncato)"
        return {"decision": dec.group(1), "reasoning_short": reasoning}
    raise DecisionParseError(f"Nessun JSON trovato nella risposta del modello: {text!r}")


def parse_decision(raw_text: str) -> dict:
    data = _extract_json(raw_text)
    decision = str(data.get("decision", "")).strip().upper()
    if decision not in ("BUY", "SELL", "HOLD"):
        raise DecisionParseError(f"decision non valida: {data.get('decision')!r}")
    reasoning = str(data.get("reasoning_short", "")).strip()
    if not reasoning:
        raise DecisionParseError("reasoning_short mancante")
    return {"decision": decision, "reasoning_short": reasoning}


def call_model(model: str, prompt: str) -> tuple[str, int, int]:
    """Ritorna (testo, input_tokens, output_tokens) — i token REALI di
    response.usage, non una stima, così budget.record_trader_call_cost()
    calcola il costo vero della chiamata appena fatta."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model=model,
        max_tokens=config.AI_TRADER_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in resp.content if block.type == "text")
    return text, resp.usage.input_tokens, resp.usage.output_tokens


def scanner_symbol_decision(symbol: str, row: dict, thresholds: dict, model: str) -> dict:
    """Giudizio AI per un simbolo non-ASSETS. Se il budget mensile è già
    esaurito, torna HOLD senza fare la chiamata (skipped_budget=True) invece
    di bloccare l'intero run o sforare il tetto."""
    if not budget.trader_has_budget():
        return {
            "symbol": symbol,
            "model_used": model,
            "decision": "HOLD",
            "reasoning_short": "Budget mensile AI esaurito: nessuna nuova chiamata questo mese.",
            "cost_usd": 0.0,
            "skipped_budget": True,
        }
    try:
        trend = _trend_context(symbol)
    except Exception:  # noqa: BLE001 - il trend è un di più, mai bloccante
        trend = None
    prompt = build_scanner_prompt(symbol, row, thresholds, trend)
    # cost_usd inizializzato qui (non 0.0 fisso nel except sotto): se
    # call_model ha già restituito una risposta e record_trader_call_cost ha
    # già addebitato la spesa reale al budget mensile, un parse_decision
    # fallito subito dopo (risposta malformata/troncata) non deve far
    # sparire quel costo dal record — bug reale trovato in un code review
    # pre-lancio, 2026-11-01: il budget veniva addebitato correttamente (lo
    # sforamento reale resta impossibile, trader_has_budget() legge il file
    # di stato vero), ma decisions.jsonl riportava cost_usd:0.0 per quella
    # decisione, rendendo inaffidabile un controllo a posteriori di dove sia
    # finita la spesa mensile.
    cost_usd = 0.0
    try:
        parsed = None
        for attempt in range(2):  # un solo nuovo tentativo se la risposta è inutilizzabile
            raw, input_tokens, output_tokens = call_model(model, prompt)
            cost_usd += budget.record_trader_call_cost(model, input_tokens, output_tokens)
            try:
                parsed = parse_decision(raw)
                break
            except DecisionParseError:
                if attempt == 1 or not budget.trader_has_budget():
                    raise
    except Exception as exc:  # noqa: BLE001 - un simbolo non deve bloccare gli altri
        return {
            "symbol": symbol,
            "model_used": model,
            "decision": "HOLD",
            "reasoning_short": f"Errore nel giudizio AI, HOLD per sicurezza: {exc}",
            "cost_usd": round(cost_usd, 6),
            # Campo esplicito invece di dedurlo da "Errore" nel testo
            # (fragile, si romperebbe se il messaggio cambiasse): usato da
            # decide_all() per data_health, vedi commento lì.
            "error": True,
        }
    return {
        "symbol": symbol,
        "model_used": model,
        "decision": parsed["decision"],
        "reasoning_short": parsed["reasoning_short"],
        "cost_usd": round(cost_usd, 6),
    }


def decide_all() -> list[dict]:
    """Una decisione per ogni titolo dell'universo tradabile:
    - ASSETS -> previsione già esistente (core_asset_decision), costo zero.
    - Altri, segnalati oggi dallo scanner, nel limite di
      AI_TRADER_MAX_SONNET_CALLS_PER_DAY (i primi N nell'ordine già
      flagged-first di market_scanner.scan()) -> AI_TRADER_SONNET_MODEL.
    - Tutti gli altri -> AI_TRADER_HAIKU_MODEL (copertura di base,
      quasi gratuita).
    Un titolo senza riga scanner quel giorno (simbolo fallito nello scan,
    o scanner non ancora girato) viene saltato: nessuna decisione forzata
    su dati che non ci sono."""
    decisions: list[dict] = []
    scanner_by_symbol = load_scanner_results()
    thresholds = {}
    if os.path.exists(config.SCANNER_FILE):
        try:
            with open(config.SCANNER_FILE, "r", encoding="utf-8") as fh:
                thresholds = json.load(fh).get("thresholds", {})
        except Exception:  # noqa: BLE001 - le soglie sono solo testo esplicativo nel prompt, mai fatale
            thresholds = {}

    universe = tradeable_universe()
    # Ordine dello scanner (flagged-first, volume anomalo decrescente: la
    # classifica di market_scanner.scan(), preservata dall'ordine di
    # inserimento del dict), non quello fisso della watchlist — come
    # sostenuto dal vecchio commento ma mai realmente implementato (bug
    # segnalato da una revisione esterna, verificato 2026-11-02). Decide
    # sia chi riceve Sonnet (primi N flagged) sia, a capitale insufficiente,
    # quali BUY partono per primi. I simboli senza riga scanner vanno in
    # coda e vengono comunque saltati più sotto.
    scanner_rank = {s: i for i, s in enumerate(scanner_by_symbol)}
    non_core = sorted(
        (s for s in universe if s not in config.ASSETS),
        key=lambda s: scanner_rank.get(s, len(scanner_rank)),
    )
    flagged_today = [s for s in non_core if scanner_by_symbol.get(s, {}).get("flagged")]
    sonnet_symbols = set(flagged_today[: config.AI_TRADER_MAX_SONNET_CALLS_PER_DAY])

    # Un asset/titolo alla volta, mai fatale per gli altri: senza questo
    # try/except, un problema isolato su un solo asset (es. predictions.jsonl
    # corrotto per quel titolo) interromperebbe decide_all() PRIMA di
    # arrivare agli altri 40+ titoli — nessuna decisione quel giorno per
    # nessuno, non solo per l'asset col problema. scanner_symbol_decision ha
    # già una propria protezione sulla chiamata al modello (torna HOLD), ma
    # non su un errore prima di quella chiamata (es. riga scanner malformata)
    # — qui è protetta anche quella.
    for asset in config.ASSETS:
        if asset in universe:
            try:
                decisions.append(core_asset_decision(asset))
            except Exception as exc:  # noqa: BLE001 - un asset alla volta, mai fatale
                decisions.append({
                    "symbol": asset,
                    "model_used": "previsione_esistente",
                    "decision": "HOLD",
                    "reasoning_short": f"Errore nel leggere la previsione esistente, HOLD per sicurezza: {exc}",
                    "cost_usd": 0.0,
                })

    # Simboli effettivamente passati per una chiamata all'API Anthropic
    # (hanno una riga scanner quel giorno), non l'intero non_core: i saltati
    # per riga scanner mancante non sono un fallimento dell'API, non vanno
    # contati nel tasso di errore qui sotto.
    attempted = 0
    failed_judgment: list[str] = []
    for symbol in non_core:
        row = scanner_by_symbol.get(symbol)
        if row is None:
            continue
        attempted += 1
        model = config.AI_TRADER_SONNET_MODEL if symbol in sonnet_symbols else config.AI_TRADER_HAIKU_MODEL
        try:
            decision = scanner_symbol_decision(symbol, row, thresholds, model)
        except Exception as exc:  # noqa: BLE001 - un titolo alla volta, mai fatale
            decision = {
                "symbol": symbol,
                "model_used": model,
                "decision": "HOLD",
                "error": True,
                "reasoning_short": f"Errore imprevisto nel giudizio AI, HOLD per sicurezza: {exc}",
                "cost_usd": 0.0,
            }
        decisions.append(decision)
        if decision.get("error"):
            failed_judgment.append(symbol)

    try:
        data_health.record_fetch_health("ai_judgment", attempted, failed_judgment)
    except Exception:  # noqa: BLE001 - lo stato di salute non deve mai bloccare il giudizio vero
        pass

    return decisions


def record_decision(decision: dict) -> dict:
    """Salva la decisione nella catena hash di decisions.jsonl — storico
    append-only, stesso pattern di predictions.jsonl/orders.jsonl."""
    return storage.append_record(config.AI_TRADER_DECISIONS_FILE, decision)
