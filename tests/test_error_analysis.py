from __future__ import annotations

from src import config, error_analysis, storage


def _outcome(**overrides) -> dict:
    base = {
        "prediction_id": "p1",
        "asset": "AAPL",
        "horizon": "1d",
        "evaluated_at": "2026-09-01T12:00:00Z",
        "price_at_target": 225.0,
        "target_bar_date": "2026-09-01",
        "actual_change_pct": 1.5,
        "actual_class": "UP",
        "predicted_class": "UP",
        "confidence": 72,
        "correct": True,
    }
    base.update(overrides)
    return base


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "ERROR_ANALYSIS_FILE", str(tmp_path / "ERROR_ANALYSIS.md"))


def _generate(tmp_path) -> str:
    error_analysis.generate_report()
    with open(config.ERROR_ANALYSIS_FILE, "r", encoding="utf-8") as fh:
        return fh.read()


def test_nessuna_previsione_valutata(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    content = _generate(tmp_path)

    assert "Nessuna previsione ancora valutata." in content


def test_campione_piccolo_mostra_avviso(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    storage.append_record(config.outcomes_file("AAPL"), _outcome(prediction_id="p1"))

    content = _generate(tmp_path)

    assert "Campione ancora piccolo" in content
    assert f"soglia indicativa {error_analysis.MIN_SAMPLE_SIZE}" in content


def test_campione_sufficiente_non_mostra_avviso(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(error_analysis, "MIN_SAMPLE_SIZE", 2)
    storage.append_record(config.outcomes_file("AAPL"), _outcome(prediction_id="p1"))
    storage.append_record(config.outcomes_file("AAPL"), _outcome(prediction_id="p2"))

    content = _generate(tmp_path)

    assert "Campione ancora piccolo" not in content


def test_classe_mai_prevista_ma_osservata_viene_segnalata(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    for i in range(4):
        storage.append_record(
            config.outcomes_file("MSFT"),
            _outcome(prediction_id=f"p{i}", asset="MSFT", predicted_class="UP", actual_class="DOWN", correct=False),
        )

    content = _generate(tmp_path)

    assert "**DOWN** osservata nella realtà 4 volte (100.0%) ma mai prevista dal modello." in content


def test_classe_prevista_spesso_ma_mai_corretta_viene_segnalata(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    for i in range(3):
        storage.append_record(
            config.outcomes_file("NVDA"),
            _outcome(prediction_id=f"p{i}", asset="NVDA", predicted_class="UP", actual_class="DOWN", correct=False),
        )

    content = _generate(tmp_path)

    assert "Quando ha previsto **UP** (3 volte), non ha mai indovinato." in content


def test_nessun_bias_quando_sotto_soglia(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    # 1 sola previsione, sbagliata: troppo poco per flaggare uno 0% di
    # accuratezza (MIN_N_FOR_ZERO_ACCURACY_FLAG=3), ma lo scarto tra
    # previsto e reale supera comunque BIAS_THRESHOLD_PCT con un campione
    # così piccolo — verifichiamo quindi solo che non scatti il flag sulla
    # bassa numerosità per classe, non l'assenza totale di flag.
    storage.append_record(
        config.outcomes_file("AAPL"),
        _outcome(prediction_id="p1", predicted_class="UP", actual_class="DOWN", correct=False),
    )

    content = _generate(tmp_path)

    assert "non ha mai indovinato" not in content


def test_tabelle_per_asset_e_per_classe(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    storage.append_record(
        config.outcomes_file("AAPL"),
        _outcome(prediction_id="p1", asset="AAPL", predicted_class="UP", actual_class="UP", correct=True),
    )
    storage.append_record(
        config.outcomes_file("AAPL"),
        _outcome(prediction_id="p2", asset="AAPL", predicted_class="UP", actual_class="DOWN", correct=False),
    )

    content = _generate(tmp_path)

    assert "| AAPL | 2 | 1 | 50.0% |" in content
    assert "| UP | 2 | 1 | 50.0% |" in content
    assert "| DOWN | 0 | — | mai prevista |" in content
    assert "| FLAT | 0 | — | mai prevista |" in content
