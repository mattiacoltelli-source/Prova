"""Sintesi mensile "a livello di paniere" per la pagina Trend strutturali:
confronta le ultime letture disponibili dei 4 asset (config.ROBOTICS_ASSETS)
invece di leggerli uno per volta. Analogo di trend_predictor.py, ma il
prompt riceve le letture di TUTTI gli asset insieme (non i prezzi grezzi)
e produce un solo paragrafo di confronto, non una nuova classificazione
per asset — nessuna chiamata dati aggiuntiva, riusa le letture già
generate da trend_run.py.

Principio identico al resto del sistema: gli aggregati cross-asset
(trend_analysis.compute_sector_aggregates) sono calcolo Python puro, mai
da ricalcolare lato modello — l'AI li commenta, non li deriva."""
from __future__ import annotations

import json
import os
import re

import anthropic

from . import config

VALID_DIRECTIONS = {"RIALZISTA", "RIBASSISTA", "LATERALE", "MISTO"}


class SectorReportParseError(RuntimeError):
    pass


def build_sector_prompt(asset_records: dict[str, dict], aggregates: dict) -> str:
    asset_lines = []
    for asset, record in sorted(asset_records.items()):
        metrics = record.get("metrics", {})
        label = config.TREND_PROMPT_CONTEXT.get(asset, {}).get("sector_label", asset)
        ep = metrics.get("extended_episodes") or {}
        correction_txt = (
            f", correzione media storica in fasi simili {ep['avg_correction_pct']:+.1f}%"
            if ep.get("avg_correction_pct") is not None
            else ""
        )
        asset_lines.append(
            f"- {asset} ({label}): direzione {record.get('trend_direction')}, "
            f"confidence {record.get('confidence')}%, fase ciclo {metrics.get('cycle_phase')} "
            f"({metrics.get('price_vs_ma_pct'):+.1f}% vs media {metrics.get('ma_weeks')} settimane), "
            f"correlazione SOX {record.get('sox_correlation')}, "
            f"CAGR 1y {_fmt_pct(metrics.get('cagr_by_years', {}).get('1'))}"
            f"{correction_txt}, letto il {record.get('generated_at', '')[:10]}"
        )
    assets_block = "\n".join(asset_lines)

    phase_counts_txt = ", ".join(f"{k}: {v}/{aggregates['num_assets']}" for k, v in aggregates["phase_counts"].items())
    direction_counts_txt = ", ".join(f"{k}: {v}/{aggregates['num_assets']}" for k, v in aggregates["direction_counts"].items())

    def _range_txt(range_dict: dict | None, unit: str = "") -> str:
        if not range_dict:
            return "non disponibile"
        return (
            f"da {range_dict['min_value']}{unit} ({range_dict['min_asset']}) "
            f"a {range_dict['max_value']}{unit} ({range_dict['max_asset']})"
        )

    return f"""Sei un analista quantitativo. Devi scrivere una SINTESI COMPARATIVA mensile per un
paniere di {aggregates['num_assets']} titoli seguiti come "trend strutturali" a lungo termine
(1-10 anni): robotica/meccanica di precisione (THK, Harmonic Drive, Teradyne) e infrastruttura
data center AI (Vertiv). Non è una nuova previsione per singolo titolo (quelle esistono già,
sotto) — è un confronto tra le letture già fatte, per capire se il paniere si muove insieme o si
sta dividendo, e se è un momento di ingresso storicamente favorevole o rischioso.

Ultime letture disponibili per asset (NON ricalcolarle, sono già definitive):
{assets_block}

Statistiche cross-asset GIÀ CALCOLATE sui dati sopra (NON ricalcolarle né ricontarle):
- Fasi di ciclo: {phase_counts_txt}
- Direzioni: {direction_counts_txt}
- Posizione vs media mobile lunga: {_range_txt(aggregates['price_vs_ma_range'], '%')}
- Correlazione con SOX: {_range_txt(aggregates['sox_correlation_range'])}
- Correzione media storica in fasi simili: {_range_txt(aggregates['avg_correction_range'], '%')}
- Almeno un asset in fase compressa/molto_compressa (storicamente punto di ingresso migliore): {'sì' if aggregates['any_asset_compressed'] else 'no'}

Nota: gli asset possono avere date di lettura diverse (THK/Harmonic Drive/Teradyne mensili,
Vertiv trimestrale) — segnalalo se rilevante, non trattarle come tutte dello stesso giorno.

Scrivi 2-3 frasi in italiano che confrontino i titoli tra loro usando ESCLUSIVAMENTE i numeri
sopra (non inventarne altri, non citare notizie o eventi non menzionati): cosa hanno in comune o
in cosa divergono, quale titolo è il più/meno esposto, e se il paniere nel suo insieme sembra in
un momento di cautela o di opportunità sull'ingresso.

Rispondi ESCLUSIVAMENTE con un oggetto JSON valido, nessun altro testo, con questa forma esatta:
{{"sector_narrative": "<2-3 frasi>", "overall_direction": "RIALZISTA|RIBASSISTA|LATERALE|MISTO"}}
"""


def _fmt_pct(value: float | None) -> str:
    return f"{value * 100:+.1f}%" if value is not None else "n/d"


def _extract_json(text: str) -> dict:
    text = text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise SectorReportParseError(f"Nessun JSON trovato nella risposta del modello: {text!r}")
    return json.loads(match.group(0))


def call_model(prompt: str) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=config.TREND_ANTHROPIC_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in resp.content if block.type == "text")


def parse_sector_report(raw_text: str) -> dict:
    data = _extract_json(raw_text)
    narrative = str(data.get("sector_narrative", "")).strip()
    direction = str(data.get("overall_direction", "")).upper()
    if not narrative:
        raise SectorReportParseError("sector_narrative mancante")
    if direction not in VALID_DIRECTIONS:
        raise SectorReportParseError(f"overall_direction non valido: {direction!r}")
    return {"sector_narrative": narrative, "overall_direction": direction}


def generate_sector_report(asset_records: dict[str, dict], aggregates: dict) -> dict:
    prompt = build_sector_prompt(asset_records, aggregates)
    raw = call_model(prompt)
    return parse_sector_report(raw)
