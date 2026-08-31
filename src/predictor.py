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


def build_prompt(
    asset: str,
    horizon_code: str,
    price: float,
    price_asof: str,
    threshold_pct: float,
    news: list[dict],
    fundamentals: dict | None,
    macro: dict,
    technical_indicators: dict | None = None,
    market_regime: str | None = None,
    high_impact_events: list[str] | None = None,
) -> str:
    news_block = (
        "\n".join(f"- ({n['published_at']}) {n['headline']}" for n in news[:8])
        if news
        else "Nessuna news recente disponibile."
    )
    fundamentals_block = json.dumps(fundamentals["metrics"], indent=2) if fundamentals else "Non disponibili."
    macro_block = "\n".join(f"- {k}: {v['value']} (al {v['date']})" for k, v in macro.items()) or "Non disponibili."

    tech_str = "Non disponibili."
    if technical_indicators:
        tech_lines = []
        for k, v in technical_indicators.items():
            if v is not None:
                tech_lines.append(f"- {k}: {v}")
        if tech_lines:
            tech_str = "\n".join(tech_lines)

    regime_block = market_regime if market_regime else "Normale / Neutral"
    events_block = "\n".join(f"- {ev}" for ev in high_impact_events) if high_impact_events else "Nessun evento ad alto impatto imminente."

    return f"""Sei un analista quantitativo esperto. Devi emettere una previsione REALE, argomentata e verificabile
sulla direzione del prezzo di {asset}, con orizzonte {horizon_code} da adesso.

Prezzo attuale: {price} (rilevato: {price_asof})
Banda neutra (FLAT) calcolata sulla volatilità storica recente: +/- {threshold_pct}%
  → prevedi UP se ti aspetti una variazione superiore a +{threshold_pct}%
  → prevedi DOWN se ti aspetti una variazione inferiore a -{threshold_pct}%
  → prevedi FLAT se ti aspetti una variazione entro questa banda

Indicatori Tecnici Quantitativi:
{tech_str}

Regime di Mercato (VIX & Volatilità):
- {regime_block}

Eventi Macro / Earnings ad Alto Impatto Imminenti:
{events_block}

News recenti:
{news_block}

Fondamentali/dati ETF disponibili:
{fundamentals_block}

Contesto macro:
{macro_block}

Linee guida di analisi Chain-of-Thought:
1. Valuta il Trend e il Momentum Tecnico (RSI, MACD, Medie Mobili, Bollinger Bands).
2. Pesa il Regime di Mercato: se la volatilità è elevata o il mercato è in laterale, evita previsioni direzionali azzardate.
3. Considera gli Eventi Imminenti (Earnings, FED, CPI): se c'è un evento imminente, riduci la confidenza o favorisci FLAT.
4. Pesa il Sentiment delle news recenti e il contesto Macroeconomico.
5. Assegna un livello di confidenza elevato (>70%) solo in caso di forte e chiara convergenza di tutti i segnali.

Rispondi ESCLUSIVAMENTE con un oggetto JSON valido, nessun altro testo, con questa forma esatta:
{{"predicted_class": "UP|DOWN|FLAT", "confidence": <intero 0-100>, "reasoning_short": "<3 frasi con sintesi del ragionamento Chain-of-Thought>"}}
"""


def generate_prediction(
    asset: str,
    horizon_code: str,
    price: float,
    price_asof: str,
    threshold_pct: float,
    news: list[dict],
    fundamentals: dict | None,
    macro: dict,
    technical_indicators: dict | None = None,
    market_regime: str | None = None,
    high_impact_events: list[str] | None = None,
    ensemble_samples: int = 1,
) -> dict:
    prompt = build_prompt(
        asset,
        horizon_code,
        price,
        price_asof,
        threshold_pct,
        news,
        fundamentals,
        macro,
        technical_indicators,
        market_regime,
        high_impact_events,
    )

    if ensemble_samples <= 1:
        raw = call_model(prompt)
        return parse_prediction(raw)

    # Multi-sampling ensemble: voto di maggioranza
    samples = []
    for _ in range(ensemble_samples):
        try:
            raw = call_model(prompt)
            samples.append(parse_prediction(raw))
        except Exception:  # noqa: S110
            pass

    if not samples:
        raw = call_model(prompt)
        return parse_prediction(raw)

    class_counts: dict[str, int] = {}
    for s in samples:
        cls = s["predicted_class"]
        class_counts[cls] = class_counts.get(cls, 0) + 1

    # Classe vincente per voto di maggioranza
    winning_class = max(class_counts, key=class_counts.get)
    winning_samples = [s for s in samples if s["predicted_class"] == winning_class]
    avg_confidence = int(sum(s["confidence"] for s in winning_samples) / len(winning_samples))
    combined_reasoning = winning_samples[0]["reasoning_short"]

    return {
        "predicted_class": winning_class,
        "confidence": avg_confidence,
        "reasoning_short": f"[Consensus Ensemble {len(winning_samples)}/{len(samples)}] {combined_reasoning}",
    }
