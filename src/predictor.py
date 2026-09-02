"""Costruzione del prompt, chiamata al modello Claude e parsing/validazione
della previsione strutturata."""
from __future__ import annotations

import json
import os
import re

import anthropic

from . import config
from .data_sources import news as news_source

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
    analyst_outlook: dict | None = None,
    insider_summary: dict | None = None,
) -> str:
    news_block = (
        "\n".join(f"- ({n['published_at']}) {n['headline']}" for n in news[:8])
        if news
        else "Nessuna news recente disponibile."
    )
    sentiment_avg = news_source.average_sentiment(news)
    if sentiment_avg is not None:
        news_block += f"\n\nSentiment medio delle news (-1..+1): {sentiment_avg}"
    fundamentals_block = json.dumps(fundamentals["metrics"], indent=2) if fundamentals else "Non disponibili."
    macro_block = "\n".join(f"- {k}: {v['value']} (al {v['date']})" for k, v in macro.items()) or "Non disponibili."

    analyst_lines = []
    if analyst_outlook:
        if analyst_outlook.get("next_report_date"):
            analyst_lines.append(f"- Prossima data di bilancio: {analyst_outlook['next_report_date']}")
        if analyst_outlook.get("eps_estimate_average") is not None:
            analyst_lines.append(
                f"- Stima EPS media consenso analisti (trimestre chiuso al "
                f"{analyst_outlook.get('fiscal_quarter_ending')}): {analyst_outlook['eps_estimate_average']} "
                f"({analyst_outlook.get('eps_estimate_analyst_count')} analisti)"
            )
        up = analyst_outlook.get("eps_revisions_up_30d")
        down = analyst_outlook.get("eps_revisions_down_30d")
        if up is not None or down is not None:
            analyst_lines.append(
                f"- Revisioni stima EPS ultimi 30gg: {up or 0} al rialzo, {down or 0} al ribasso"
            )
    analyst_block = "\n".join(analyst_lines) or "Non disponibili."

    if insider_summary:
        insider_block = (
            f"Ultimi {insider_summary['lookback_days']}gg: "
            f"{insider_summary['buy_transactions']} acquisti sul mercato aperto, "
            f"{insider_summary['sell_transactions']} vendite, "
            f"netto {insider_summary['net_shares']:+} azioni "
            "(solo transazioni discrezionali, escluse vesting/opzioni/donazioni)"
        )
    else:
        insider_block = "Nessuna transazione insider rilevante nella finestra osservata."

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
    sector_ticker = technicals.get("sector_benchmark")
    if technicals.get("relative_strength_vs_sector_pct") is not None and sector_ticker:
        technical_lines.append(
            f"- Forza relativa vs settore {sector_ticker} (60gg): "
            f"{technicals['relative_strength_vs_sector_pct']}% "
            "(positivo = sta sovraperformando il proprio settore, non solo il mercato generale)"
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
    if technicals.get("beta_vs_sector") is not None and sector_ticker:
        technical_lines.append(
            f"- Beta vs settore {sector_ticker} (60gg): {technicals['beta_vs_sector']} "
            "(>1 = più volatile del proprio settore, <1 = meno volatile)"
        )
    if technicals.get("bollinger_percent_b") is not None:
        technical_lines.append(
            f"- Bande di Bollinger (%B, 20gg): {technicals['bollinger_percent_b']} "
            "(0 = bordo inferiore, 1 = bordo superiore, <0 o >1 = fuori banda)"
        )
    range_52w = technicals.get("range_52w")
    if range_52w is not None:
        technical_lines.append(
            f"- Distanza da massimo 52 settimane: {range_52w['pct_from_high']}%, "
            f"da minimo 52 settimane: {range_52w['pct_from_low']}%"
        )
    if technicals.get("relative_volume") is not None:
        technical_lines.append(
            f"- Volume relativo (ultima barra vs media 20gg): {technicals['relative_volume']}x "
            "(>1 = attività sopra la norma recente)"
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

Consenso analisti/prossimo bilancio:
{analyst_block}

Transazioni insider (dirigenti/amministratori, solo mercato aperto):
{insider_block}

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
    analyst_outlook: dict | None = None,
    insider_summary: dict | None = None,
) -> dict:
    prompt = build_prompt(
        asset, horizon_code, price, price_asof, threshold_pct, news, fundamentals, macro,
        technicals, analyst_outlook, insider_summary,
    )
    raw = call_model(prompt)
    return parse_prediction(raw)
