"""Test della v3 del prompt di previsione: secondo ancoraggio di
persistenza, oltre alle frequenze storiche già introdotte in v2.

Il difetto misurato sulla v2 non era più il bias di v1 (UP previsto nel
62% dei casi, DOWN mai) ma l'opposto: dare le frequenze storiche ha fatto
collassare il modello sulla classe più frequente — FLAT predetto l'81.7%
delle volte (104 previsioni valutate) contro un'occorrenza reale del 50%,
con un'accuratezza quando prevede FLAT (48.2%) indistinguibile dalla
frequenza di base. Questi test fissano le proprietà del prompt che
affrontano quel difetto, in modo che non tornino a perdersi in una
riscrittura futura.
"""
from __future__ import annotations

from src import config, predictor, report

BASE_RATES = {
    "pct": {"UP": 28.1, "DOWN": 24.8, "FLAT": 47.2},
    "observations": 6941,
    "first_date": "1999-02-11",
    "majority_class": "FLAT",
    "majority_pct": 47.2,
}

PERSISTENCE = {
    "actual_class": "DOWN",
    "evaluated_at": "2026-10-20T12:00:00+00:00",
    "global_accuracy_pct": 54.4,
    "global_n": 160,
}


def _flat(text: str) -> str:
    """Testo con spazi normalizzati (il prompt è testo a capo fisso)."""
    return " ".join(text.split())


def _prompt(persistence=PERSISTENCE, **kwargs):
    args = dict(
        asset="NVDA",
        horizon_code="1d",
        price=219.05,
        price_asof="2026-10-21T00:00:00+00:00",
        threshold_pct=1.06,
        news=[],
        fundamentals=None,
        macro={},
        base_rates=BASE_RATES,
        persistence=persistence,
    )
    args.update(kwargs)
    return predictor.build_prompt(**args)


def test_il_prompt_espone_lultimo_esito_reale_e_la_data():
    p = _prompt()
    assert "DOWN" in p
    assert "2026-10-20" in p


def test_il_prompt_dichiara_laccuratezza_globale_della_persistenza():
    p = _flat(_prompt())
    assert "54.4% su 160 casi" in p


def test_il_prompt_non_invita_ad_allinearsi_alla_persistenza():
    """Stesso rischio già mitigato (senza successo) per le frequenze
    storiche in v2: il prompt deve dire esplicitamente che non è un
    suggerimento su cosa rispondere."""
    p = _flat(_prompt())
    assert "Non è un suggerimento su cosa rispondere più delle frequenze" in p


def test_il_prompt_funziona_anche_senza_persistenza():
    """Nessun esito ancora risolto per questa coppia (es. asset appena
    aggiunto): il prompt deve restare valido e limitarsi a non mostrare
    un esito specifico."""
    p = _prompt(persistence=None)
    assert "Nessun esito ancora risolto per questa coppia asset/orizzonte." in p
    assert "predicted_class" not in p  # v3 chiede probabilità, non una classe
    assert "probability_up" in p


def test_il_prompt_menziona_entrambe_le_baseline_come_indipendenti():
    p = _flat(_prompt())
    assert "due baseline naive indipendenti" in p


def test_il_prompt_chiede_di_giustificare_lo_scostamento_da_entrambe():
    p = _flat(_prompt())
    assert "o dall'ultimo esito" in p


def test_generate_prediction_passa_la_persistenza_al_prompt(monkeypatch):
    """Regressione: generate_prediction ha già dodici parametri opzionali
    e li passa per nome a build_prompt — un inserimento in mezzo non deve
    spostare in silenzio base_rates/technicals o gli altri."""
    captured = {}

    def fake_call_model(prompt):
        captured["prompt"] = prompt
        return '{"probability_up": 0.3, "probability_down": 0.5, "probability_flat": 0.2, "reasoning_short": "test"}'

    monkeypatch.setattr(predictor, "call_model", fake_call_model)
    result = predictor.generate_prediction(
        "NVDA", "1d", 219.05, "x", 1.06, [], None, {},
        BASE_RATES,
        PERSISTENCE,
        {"sma_trend": "rialzista"},
        None,
        None,
        None,
    )
    assert result["predicted_class"] == "DOWN"
    assert "54.4% su 160 casi" in captured["prompt"], "la persistenza deve arrivare nel prompt"
    assert "28.1%" in captured["prompt"], "le frequenze storiche devono restare, non essere spostate"
    assert "Trend di fondo (SMA 50/200): rialzista" in captured["prompt"], (
        "technicals non deve essere finito nel parametro sbagliato"
    )


def test_last_resolved_outcome_nessun_esito_per_la_coppia():
    assert report.last_resolved_outcome([], "NVDA", "1d") is None
    rows = [{"asset": "NVDA", "horizon": "7d", "actual_class": "UP", "evaluated_at": "2026-10-01T00:00:00Z"}]
    assert report.last_resolved_outcome(rows, "NVDA", "1d") is None


def test_last_resolved_outcome_prende_il_piu_recente_per_la_coppia_esatta():
    rows = [
        {"asset": "NVDA", "horizon": "1d", "actual_class": "UP", "evaluated_at": "2026-10-01T00:00:00Z"},
        {"asset": "NVDA", "horizon": "1d", "actual_class": "DOWN", "evaluated_at": "2026-10-20T00:00:00Z"},
        {"asset": "NVDA", "horizon": "1d", "actual_class": "FLAT", "evaluated_at": "2026-10-10T00:00:00Z"},
        {"asset": "AAPL", "horizon": "1d", "actual_class": "UP", "evaluated_at": "2026-10-21T00:00:00Z"},
        {"asset": "NVDA", "horizon": "7d", "actual_class": "UP", "evaluated_at": "2026-10-21T00:00:00Z"},
    ]
    last = report.last_resolved_outcome(rows, "NVDA", "1d")
    assert last == {"actual_class": "DOWN", "evaluated_at": "2026-10-20T00:00:00Z"}


def test_persistence_accuracy_summary_su_righe_date():
    rows = [
        {"asset": "NVDA", "horizon": "1d", "actual_class": "UP", "evaluated_at": "2026-10-01T00:00:00Z"},
        {"asset": "NVDA", "horizon": "1d", "actual_class": "UP", "evaluated_at": "2026-10-02T00:00:00Z"},
        {"asset": "NVDA", "horizon": "1d", "actual_class": "DOWN", "evaluated_at": "2026-10-03T00:00:00Z"},
    ]
    total, pct = report.persistence_accuracy_summary(rows)
    assert total == 2  # 2 confronti consecutivi possibili su 3 esiti
    assert pct == 50.0  # 2026-10-02 confermato (UP==UP), 2026-10-03 no (DOWN!=UP)


def test_prompt_version_configurata_e_intera():
    assert isinstance(config.PROMPT_VERSION, int)
    assert config.PROMPT_VERSION >= 3
