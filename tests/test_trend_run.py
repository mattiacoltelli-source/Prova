"""Test unitari per la cadenza per-asset di src/trend_run.py (_period_key/
_is_due/_mark_asset_done): THK/Harmonic Drive/TER restano mensili, VRT è
trimestrale — stesso file di stato (trend_done.json), logica condivisa,
cadenza diversa per asset via config.ASSET_CADENCE_MONTHS."""
from __future__ import annotations

import datetime as dt
from unittest.mock import patch

from src import storage, trend_run


def test_period_key_mensile_e_sempre_il_mese_corrente():
    assert trend_run._period_key("THK", dt.date(2026, 9, 5)) == "2026-09"
    assert trend_run._period_key("THK", dt.date(2026, 9, 30)) == "2026-09"
    assert trend_run._period_key("TER", dt.date(2026, 1, 1)) == "2026-01"


def test_period_key_trimestrale_raggruppa_per_trimestre_solare():
    assert trend_run._period_key("VRT", dt.date(2026, 1, 15)) == "2026-01"
    assert trend_run._period_key("VRT", dt.date(2026, 2, 2)) == "2026-01"
    assert trend_run._period_key("VRT", dt.date(2026, 3, 31)) == "2026-01"
    assert trend_run._period_key("VRT", dt.date(2026, 4, 2)) == "2026-04"
    assert trend_run._period_key("VRT", dt.date(2026, 6, 30)) == "2026-04"
    assert trend_run._period_key("VRT", dt.date(2026, 7, 1)) == "2026-07"
    assert trend_run._period_key("VRT", dt.date(2026, 10, 1)) == "2026-10"
    assert trend_run._period_key("VRT", dt.date(2026, 12, 31)) == "2026-10"


def test_is_due_e_mark_asset_done_ciclo_completo(tmp_path, monkeypatch):
    monkeypatch.setattr(trend_run.config, "STATE_DIR", str(tmp_path))

    today = dt.date(2026, 9, 2)
    assert trend_run._is_due("THK", today, trend_run._load_done()) is True
    assert trend_run._is_due("VRT", today, trend_run._load_done()) is True

    trend_run._mark_asset_done("THK", today)
    done = trend_run._load_done()
    assert trend_run._is_due("THK", today, done) is False
    # VRT non ancora fatto: resta dovuto anche dopo che THK è stato segnato.
    assert trend_run._is_due("VRT", today, done) is True

    trend_run._mark_asset_done("VRT", today)
    done = trend_run._load_done()
    assert trend_run._is_due("VRT", today, done) is False

    # THK: un mese dopo (ottobre) torna dovuto (nuovo periodo mensile).
    next_month = dt.date(2026, 10, 3)
    assert trend_run._is_due("THK", next_month, done) is True
    # VRT: più avanti nello STESSO trimestre (settembre, ancora Q3 = lug-set)
    # NON è ancora dovuto.
    same_quarter_later = dt.date(2026, 9, 20)
    assert trend_run._period_key("VRT", today) == "2026-07"
    assert trend_run._period_key("VRT", same_quarter_later) == "2026-07"
    assert trend_run._is_due("VRT", same_quarter_later, done) is False
    # VRT: al trimestre successivo (Q4, da ottobre) torna dovuto.
    assert trend_run._period_key("VRT", next_month) == "2026-10"
    assert trend_run._is_due("VRT", next_month, done) is True


def test_asset_cadence_months_copre_tutti_gli_asset():
    from src import config
    for asset in config.ROBOTICS_ASSETS:
        assert asset in config.ASSET_CADENCE_MONTHS
        assert asset in config.TREND_PROMPT_CONTEXT
        ctx = config.TREND_PROMPT_CONTEXT[asset]
        assert ctx["sector_label"]
        assert ctx["benchmark_intro"]
        assert ctx["cyclicality_note"]


def _fake_trend_record(asset: str, direction: str = "RIALZISTA") -> dict:
    return {
        "asset": asset, "ticker": asset, "generated_at": "2026-09-17T12:00:00Z",
        "model": "x", "trend_direction": direction, "confidence": 70,
        "sox_correlation": 0.5,
        "metrics": {"cycle_phase": "molto_estesa", "price_vs_ma_pct": 50.0, "ma_weeks": 200,
                    "cagr_by_years": {"1": 0.5}, "extended_episodes": {"avg_correction_pct": -10.0}},
    }


def test_run_sector_summary_scrive_record_e_segna_fatto(tmp_path, monkeypatch):
    monkeypatch.setattr(trend_run.config, "STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(trend_run.config, "DATA_DIR", str(tmp_path / "data"))
    storage.append_record(trend_run.config.trend_file("THK"), _fake_trend_record("THK"))
    storage.append_record(trend_run.config.trend_file("TER"), _fake_trend_record("TER"))

    fake_analysis = {"sector_narrative": "Entrambi in fase estesa.", "overall_direction": "RIALZISTA"}
    with patch("src.trend_run.sector_report.generate_sector_report", return_value=fake_analysis) as mock_gen:
        trend_run._run_sector_summary(dt.datetime(2026, 9, 17, tzinfo=dt.timezone.utc), dt.date(2026, 9, 17), dry_run=False, force=False)

    mock_gen.assert_called_once()
    saved = storage.read_all(trend_run.config.sector_summary_file())
    assert len(saved) == 1
    assert saved[0]["sector_narrative"] == "Entrambi in fase estesa."
    assert saved[0]["overall_direction"] == "RIALZISTA"
    assert set(saved[0]["assets_snapshot"].keys()) == {"THK", "TER"}

    done = trend_run._load_done()
    assert done[trend_run.config.SECTOR_SUMMARY_KEY] == "2026-09"

    # Un secondo run nello stesso periodo non deve rigenerare (già fatto).
    with patch("src.trend_run.sector_report.generate_sector_report", return_value=fake_analysis) as mock_gen2:
        trend_run._run_sector_summary(dt.datetime(2026, 9, 20, tzinfo=dt.timezone.utc), dt.date(2026, 9, 20), dry_run=False, force=False)
    mock_gen2.assert_not_called()


def test_run_sector_summary_salta_se_meno_di_2_asset_hanno_dati(tmp_path, monkeypatch):
    monkeypatch.setattr(trend_run.config, "STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(trend_run.config, "DATA_DIR", str(tmp_path / "data"))
    storage.append_record(trend_run.config.trend_file("THK"), _fake_trend_record("THK"))

    with patch("src.trend_run.sector_report.generate_sector_report") as mock_gen:
        trend_run._run_sector_summary(dt.datetime(2026, 9, 17, tzinfo=dt.timezone.utc), dt.date(2026, 9, 17), dry_run=False, force=False)
    mock_gen.assert_not_called()
    assert not __import__("os").path.exists(trend_run.config.sector_summary_file())


def test_run_sector_summary_dry_run_non_scrive_nulla(tmp_path, monkeypatch):
    monkeypatch.setattr(trend_run.config, "STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(trend_run.config, "DATA_DIR", str(tmp_path / "data"))
    storage.append_record(trend_run.config.trend_file("THK"), _fake_trend_record("THK"))
    storage.append_record(trend_run.config.trend_file("TER"), _fake_trend_record("TER"))

    fake_analysis = {"sector_narrative": "test", "overall_direction": "RIALZISTA"}
    with patch("src.trend_run.sector_report.generate_sector_report", return_value=fake_analysis):
        trend_run._run_sector_summary(dt.datetime(2026, 9, 17, tzinfo=dt.timezone.utc), dt.date(2026, 9, 17), dry_run=True, force=False)

    assert not __import__("os").path.exists(trend_run.config.sector_summary_file())
    assert trend_run.config.SECTOR_SUMMARY_KEY not in trend_run._load_done()
