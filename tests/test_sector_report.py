"""Test unitari per src/sector_report.py e trend_analysis.compute_sector_aggregates:
la sintesi mensile "a livello di paniere" che confronta le ultime letture
disponibili degli asset, raggruppati per settore, invece di leggerli uno
per volta o mescolarli in un unico paragrafo."""
from __future__ import annotations

import pytest

from src import sector_report, trend_analysis

THK_RECORD = {
    "generated_at": "2026-09-17T12:00:00Z",
    "trend_direction": "RIALZISTA",
    "confidence": 72,
    "sox_correlation": 0.557,
    "metrics": {
        "cycle_phase": "molto_estesa",
        "price_vs_ma_pct": 59.3,
        "ma_weeks": 200,
        "cagr_by_years": {"1": 0.4747},
        "extended_episodes": {"avg_correction_pct": -7.4, "num_episodes": 3},
    },
}
TER_RECORD = {
    "generated_at": "2026-09-17T12:00:00Z",
    "trend_direction": "RIALZISTA",
    "confidence": 72,
    "sox_correlation": 0.852,
    "metrics": {
        "cycle_phase": "molto_estesa",
        "price_vs_ma_pct": 120.0,
        "ma_weeks": 200,
        "cagr_by_years": {"1": 1.9966},
        "extended_episodes": {"avg_correction_pct": -52.2, "num_episodes": 3},
    },
}
VRT_RECORD = {
    "generated_at": "2026-09-17T12:08:00Z",
    "trend_direction": "RIALZISTA",
    "confidence": 65,
    "sox_correlation": 0.498,
    "metrics": {
        "cycle_phase": "compressa",
        "price_vs_ma_pct": -5.0,
        "ma_weeks": 200,
        "cagr_by_years": {"1": 0.75},
        "extended_episodes": {"avg_correction_pct": -59.4, "num_episodes": 1},
    },
}


def test_compute_sector_aggregates_conta_fasi_e_direzioni():
    agg = trend_analysis.compute_sector_aggregates({"THK": THK_RECORD, "TER": TER_RECORD, "VRT": VRT_RECORD})
    assert agg["num_assets"] == 3
    assert agg["phase_counts"] == {"molto_estesa": 2, "compressa": 1}
    assert agg["direction_counts"] == {"RIALZISTA": 3}
    assert agg["any_asset_compressed"] is True


def test_compute_sector_aggregates_range_price_vs_ma():
    agg = trend_analysis.compute_sector_aggregates({"THK": THK_RECORD, "TER": TER_RECORD, "VRT": VRT_RECORD})
    r = agg["price_vs_ma_range"]
    assert r["min_asset"] == "VRT" and r["min_value"] == -5.0
    assert r["max_asset"] == "TER" and r["max_value"] == 120.0


def test_compute_sector_aggregates_range_sox_correlation():
    agg = trend_analysis.compute_sector_aggregates({"THK": THK_RECORD, "TER": TER_RECORD, "VRT": VRT_RECORD})
    r = agg["sox_correlation_range"]
    assert r["min_asset"] == "VRT" and r["max_asset"] == "TER"


def test_compute_sector_aggregates_nessun_asset_compresso():
    agg = trend_analysis.compute_sector_aggregates({"THK": THK_RECORD, "TER": TER_RECORD})
    assert agg["any_asset_compressed"] is False
    assert agg["phase_counts"] == {"molto_estesa": 2}


def test_compute_sector_aggregates_campi_mancanti_non_esplodono():
    # Un record senza extended_episodes/sox_correlation non deve rompere l'aggregazione.
    minimal = {"trend_direction": "LATERALE", "metrics": {"cycle_phase": "neutrale", "price_vs_ma_pct": 2.0}}
    agg = trend_analysis.compute_sector_aggregates({"THK": THK_RECORD, "X": minimal})
    assert agg["num_assets"] == 2
    assert agg["avg_correction_range"]["min_asset"] == "THK"  # solo THK ha extended_episodes


SECTOR_OF = {"THK": "Robotica", "TER": "Robotica", "VRT": "Infrastruttura"}


def test_build_sector_prompt_include_dati_reali_non_inventa_numeri():
    records = {"THK": THK_RECORD, "TER": TER_RECORD, "VRT": VRT_RECORD}
    agg = trend_analysis.compute_sector_aggregates(records)
    sector_agg = {
        "Robotica": trend_analysis.compute_sector_aggregates({"THK": THK_RECORD, "TER": TER_RECORD}),
        "Infrastruttura": trend_analysis.compute_sector_aggregates({"VRT": VRT_RECORD}),
    }
    prompt = sector_report.build_sector_prompt(records, agg, SECTOR_OF, sector_agg)
    assert "THK" in prompt and "TER" in prompt and "VRT" in prompt
    assert "molto_estesa" in prompt
    assert "0.852" in prompt  # correlazione SOX di TER, letta dal dato reale
    assert "Robotica" in prompt and "Infrastruttura" in prompt
    assert "GIÀ CALCOLATE" in prompt or "già calcolate" in prompt
    assert "NON ricalcolarle" in prompt
    assert "date di lettura diverse" in prompt
    assert "NON mescolare titoli di settori diversi" in prompt


def test_build_sector_prompt_non_mescola_asset_di_settori_diversi():
    """Ogni titolo deve comparire nel blocco del proprio settore, non in entrambi."""
    records = {"THK": THK_RECORD, "VRT": VRT_RECORD}
    agg = trend_analysis.compute_sector_aggregates(records)
    sector_agg = {
        "Robotica": trend_analysis.compute_sector_aggregates({"THK": THK_RECORD}),
        "Infrastruttura": trend_analysis.compute_sector_aggregates({"VRT": VRT_RECORD}),
    }
    prompt = sector_report.build_sector_prompt(records, agg, SECTOR_OF, sector_agg)
    robotica_block = prompt[prompt.index("## Robotica") : prompt.index("## Infrastruttura")]
    assert "THK" in robotica_block and "VRT" not in robotica_block


def test_parse_sector_report_ok():
    raw = (
        '{"sector_narratives": {"Robotica": "Tutti e 2 in fase estesa.", "Infrastruttura": "Compressa."}, '
        '"cross_sector_note": "La robotica è più esposta.", "overall_direction": "RIALZISTA"}'
    )
    result = sector_report.parse_sector_report(raw, ["Robotica", "Infrastruttura"])
    assert result["sector_narratives"]["Robotica"] == "Tutti e 2 in fase estesa."
    assert result["sector_narratives"]["Infrastruttura"] == "Compressa."
    assert result["cross_sector_note"] == "La robotica è più esposta."
    assert result["overall_direction"] == "RIALZISTA"


def test_parse_sector_report_direzione_invalida():
    raw = '{"sector_narratives": {"Robotica": "testo"}, "cross_sector_note": "nota", "overall_direction": "BOH"}'
    with pytest.raises(sector_report.SectorReportParseError):
        sector_report.parse_sector_report(raw, ["Robotica"])


def test_parse_sector_report_settore_mancante():
    raw = '{"sector_narratives": {"Robotica": "testo"}, "cross_sector_note": "nota", "overall_direction": "RIALZISTA"}'
    with pytest.raises(sector_report.SectorReportParseError):
        sector_report.parse_sector_report(raw, ["Robotica", "Infrastruttura"])


def test_parse_sector_report_narrativa_vuota():
    raw = '{"sector_narratives": {"Robotica": ""}, "cross_sector_note": "nota", "overall_direction": "RIALZISTA"}'
    with pytest.raises(sector_report.SectorReportParseError):
        sector_report.parse_sector_report(raw, ["Robotica"])


def test_parse_sector_report_cross_sector_note_mancante():
    raw = '{"sector_narratives": {"Robotica": "testo"}, "cross_sector_note": "", "overall_direction": "RIALZISTA"}'
    with pytest.raises(sector_report.SectorReportParseError):
        sector_report.parse_sector_report(raw, ["Robotica"])


def test_parse_sector_report_nessun_json():
    with pytest.raises(sector_report.SectorReportParseError):
        sector_report.parse_sector_report("non è json", ["Robotica"])
