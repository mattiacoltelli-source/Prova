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

import json
import os
import re

import anthropic

from . import budget, config, storage


class DecisionParseError(RuntimeError):
    pass


def tradeable_universe() -> list[str]:
    """SCANNER_STOCKS meno i ticker non tradabili su Alpaca (broker USA —
    vedi AI_TRADER_EXCLUDED_TICKERS in config.py). Le crypto di
    SCANNER_CRYPTO restano fuori per ora (formato ticker diverso)."""
    return [s for s in config.SCANNER_STOCKS if s not in config.AI_TRADER_EXCLUDED_TICKERS]


def load_scanner_results() -> dict[str, dict]:
    """Ultimo scan disponibile (data/scanner/results.json), indicizzato per
    simbolo. {} se lo scanner non ha ancora mai girato — chi chiama decide
    come comportarsi (vedi decide_all: un simbolo senza riga scanner non
    riceve un giudizio quel giorno, invece di bloccare tutto il run)."""
    if not os.path.exists(config.SCANNER_FILE):
        return {}
    with open(config.SCANNER_FILE, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return {row["symbol"]: row for row in data.get("results", [])}


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


def build_scanner_prompt(symbol: str, row: dict, thresholds: dict) -> str:
    flagged_line = "SÌ — uno o più segnali sopra soglia oggi" if row.get("flagged") else "no, nessun segnale sopra soglia oggi"
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

BUY solo se il quadro è chiaramente positivo (non solo "non negativo"); SELL solo se
chiaramente negativo; HOLD in tutti gli altri casi, incluso quando i segnali sono
contrastanti o troppo deboli per decidere con sicurezza.

Rispondi ESCLUSIVAMENTE con un oggetto JSON valido, nessun altro testo:
{{"decision": "BUY"|"SELL"|"HOLD", "reasoning_short": "<massimo 2 frasi>"}}
"""


def _extract_json(text: str) -> dict:
    text = text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise DecisionParseError(f"Nessun JSON trovato nella risposta del modello: {text!r}")
    return json.loads(match.group(0))


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
    prompt = build_scanner_prompt(symbol, row, thresholds)
    try:
        raw, input_tokens, output_tokens = call_model(model, prompt)
        cost_usd = budget.record_trader_call_cost(model, input_tokens, output_tokens)
        parsed = parse_decision(raw)
    except Exception as exc:  # noqa: BLE001 - un simbolo non deve bloccare gli altri
        return {
            "symbol": symbol,
            "model_used": model,
            "decision": "HOLD",
            "reasoning_short": f"Errore nel giudizio AI, HOLD per sicurezza: {exc}",
            "cost_usd": 0.0,
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
        with open(config.SCANNER_FILE, "r", encoding="utf-8") as fh:
            thresholds = json.load(fh).get("thresholds", {})

    universe = tradeable_universe()
    non_core = [s for s in universe if s not in config.ASSETS]
    flagged_today = [s for s in non_core if scanner_by_symbol.get(s, {}).get("flagged")]
    sonnet_symbols = set(flagged_today[: config.AI_TRADER_MAX_SONNET_CALLS_PER_DAY])

    for asset in config.ASSETS:
        if asset in universe:
            decisions.append(core_asset_decision(asset))

    for symbol in non_core:
        row = scanner_by_symbol.get(symbol)
        if row is None:
            continue
        model = config.AI_TRADER_SONNET_MODEL if symbol in sonnet_symbols else config.AI_TRADER_HAIKU_MODEL
        decisions.append(scanner_symbol_decision(symbol, row, thresholds, model))

    return decisions


def record_decision(decision: dict) -> dict:
    """Salva la decisione nella catena hash di decisions.jsonl — storico
    append-only, stesso pattern di predictions.jsonl/orders.jsonl."""
    return storage.append_record(config.AI_TRADER_DECISIONS_FILE, decision)
