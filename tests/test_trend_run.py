"""Test unitari per la cadenza per-asset di src/trend_run.py (_period_key/
_is_due/_mark_asset_done): THK/Harmonic Drive/TER restano mensili, VRT è
trimestrale — stesso file di stato (trend_done.json), logica condivisa,
cadenza diversa per asset via config.ASSET_CADENCE_MONTHS."""
from __future__ import annotations

import datetime as dt

from src import trend_run


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
