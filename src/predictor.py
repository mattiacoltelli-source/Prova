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


from .data_sources.sentiment import compute_sentiment_score

def build_prompt(
    asset: str,
    horizon_code: str,
    price: float,
    price_asof: str,
    threshold_pct: float,
    news: list[dict],
    fundamentals: dict | None,
    macro: dict,
) -> str:
    news_block = (
        "\n".join(f"- ({n['published_at']}) {n['headline']}" for n in news[:8])
        if news
        else "Nessuna news recente disponibile."
    )
    fundamentals_block = json.dumps(fundamentals["metrics"], indent=2) if fundamentals else "Non disponibili."
    macro_block = "\n".join(f"- {k}: {v['value']} (al {v['date']})" for k, v in macro.items()) or "Non disponibili."

    sentiment_res = compute_sentiment_score(asset, news)
    sentiment_block = (
        f"Score: {sentiment_res['sentiment_score']} ({sentiment_res['sentiment_label']}) | "
        f"Segnali Positivi: {sentiment_res['bullish_signals']}, Segnali Negativi: {sentiment_res['bearish_signals']}"
    )

    return f"""Sei un analista quantitativo che deve emettere una previsione REALE e verificabile
sulla direzione del prezzo di {asset}, con orizzonte {horizon_code} da adesso.

Prezzo attuale: {price} (rilevato: {price_asof})
Banda neutra (FLAT) calcolata sulla volatilità storica recente: +/- {threshold_pct}%
  → prevedi UP se ti aspetti una variazione superiore a +{threshold_pct}%
  → prevedi DOWN se ti aspetti una variazione inferiore a -{threshold_pct}%
  → prevedi FLAT se ti aspetti una variazione entro questa banda

Punteggio News & Social Sentiment Scoring (Analisi NLP):
{sentiment_block}

News recenti:
{news_block}

Fondamentali/dati ETF disponibili:
{fundamentals_block}

Contesto macro:
{macro_block}

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
) -> dict:
    prompt = build_prompt(asset, horizon_code, price, price_asof, threshold_pct, news, fundamentals, macro)
    raw = call_model(prompt)
    return parse_prediction(raw)
