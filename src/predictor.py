"""Costruzione del prompt, chiamata al modello Claude e parsing/validazione
della previsione strutturata."""
from __future__ import annotations

import json
import os
import re

import anthropic

from . import config

VALID_CLASSES = {"UP", "DOWN", "FLAT"}


class PredictionParseError(RuntimeError):
    pass


def build_prompt(
    asset: str,
    horizon_code: str,
    price: float,
    price_asof: str,
    threshold_pct: float,
    news: list[dict],
    fundamentals: dict | None,
    macro: dict,
    technicals: dict | None = None,
) -> str:
    news_block = (
        "\n".join(f"- ({n['published_at']}) {n['headline']}" for n in news[:8])
        if news
        else "Nessuna news recente disponibile."
    )
    fundamentals_block = json.dumps(fundamentals["metrics"], indent=2) if fundamentals else "Non disponibili."
    macro_block = "\n".join(f"- {k}: {v['value']} (al {v['date']})" for k, v in macro.items()) or "Non disponibili."

    technicals = technicals or {}
    technical_lines = []
    if technicals.get("obv_trend"):
        technical_lines.append(f"- On-Balance Volume: {technicals['obv_trend']}")
    if technicals.get("cmf") is not None:
        technical_lines.append(f"- Chaikin Money Flow (20gg): {technicals['cmf']} (range -1..+1, >0 = pressione in acquisto)")
    if technicals.get("relative_strength_vs_spy_pct") is not None:
        technical_lines.append(
            f"- Forza relativa vs S&P 500 (60gg): {technicals['relative_strength_vs_spy_pct']}% "
            "(positivo = sta sovraperformando il mercato)"
        )
    if technicals.get("sma_trend"):
        technical_lines.append(f"- Trend di fondo (SMA 50/200): {technicals['sma_trend']}")
    if technicals.get("ema_trend"):
        technical_lines.append(f"- Trend di breve termine (EMA 9/21): {technicals['ema_trend']}")
    if technicals.get("rsi_14") is not None:
        technical_lines.append(
            f"- RSI (14gg): {technicals['rsi_14']} (>70 ipercomprato, <30 ipervenduto)"
        )
    macd = technicals.get("macd")
    if macd is not None:
        technical_lines.append(
            f"- MACD (12/26/9): linea {macd['macd']}, segnale {macd['signal']}, "
            f"istogramma {macd['histogram']} (istogramma >0 = momentum rialzista)"
        )
    if technicals.get("atr_pct") is not None:
        technical_lines.append(
            f"- ATR (14gg): {technicals['atr_pct']}% del prezzo attuale (ampiezza media di movimento giornaliero)"
        )
    if technicals.get("beta_vs_spy") is not None:
        technical_lines.append(
            f"- Beta vs S&P 500 (60gg): {technicals['beta_vs_spy']} "
            "(>1 = più volatile del mercato, <1 = meno volatile)"
        )
    technicals_block = "\n".join(technical_lines) or "Non disponibili."

    return f"""Sei un analista quantitativo che deve emettere una previsione REALE e verificabile
sulla direzione del prezzo di {asset}, con orizzonte {horizon_code} da adesso.

Prezzo attuale: {price} (rilevato: {price_asof})
Banda neutra (FLAT) calcolata sulla volatilità storica recente: +/- {threshold_pct}%
  → prevedi UP se ti aspetti una variazione superiore a +{threshold_pct}%
  → prevedi DOWN se ti aspetti una variazione inferiore a -{threshold_pct}%
  → prevedi FLAT se ti aspetti una variazione entro questa banda

News recenti:
{news_block}

Fondamentali/dati ETF disponibili:
{fundamentals_block}

Contesto macro:
{macro_block}

Indicatori tecnici aggiuntivi:
{technicals_block}

Rispondi ESCLUSIVAMENTE con un oggetto JSON valido, nessun altro testo, con questa forma esatta:
{{"predicted_class": "UP|DOWN|FLAT", "confidence": <intero 0-100>, "reasoning_short": "<massimo 3 frasi>"}}
"""


def _extract_json(text: str) -> dict:
    text = text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise PredictionParseError(f"Nessun JSON trovato nella risposta del modello: {text!r}")
    return json.loads(match.group(0))


def call_model(prompt: str) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=config.ANTHROPIC_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in resp.content if block.type == "text")


def parse_prediction(raw_text: str) -> dict:
    data = _extract_json(raw_text)
    predicted_class = str(data.get("predicted_class", "")).upper()
    confidence = data.get("confidence")
    reasoning = str(data.get("reasoning_short", "")).strip()

    if predicted_class not in VALID_CLASSES:
        raise PredictionParseError(f"predicted_class non valido: {predicted_class!r}")
    if not isinstance(confidence, (int, float)) or not (0 <= confidence <= 100):
        raise PredictionParseError(f"confidence non valida: {confidence!r}")
    if not reasoning:
        raise PredictionParseError("reasoning_short mancante")

    return {"predicted_class": predicted_class, "confidence": int(confidence), "reasoning_short": reasoning}


def generate_prediction(
    asset: str,
    horizon_code: str,
    price: float,
    price_asof: str,
    threshold_pct: float,
    news: list[dict],
    fundamentals: dict | None,
    macro: dict,
    technicals: dict | None = None,
) -> dict:
    prompt = build_prompt(
        asset, horizon_code, price, price_asof, threshold_pct, news, fundamentals, macro, technicals
    )
    raw = call_model(prompt)
    return parse_prediction(raw)
