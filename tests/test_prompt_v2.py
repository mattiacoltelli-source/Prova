"""Test della v2 del prompt di previsione e del versionamento.

Il difetto misurato sulla v1 era che il modello riceveva una lunga lista di
indicatori di trend e nessuna frequenza di base: UP previsto nel 62% dei
casi contro un 28-38% di occorrenza reale, DOWN mai previsto contro un 45%.
Questi test fissano le proprietà del prompt che affrontano quel difetto, in
modo che non tornino a perdersi in una riscrittura futura.
"""
from __future__ import annotations

from src import baseline, config, predictor, report

BASE_RATES = {
    "pct": {"UP": 28.1, "DOWN": 24.8, "FLAT": 47.2},
    "observations": 6941,
    "first_date": "1999-02-11",
    "majority_class": "FLAT",
    "majority_pct": 47.2,
}


def _flat(text: str) -> str:
    """Testo con spazi normalizzati.

    Il prompt è testo a capo fisso: un'asserzione su una frase non deve
    rompersi solo perché la frase finisce per cadere a cavallo di due righe.
    """
    return " ".join(text.split())


def _prompt(base_rates=BASE_RATES, **kwargs):
    args = dict(
        asset="NVDA",
        horizon_code="1d",
        price=219.05,
        price_asof="2026-09-17T00:00:00+00:00",
        threshold_pct=1.06,
        news=[],
        fundamentals=None,
        macro={},
        base_rates=base_rates,
    )
    args.update(kwargs)
    return predictor.build_prompt(**args)


def test_il_prompt_espone_le_frequenze_storiche_delle_tre_classi():
    p = _prompt()
    assert "28.1%" in p and "24.8%" in p and "47.2%" in p
    assert "6941" in p, "va detto su quante osservazioni sono calcolate"
    assert "1999-02-11" in p, "va detto da quando"


def test_il_prompt_dichiara_la_baseline_da_battere():
    """Il modello deve sapere che viene confrontato con 'prevedi sempre la
    classe più frequente', altrimenti non ha modo di capire cosa conti come
    risultato utile."""
    p = _flat(_prompt())
    assert "47.2% di accuratezza" in p
    assert "FLAT" in p


def test_il_prompt_non_invita_ad_allinearsi_alle_frequenze():
    """Rischio opposto al bias della v1: se il prompt suggerisse di seguire
    le frequenze, il modello collasserebbe sulla classe più frequente
    ottenendo la baseline e nessun valore aggiunto."""
    p = _flat(_prompt())
    assert "non allinearti a queste percentuali" in p
    assert "Non è un suggerimento su cosa rispondere" in p


def test_il_prompt_separa_regime_di_trend_da_probabilita_sullorizzonte():
    """È la correzione centrale: 'il titolo sale' non implica 'supererà la
    banda in questo orizzonte'."""
    p = _flat(_prompt())
    assert "DUE COSE DA NON CONFONDERE" in p
    assert "REGIME ATTUALE" in p
    assert "non implica" in p
    # La soglia va citata dentro la spiegazione, non solo nella legenda.
    assert p.count("1.06%") >= 3


def test_il_prompt_menziona_down_come_esito_legittimo():
    """DOWN non è stata prevista nemmeno una volta in 45 previsioni v1."""
    p = _prompt()
    down_section = p[p.index("Tutte e tre le classi") :]
    assert "DOWN" in down_section


def test_il_prompt_funziona_anche_senza_frequenze_di_base():
    """data/baseline.json è opzionale: senza di esso il prompt deve restare
    valido e limitarsi a non mostrare la sezione."""
    p = _prompt(base_rates=None)
    assert "Non disponibili per questa coppia asset/orizzonte." in p
    assert "predicted_class" in p, "il resto del prompt deve restare intatto"


def test_generate_prediction_passa_le_frequenze_al_prompt(monkeypatch):
    """Regressione: build_prompt ha molti parametri opzionali e
    generate_prediction li passava per posizione — inserire base_rates in
    mezzo avrebbe spostato in silenzio technicals e i successivi."""
    captured = {}

    def fake_call_model(prompt):
        captured["prompt"] = prompt
        return '{"predicted_class": "FLAT", "confidence": 40, "reasoning_short": "test"}'

    monkeypatch.setattr(predictor, "call_model", fake_call_model)
    result = predictor.generate_prediction(
        "NVDA", "1d", 219.05, "x", 1.06, [], None, {},
        BASE_RATES,
        {"sma_trend": "rialzista"},
        None,
        None,
    )
    assert result["predicted_class"] == "FLAT"
    assert "28.1%" in captured["prompt"], "le frequenze devono arrivare nel prompt"
    assert "Trend di fondo (SMA 50/200): rialzista" in captured["prompt"], (
        "technicals non deve essere finito nel parametro sbagliato"
    )


def test_base_rates_none_per_coppie_sconosciute():
    assert baseline.base_rates("TICKER_INESISTENTE", "1d") is None
    assert baseline.base_rates("NVDA", "99d") is None


def test_base_rates_legge_una_coppia_reale():
    rates = baseline.base_rates("NVDA", "1d")
    assert rates is not None
    assert set(rates["pct"]) == {"UP", "DOWN", "FLAT"}
    assert abs(sum(rates["pct"].values()) - 100) < 0.5


def test_report_separa_laccuratezza_per_versione_di_prompt():
    rows = [
        {"asset": "NVDA", "horizon": "1d", "predicted_class": "UP", "actual_class": "UP",
         "correct": True, "confidence": 60, "evaluated_at": "2026-09-01T00:00:00Z",
         "prompt_version": 2},
        {"asset": "NVDA", "horizon": "1d", "predicted_class": "UP", "actual_class": "DOWN",
         "correct": False, "confidence": 60, "evaluated_at": "2026-09-02T00:00:00Z"},
    ]
    md = report.render_markdown(rows)
    assert "## Accuratezza per versione del prompt" in md
    # La riga senza prompt_version è una previsione v1 per definizione.
    assert "| v1 | 1 | 0.0% |" in md
    assert "| v2 | 1 | 100.0% |" in md


def test_report_non_mostra_la_tabella_con_una_sola_versione():
    rows = [
        {"asset": "NVDA", "horizon": "1d", "predicted_class": "UP", "actual_class": "UP",
         "correct": True, "confidence": 60, "evaluated_at": "2026-09-01T00:00:00Z"},
    ]
    assert "## Accuratezza per versione del prompt" not in report.render_markdown(rows)


def test_prompt_version_configurata_e_intera():
    assert isinstance(config.PROMPT_VERSION, int)
    assert config.PROMPT_VERSION >= 2
