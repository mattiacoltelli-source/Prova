"""Test unitari per src/market_regime.py: rendimento assoluto di un
indice, percentile VIX e classificazione risk-on/risk-off — tutto calcolo
puro su fixture, nessuna chiamata di rete."""
from __future__ import annotations

from src import market_regime


def _bars(closes: list[float]) -> list[dict]:
    return [{"date": f"2026-01-{i + 1:02d}", "close": c} for i, c in enumerate(closes)]


def _vix_history(values: list[float]) -> list[dict]:
    return [{"date": f"2025-01-{i + 1:02d}", "value": v} for i, v in enumerate(values)]


# --- compute_index_return_pct -------------------------------------------


def test_compute_index_return_pct_calcola_il_rendimento_assoluto():
    bars = _bars([100.0, 101.0, 99.0, 102.0, 105.0])
    # lookback_days=4 su 5 barre: dalla PRIMA barra (indice -5, 100.0) all'ultima (105.0).
    assert market_regime.compute_index_return_pct(bars, 4) == round((105.0 - 100.0) / 100.0 * 100, 2)


def test_compute_index_return_pct_none_se_storico_insufficiente():
    bars = _bars([100.0, 101.0])
    assert market_regime.compute_index_return_pct(bars, 5) is None


def test_compute_index_return_pct_usa_lookback_corretto_non_lintera_storia():
    # Se usasse tutta la storia invece delle ultime N barre, il risultato
    # cambierebbe: qui il rendimento a 1 giorno deve guardare solo le
    # ultime 2 barre, non l'intera serie.
    bars = _bars([50.0, 100.0, 110.0])
    assert market_regime.compute_index_return_pct(bars, 1) == round((110.0 - 100.0) / 100.0 * 100, 2)


# --- compute_vix_percentile ----------------------------------------------


def test_compute_vix_percentile_valore_massimo_e_percentile_100():
    values = list(range(1, 253))  # 252 valori, 1..252, ultimo è il massimo
    history = _vix_history([float(v) for v in values])
    result = market_regime.compute_vix_percentile(history, lookback_days=252)
    assert result["value"] == 252.0
    assert result["percentile"] == 100.0


def test_compute_vix_percentile_valore_minimo_e_percentile_basso():
    # L'ULTIMO elemento della lista è quello letto come "oggi": qui è il
    # più basso dei 252, quindi ci si aspetta un percentile molto basso.
    values = [float(v) for v in range(2, 253)] + [1.0]
    history = _vix_history(values)
    result = market_regime.compute_vix_percentile(history, lookback_days=252)
    assert result["value"] == 1.0
    # solo se stesso è <= a se stesso su 252 valori
    assert result["percentile"] == round(1 / 252 * 100, 1)


def test_compute_vix_percentile_none_se_storico_insufficiente():
    history = _vix_history([20.0] * 100)
    assert market_regime.compute_vix_percentile(history, lookback_days=252) is None


def test_compute_vix_percentile_include_data_del_valore_piu_recente():
    history = _vix_history([15.0] * 251 + [30.0])
    result = market_regime.compute_vix_percentile(history, lookback_days=252)
    assert result["date"] == history[-1]["date"]


# --- classify_risk_mode ---------------------------------------------------


def test_classify_risk_mode_risk_off_sopra_soglia():
    assert market_regime.classify_risk_mode(85.0) == "risk-off"
    assert market_regime.classify_risk_mode(market_regime.RISK_OFF_PERCENTILE) == "risk-off"


def test_classify_risk_mode_risk_on_sotto_soglia():
    assert market_regime.classify_risk_mode(10.0) == "risk-on"
    assert market_regime.classify_risk_mode(market_regime.RISK_ON_PERCENTILE) == "risk-on"


def test_classify_risk_mode_neutro_in_mezzo():
    assert market_regime.classify_risk_mode(55.0) == "neutro"


# --- compute_market_regime (orchestratore) --------------------------------


def test_compute_market_regime_bundle_completo():
    spy_bars = _bars([float(100 + i) for i in range(30)])
    qqq_bars = _bars([float(200 + i * 2) for i in range(30)])
    vix_history = _vix_history([20.0] * 251 + [45.0])  # ultimo valore alto

    regime = market_regime.compute_market_regime(spy_bars, qqq_bars, vix_history)

    assert regime["spy_return_1d_pct"] is not None
    assert regime["spy_return_5d_pct"] is not None
    assert regime["spy_return_20d_pct"] is not None
    assert regime["qqq_return_1d_pct"] is not None
    assert regime["vix"]["value"] == 45.0
    assert regime["risk_mode"] == "risk-off"


def test_compute_market_regime_fonti_mancanti_non_esplodono():
    """Una fonte che fallisce (None) non deve azzerare le altre — stesso
    principio 'segnale opzionale, mai bloccante' del resto del progetto."""
    regime = market_regime.compute_market_regime(None, None, None)
    assert regime == {}

    spy_bars = _bars([float(100 + i) for i in range(30)])
    regime = market_regime.compute_market_regime(spy_bars, None, None)
    assert regime["spy_return_1d_pct"] is not None
    assert "qqq_return_1d_pct" not in regime
    assert "vix" not in regime
    assert "risk_mode" not in regime


def test_compute_market_regime_vix_storico_insufficiente_niente_risk_mode():
    spy_bars = _bars([float(100 + i) for i in range(30)])
    vix_history = _vix_history([20.0] * 50)  # troppo corto per il percentile
    regime = market_regime.compute_market_regime(spy_bars, None, vix_history)
    assert "vix" not in regime
    assert "risk_mode" not in regime
