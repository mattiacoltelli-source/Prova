"""Sintesi mensile "a livello di paniere" per la pagina Trend strutturali:
confronta le ultime letture disponibili degli asset (config.ROBOTICS_ASSETS)
invece di leggerli uno per volta. Analogo di trend_predictor.py, ma il
prompt riceve le letture di TUTTI gli asset insieme (non i prezzi grezzi)
e produce un confronto per settore, non una nuova classificazione per
asset — nessuna chiamata dati aggiuntiva, riusa le letture già generate da
trend_run.py.

Fino al 2026-09-18 il paniere aveva un solo settore (robotica) più Vertiv
trattato come caso a parte nel testo del prompt, e produceva un unico
paragrafo. Con l'aggiunta di NVT il paniere è arrivato a 5 asset su 2 temi
distinti (config.ROBOTICS_SECTOR: robotica vs infrastruttura elettrica) e
un solo blob di testo mescolava titoli non comparabili — ora la sintesi è
un paragrafo per settore più una nota di confronto tra i due.

Principio identico al resto del sistema: gli aggregati cross-asset
(trend_analysis.compute_sector_aggregates, calcolati per settore da
trend_run.py) sono calcolo Python puro, mai da ricalcolare lato modello —
l'AI li commenta, non li deriva."""
from __future__ import annotations

import json
import os
import re

import anthropic

from . import config

VALID_DIRECTIONS = {"RIALZISTA", "RIBASSISTA", "LATERALE", "MISTO"}


class SectorReportParseError(RuntimeError):
    pass


def _range_txt(range_dict: dict | None, unit: str = "") -> str:
    if not range_dict:
        return "non disponibile"
    return (
        f"da {range_dict['min_value']}{unit} ({range_dict['min_asset']}) "
        f"a {range_dict['max_value']}{unit} ({range_dict['max_asset']})"
    )


def _asset_line(asset: str, record: dict) -> str:
    metrics = record.get("metrics", {})
    label = config.TREND_PROMPT_CONTEXT.get(asset, {}).get("sector_label", asset)
    ep = metrics.get("extended_episodes") or {}
    correction_txt = (
        f", correzione media storica in fasi simili {ep['avg_correction_pct']:+.1f}%"
        if ep.get("avg_correction_pct") is not None
        else ""
    )
    return (
        f"- {asset} ({label}): direzione {record.get('trend_direction')}, "
        f"confidence {record.get('confidence')}%, fase ciclo {metrics.get('cycle_phase')} "
        f"({metrics.get('price_vs_ma_pct'):+.1f}% vs media {metrics.get('ma_weeks')} settimane), "
        f"correlazione SOX {record.get('sox_correlation')}, "
        f"CAGR 1y {_fmt_pct(metrics.get('cagr_by_years', {}).get('1'))}"
        f"{correction_txt}, letto il {record.get('generated_at', '')[:10]}"
    )


def _sector_stats_block(agg: dict) -> str:
    phase_txt = ", ".join(f"{k}: {v}/{agg['num_assets']}" for k, v in agg["phase_counts"].items()) or "n/d"
    direction_txt = ", ".join(f"{k}: {v}/{agg['num_assets']}" for k, v in agg["direction_counts"].items()) or "n/d"
    return (
        f"  Statistiche già calcolate per questo settore (NON ricalcolarle né ricontarle):\n"
        f"  - Fasi di ciclo: {phase_txt}\n"
        f"  - Direzioni: {direction_txt}\n"
        f"  - Posizione vs media mobile lunga: {_range_txt(agg['price_vs_ma_range'], '%')}\n"
        f"  - Correlazione con SOX: {_range_txt(agg['sox_correlation_range'])}\n"
        f"  - Correzione media storica in fasi simili: {_range_txt(agg['avg_correction_range'], '%')}\n"
        f"  - Almeno un asset in fase compressa/molto_compressa: {'sì' if agg['any_asset_compressed'] else 'no'}"
    )


def build_sector_prompt(
    asset_records: dict[str, dict],
    aggregates: dict,
    sector_of: dict[str, str],
    sector_aggregates: dict[str, dict],
) -> str:
    # Raggruppa per settore preservando l'ordine di prima comparsa, non
    # l'ordine alfabetico: così il prompt (e le chiavi del JSON atteso)
    # seguono lo stesso ordine ogni volta invece di dipendere dall'hash
    # dict di Python.
    sectors_order: list[str] = []
    by_sector: dict[str, list[str]] = {}
    for asset in sorted(asset_records):
        sector = sector_of.get(asset, "Altro")
        if sector not in by_sector:
            by_sector[sector] = []
            sectors_order.append(sector)
        by_sector[sector].append(asset)

    sector_blocks = []
    for sector in sectors_order:
        assets_in_sector = by_sector[sector]
        lines = "\n".join(_asset_line(a, asset_records[a]) for a in assets_in_sector)
        agg = sector_aggregates.get(sector) or {}
        sector_blocks.append(f"## {sector} ({len(assets_in_sector)} titoli)\n{lines}\n{_sector_stats_block(agg)}")
    sectors_block = "\n\n".join(sector_blocks)

    sector_keys_json = ", ".join(f'"{s}": "<2-3 frasi>"' for s in sectors_order)

    return f"""Sei un analista quantitativo. Devi scrivere una SINTESI COMPARATIVA mensile per un
paniere di {aggregates['num_assets']} titoli seguiti come "trend strutturali" a lungo termine
(1-10 anni), divisi in {len(sectors_order)} settori distinti. Non è una nuova previsione per
singolo titolo (quelle esistono già, sotto) — è un confronto tra le letture già fatte, per capire
se ciascun settore si muove compatto o si sta dividendo, e se è un momento di ingresso
storicamente favorevole o rischioso. NON mescolare titoli di settori diversi nello stesso
paragrafo: sono tesi d'investimento diverse, non comparabili direttamente.

Ultime letture disponibili per asset, raggruppate per settore (NON ricalcolarle, sono già
definitive):

{sectors_block}

Statistiche sull'intero paniere insieme (tutti i {aggregates['num_assets']} titoli, per la nota
di confronto tra settori — NON ricalcolarle):
- Fasi di ciclo: {", ".join(f"{k}: {v}/{aggregates['num_assets']}" for k, v in aggregates["phase_counts"].items())}
- Direzioni: {", ".join(f"{k}: {v}/{aggregates['num_assets']}" for k, v in aggregates["direction_counts"].items())}
- Correlazione con SOX: {_range_txt(aggregates['sox_correlation_range'])}

Nota: gli asset possono avere date di lettura diverse (mensile per quasi tutti, trimestrale per
Vertiv) — segnalalo se rilevante, non trattarle come tutte dello stesso giorno.

Per ciascun settore elencato sopra, scrivi 2-3 frasi in italiano che confrontino SOLO i titoli di
quel settore tra loro, usando ESCLUSIVAMENTE i numeri di quel settore (non inventarne altri, non
citare notizie o eventi non menzionati, non confrontare con l'altro settore qui). Poi scrivi
separatamente 1-2 frasi (cross_sector_note) che confrontino i settori TRA loro usando le
statistiche sull'intero paniere sopra: quale settore è più esposto, se si muovono insieme o
divergono.

Rispondi ESCLUSIVAMENTE con un oggetto JSON valido, nessun altro testo, con questa forma esatta
(una chiave per ciascun settore elencato sopra, esattamente con questi nomi):
{{"sector_narratives": {{{sector_keys_json}}}, "cross_sector_note": "<1-2 frasi>", "overall_direction": "RIALZISTA|RIBASSISTA|LATERALE|MISTO"}}
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


def parse_sector_report(raw_text: str, expected_sectors: list[str]) -> dict:
    data = _extract_json(raw_text)

    raw_narratives = data.get("sector_narratives")
    if not isinstance(raw_narratives, dict):
        raise SectorReportParseError(f"sector_narratives mancante o non è un oggetto: {raw_narratives!r}")
    narratives: dict[str, str] = {}
    for sector in expected_sectors:
        text = str(raw_narratives.get(sector, "")).strip()
        if not text:
            raise SectorReportParseError(f"sector_narratives manca del settore {sector!r} o è vuoto")
        narratives[sector] = text

    cross_sector_note = str(data.get("cross_sector_note", "")).strip()
    if not cross_sector_note:
        raise SectorReportParseError("cross_sector_note mancante")

    direction = str(data.get("overall_direction", "")).upper()
    if direction not in VALID_DIRECTIONS:
        raise SectorReportParseError(f"overall_direction non valido: {direction!r}")

    return {"sector_narratives": narratives, "cross_sector_note": cross_sector_note, "overall_direction": direction}


def generate_sector_report(
    asset_records: dict[str, dict],
    aggregates: dict,
    sector_of: dict[str, str],
    sector_aggregates: dict[str, dict],
) -> dict:
    expected_sectors = sorted({sector_of.get(a, "Altro") for a in asset_records})
    prompt = build_sector_prompt(asset_records, aggregates, sector_of, sector_aggregates)
    raw = call_model(prompt)
    return parse_sector_report(raw, expected_sectors)
