"""Costruzione del prompt e parsing della risposta Claude per l'analisi di
trend di lungo periodo (asset "robotica"). Analogo di predictor.py, ma
l'output NON è una previsione puntuale UP/DOWN/FLAT verificabile a breve
termine: è una lettura narrativa del regime di trend attuale (direzione,
fase del ciclo, driver, rischi), pensata per orizzonti 1/3/5/10 anni dove
il rumore giornaliero non ha significato."""
from __future__ import annotations

import json
import os
import re

import anthropic

from . import config

VALID_DIRECTIONS = {"RIALZISTA", "RIBASSISTA", "LATERALE"}


class TrendParseError(RuntimeError):
    pass


def build_trend_prompt(
    asset_label: str,
    ticker: str,
    metrics: dict,
    news: list[dict],
    sox_correlation: float | None,
    beta_vs_sox: float | None,
) -> str:
    cagr_lines = []
    for years, value in metrics["cagr_by_years"].items():
        cagr_lines.append(f"- {years} anni: {value * 100:+.1f}%" if value is not None else f"- {years} anni: non disponibile (storico insufficiente)")
    cagr_block = "\n".join(cagr_lines)

    annual_returns = metrics.get("annual_returns") or {}
    annual_block = "\n".join(
        f"- {year}: {ret:+.1f}%" for year, ret in sorted(annual_returns.items())
    ) or "Non disponibili."

    news_block = (
        "\n".join(f"- ({n['published_at']}) {n['headline']}" for n in news[:6])
        if news
        else "Nessuna news recente disponibile per questo ticker."
    )

    max_dd = metrics.get("max_drawdown")
    vol = metrics.get("annualized_volatility")
    price_vs_ma = metrics.get("price_vs_ma_pct")
    ma_weeks = metrics.get("ma_weeks")

    return f"""Sei un analista quantitativo specializzato in trend di lungo periodo (NON trading di breve
termine). Devi valutare il REGIME DI TREND attuale di {asset_label} ({ticker}), un'azione del
comparto robotica/automazione/meccanica di precisione, su orizzonti di 1, 3, 5 e 10 anni.

Prezzo attuale: {metrics.get('last_price')} (al {metrics.get('last_date')})
Storico disponibile da: {metrics.get('first_date')}

CAGR (crescita media annua composta) per orizzonte:
{cagr_block}

Rendimenti per anno solare (mostra la forma del ciclo, boom vs bust):
{annual_block}

Drawdown massimo storico dai picchi: {f'{max_dd * 100:+.1f}%' if max_dd is not None else 'non disponibile'}
Volatilità annualizzata: {f'{vol * 100:.1f}%' if vol is not None else 'non disponibile'}
Posizione rispetto alla media mobile a {ma_weeks} settimane: {f'{price_vs_ma:+.1f}%' if price_vs_ma is not None else 'non disponibile'} (fase ciclo calcolata: {metrics.get('cycle_phase')})

Driver macro dominante per questo paniere (scoperto empiricamente, non produzione industriale
generica): correlazione storica dei rendimenti annuali con l'indice Philadelphia Semiconductor
(^SOX) = {sox_correlation if sox_correlation is not None else 'non disponibile'}, beta vs SOX
(circa 1 anno di barre) = {beta_vs_sox if beta_vs_sox is not None else 'non disponibile'}.

News/contesto recente:
{news_block}

Nota importante: questo è un titolo storicamente CICLICO (boom-bust di 3-4 anni legati al ciclo
capex semiconduttori/AI, con drawdown storici del 45-80% dai picchi), non un trend lineare. Una
fase "molto_estesa" o "estesa" (prezzo ben sopra la propria media di lungo periodo) è
storicamente seguita da correzioni significative, anche quando il trend di fondo resta
strutturalmente positivo.

Rispondi ESCLUSIVAMENTE con un oggetto JSON valido, nessun altro testo, con questa forma esatta:
{{"trend_direction": "RIALZISTA|RIBASSISTA|LATERALE", "confidence": <intero 0-100>,
"cycle_assessment": "<1-2 frasi su dove siamo nel ciclo storico>",
"key_drivers": ["<driver 1>", "<driver 2>", "<driver 3 opzionale>"],
"risk_notes": "<1-2 frasi sui rischi principali, incluso il rischio di mean-reversion se la fase è estesa>"}}
"""


def _extract_json(text: str) -> dict:
    text = text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise TrendParseError(f"Nessun JSON trovato nella risposta del modello: {text!r}")
    return json.loads(match.group(0))


def call_model(prompt: str) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=config.TREND_ANTHROPIC_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in resp.content if block.type == "text")


def parse_trend_analysis(raw_text: str) -> dict:
    data = _extract_json(raw_text)
    direction = str(data.get("trend_direction", "")).upper()
    confidence = data.get("confidence")
    cycle_assessment = str(data.get("cycle_assessment", "")).strip()
    key_drivers = data.get("key_drivers")
    risk_notes = str(data.get("risk_notes", "")).strip()

    if direction not in VALID_DIRECTIONS:
        raise TrendParseError(f"trend_direction non valido: {direction!r}")
    if not isinstance(confidence, (int, float)) or not (0 <= confidence <= 100):
        raise TrendParseError(f"confidence non valida: {confidence!r}")
    if not cycle_assessment:
        raise TrendParseError("cycle_assessment mancante")
    if not isinstance(key_drivers, list) or not key_drivers:
        raise TrendParseError(f"key_drivers non valido: {key_drivers!r}")
    if not risk_notes:
        raise TrendParseError("risk_notes mancante")

    return {
        "trend_direction": direction,
        "confidence": int(confidence),
        "cycle_assessment": cycle_assessment,
        "key_drivers": [str(d).strip() for d in key_drivers if str(d).strip()],
        "risk_notes": risk_notes,
    }


def generate_trend_analysis(
    asset_label: str,
    ticker: str,
    metrics: dict,
    news: list[dict],
    sox_correlation: float | None,
    beta_vs_sox: float | None,
) -> dict:
    prompt = build_trend_prompt(asset_label, ticker, metrics, news, sox_correlation, beta_vs_sox)
    raw = call_model(prompt)
    return parse_trend_analysis(raw)
