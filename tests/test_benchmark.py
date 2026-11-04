"""Test unitari per src/benchmark.py (le strategie di confronto Momentum e
Mean Reversion a regole fisse per la pagina Trading AI).

Nessuna chiamata di rete reale: prices.fetch_daily_history è sempre
mockata (stesso spirito di FakeResponse in test_market_scanner.py per
Yahoo Finance, ma qui si mocka direttamente la funzione pubblica condivisa
di data_sources/prices.py, non il livello HTTP sotto — benchmark.py non fa
più una chiamata Yahoo diretta dal 2026-11-02)."""
from __future__ import annotations

import datetime as dt
import json
from unittest.mock import patch

import pytest

from src import benchmark, config, storage


def _bars_from_closes(closes, volumes=None):
    """Converte una lista di chiusure in barre DailyBar con date sintetiche
    crescenti. Senza volume (default): gli indicatori che lo richiedono
    (volume relativo) tornano semplicemente None, 0 punti nel punteggio
    tecnico — mai un errore, coerente con "un indicatore non calcolabile
    non deve causare l'esclusione automatica" richiesto dall'utente. I
    test che verificano il punteggio tecnico passano volumes esplicito."""
    # Le barre finiscono all'ultima seduta attesa dai test (venerdì
    # 2026-10-30): altrimenti il controllo "dati vecchi" le scarterebbe.
    end = dt.date(2026, 10, 30)
    bars = []
    for i, close in enumerate(closes):
        bar = {"date": (end - dt.timedelta(days=len(closes) - 1 - i)).isoformat(), "close": close}
        if volumes is not None:
            bar["volume"] = volumes[i]
        bars.append(bar)
    return bars


def _momentum_fake_fetch(closes_by_symbol, bad_symbols=(), volumes_by_symbol=None):
    def fake_fetch(symbol, range_="1y"):
        if symbol in bad_symbols:
            raise benchmark.BenchmarkError(f"nessun dato per {symbol}")
        if symbol in closes_by_symbol:
            volumes = (volumes_by_symbol or {}).get(symbol)
            return _bars_from_closes(closes_by_symbol[symbol], volumes=volumes)
        raise AssertionError(f"simbolo inatteso in test: {symbol}")
    return fake_fetch


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AI_TRADER_MOMENTUM_FILE", str(tmp_path / "momentum.jsonl"))
    monkeypatch.setattr(config, "AI_TRADER_MOMENTUM_LOOKBACK_DAYS", 2)
    monkeypatch.setattr(config, "AI_TRADER_MOMENTUM_TOP_N", 2)
    monkeypatch.setattr(config, "AI_TRADER_MEANREV_FILE", str(tmp_path / "meanrev.jsonl"))
    monkeypatch.setattr(config, "AI_TRADER_MEANREV_LOOKBACK_DAYS", 2)
    monkeypatch.setattr(config, "AI_TRADER_MEANREV_TOP_N", 2)
    monkeypatch.setattr(config, "SCANNER_STOCKS", ["AAA", "BBB", "CCC"])
    monkeypatch.setattr(config, "AI_TRADER_EXCLUDED_TICKERS", [])
    monkeypatch.setattr(config, "STATE_DIR", str(tmp_path / "_state"))


_EXPERIMENT = {"start_equity_usd": 100000.0}


# ─── update_momentum ────────────────────────────────────────────────────────


def test_momentum_primo_giorno_sceglie_i_migliori_top_n_senza_perdita_di_ieri(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    # Lookback=2: serve closes[-1]/closes[-1-2] -> almeno 3 barre.
    closes_by_symbol = {
        "AAA": [100.0, 100.0, 110.0],  # momentum +10%
        "BBB": [100.0, 100.0, 90.0],   # momentum -10% (escluso: negativo)
        "CCC": [100.0, 100.0, 105.0],  # momentum +5%
    }
    with patch("src.benchmark.prices.fetch_daily_history", side_effect=_momentum_fake_fetch(closes_by_symbol)):
        benchmark.update_momentum(dt.date(2026, 10, 31), _EXPERIMENT)

    records = storage.read_all(config.AI_TRADER_MOMENTUM_FILE)
    assert len(records) == 1
    rec = records[0]
    # Giorno 1: nessun paniere precedente da segnare a mercato, equity invariata.
    assert rec["equity_usd"] == 100000.0
    assert rec["holdings"] == {"AAA": 0.175, "CCC": 0.175}
    assert rec["entry_prices"] == {"AAA": 110.0, "CCC": 105.0}
    assert rec["mark_prices"] == {"AAA": 110.0, "CCC": 105.0}
    assert rec["exit_prices"] == {}


def test_momentum_secondo_giorno_segna_a_mercato_il_paniere_di_ieri(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    storage.append_record(config.AI_TRADER_MOMENTUM_FILE, {
        "date": "2026-10-31",
        "equity_usd": 100000.0,
        "holdings": {"AAA": 0.5, "CCC": 0.5},
        "entry_prices": {"AAA": 110.0, "CCC": 105.0},
        "mark_prices": {"AAA": 110.0, "CCC": 105.0},
        "exit_prices": {},
    })
    closes_by_symbol = {
        "AAA": [100.0, 110.0, 121.0],  # +10% rispetto a ieri (110 -> 121)
        "BBB": [100.0, 90.0, 81.0],
        "CCC": [100.0, 105.0, 105.0],  # invariato rispetto a ieri
    }
    with patch("src.benchmark.prices.fetch_daily_history", side_effect=_momentum_fake_fetch(closes_by_symbol)):
        benchmark.update_momentum(dt.date(2026, 11, 1), _EXPERIMENT)

    records = storage.read_all(config.AI_TRADER_MOMENTUM_FILE)
    assert len(records) == 2
    rec = records[1]
    # 0.5*(121/110-1) + 0.5*(105/105-1) = 0.05 -> 100000 * 1.05 (pesi di
    # IERI, 0.5/0.5 come inseriti sopra nel fixture — il nuovo tetto del
    # 35% si applica solo alla selezione di OGGI, sotto)
    assert rec["equity_usd"] == 105000.0
    assert rec["holdings"] == {"AAA": 0.175, "CCC": 0.175}
    # Nessuno dei due è entrato oggi: entry_prices resta quello originale di ieri.
    assert rec["entry_prices"] == {"AAA": 110.0, "CCC": 105.0}
    # mark_prices invece è sempre quello di OGGI.
    assert rec["mark_prices"] == {"AAA": 121.0, "CCC": 105.0}


def test_momentum_entry_price_resta_invariato_su_piu_giorni_di_possesso(tmp_path, monkeypatch):
    """Bug reale corretto il 2026-11-02: un unico campo 'prices' veniva
    sovrascritto ogni giorno, quindi per un titolo tenuto da più giorni non
    c'era più modo di sapere a quanto era stato comprato all'origine."""
    _isolate(tmp_path, monkeypatch)
    storage.append_record(config.AI_TRADER_MOMENTUM_FILE, {
        "date": "2026-10-31", "equity_usd": 100000.0,
        "holdings": {"AAA": 1.0}, "entry_prices": {"AAA": 100.0},
        "mark_prices": {"AAA": 100.0}, "exit_prices": {},
    })
    storage.append_record(config.AI_TRADER_MOMENTUM_FILE, {
        "date": "2026-11-01", "equity_usd": 105000.0,
        "holdings": {"AAA": 1.0}, "entry_prices": {"AAA": 100.0},
        "mark_prices": {"AAA": 105.0}, "exit_prices": {},
    })
    # Terzo giorno: AAA ha ancora il momentum migliore, resta l'unica in portafoglio.
    closes_by_symbol = {
        "AAA": [100.0, 105.0, 112.0],
        "BBB": [100.0, 90.0, 80.0],
        "CCC": [100.0, 95.0, 90.0],
    }
    with patch("src.benchmark.prices.fetch_daily_history", side_effect=_momentum_fake_fetch(closes_by_symbol)):
        benchmark.update_momentum(dt.date(2026, 11, 2), _EXPERIMENT)

    rec = storage.read_all(config.AI_TRADER_MOMENTUM_FILE)[2]
    assert rec["entry_prices"]["AAA"] == 100.0  # invariato dal giorno 1
    assert rec["mark_prices"]["AAA"] == 112.0   # aggiornato a oggi


def test_momentum_salva_il_prezzo_di_uscita_di_un_titolo_venduto(tmp_path, monkeypatch):
    """Il prezzo di vendita di un titolo che esce dal paniere deve essere
    salvato nello stesso giorno in cui esce — altrimenti il frontend non
    potrebbe mai mostrare 'a quanto ha venduto' (richiesto dall'utente)."""
    _isolate(tmp_path, monkeypatch)
    storage.append_record(config.AI_TRADER_MOMENTUM_FILE, {
        "date": "2026-10-31", "equity_usd": 100000.0,
        "holdings": {"AAA": 0.5, "BBB": 0.5},
        "entry_prices": {"AAA": 100.0, "BBB": 100.0},
        "mark_prices": {"AAA": 100.0, "BBB": 100.0}, "exit_prices": {},
    })
    closes_by_symbol = {
        "AAA": [100.0, 105.0, 110.0],  # momentum +10%, resta
        "BBB": [100.0, 96.0, 95.0],    # momentum -5%, esce dal paniere (senza toccare lo stop)
        "CCC": [100.0, 100.0, 105.0],  # momentum +5%, entra nel paniere
    }
    with patch("src.benchmark.prices.fetch_daily_history", side_effect=_momentum_fake_fetch(closes_by_symbol)):
        benchmark.update_momentum(dt.date(2026, 11, 1), _EXPERIMENT)

    rec = storage.read_all(config.AI_TRADER_MOMENTUM_FILE)[1]
    assert rec["holdings"] == {"AAA": 0.175, "CCC": 0.175}  # BBB non c'è più
    assert rec["exit_prices"] == {"BBB": 95.0}  # solo lei è uscita oggi
    assert rec["entry_prices"]["CCC"] == 105.0  # appena entrata: ingresso = oggi


def test_momentum_nessun_titolo_con_momentum_positivo_va_tutto_in_contanti(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    closes_by_symbol = {
        "AAA": [100.0, 100.0, 95.0],
        "BBB": [100.0, 100.0, 90.0],
        "CCC": [100.0, 100.0, 99.0],
    }
    with patch("src.benchmark.prices.fetch_daily_history", side_effect=_momentum_fake_fetch(closes_by_symbol)):
        benchmark.update_momentum(dt.date(2026, 10, 31), _EXPERIMENT)

    rec = storage.read_all(config.AI_TRADER_MOMENTUM_FILE)[0]
    assert rec["holdings"] == {}
    assert rec["entry_prices"] == {}


def test_momentum_un_titolo_senza_dati_non_blocca_gli_altri(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "DATA_HEALTH_FAILURE_RATE_ALERT_THRESHOLD", 0.5)  # universo di test da 3 titoli: 1 su 3 è tollerato qui
    closes_by_symbol = {
        "AAA": [100.0, 100.0, 110.0],
        "CCC": [100.0, 100.0, 105.0],
    }
    with patch("src.benchmark.prices.fetch_daily_history", side_effect=_momentum_fake_fetch(closes_by_symbol, bad_symbols=["BBB"])):
        benchmark.update_momentum(dt.date(2026, 10, 31), _EXPERIMENT)

    rec = storage.read_all(config.AI_TRADER_MOMENTUM_FILE)[0]
    assert rec["holdings"] == {"AAA": 0.175, "CCC": 0.175}


def test_momentum_registra_lo_stato_di_salute_dati(tmp_path, monkeypatch):
    """update_momentum() deve scrivere data_health_benchmark.json con il
    simbolo fallito (src/data_health.py, richiesto dall'utente il
    2026-11-02)."""
    _isolate(tmp_path, monkeypatch)
    closes_by_symbol = {
        "AAA": [100.0, 100.0, 110.0],
        "CCC": [100.0, 100.0, 105.0],
    }
    with patch("src.benchmark.prices.fetch_daily_history", side_effect=_momentum_fake_fetch(closes_by_symbol, bad_symbols=["BBB"])):
        benchmark.update_momentum(dt.date(2026, 10, 31), _EXPERIMENT)

    with open(f"{config.STATE_DIR}/data_health_benchmark.json", encoding="utf-8") as fh:
        health = json.load(fh)
    assert health["total"] == 3
    assert health["failed_symbols"] == ["BBB"]


def test_momentum_stesso_giorno_e_idempotente_nessuna_chiamata_di_rete(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    storage.append_record(config.AI_TRADER_MOMENTUM_FILE, {
        "date": "2026-10-31", "equity_usd": 100000.0,
        "holdings": {}, "entry_prices": {}, "mark_prices": {}, "exit_prices": {},
    })

    def boom(*a, **k):
        raise AssertionError("non deve fare nessuna richiesta di rete: oggi è già registrato")

    with patch("src.benchmark.prices.fetch_daily_history", side_effect=boom):
        benchmark.update_momentum(dt.date(2026, 10, 31), _EXPERIMENT)

    assert len(storage.read_all(config.AI_TRADER_MOMENTUM_FILE)) == 1


# ─── derive_momentum_trades ─────────────────────────────────────────────────


def test_derive_momentum_trades_operazione_chiusa_ha_rendimento_corretto():
    history = [
        {"date": "2026-10-31", "holdings": {"AAA": 1.0},
         "entry_prices": {"AAA": 100.0}, "mark_prices": {"AAA": 100.0}, "exit_prices": {}},
        {"date": "2026-11-01", "holdings": {},
         "entry_prices": {}, "mark_prices": {}, "exit_prices": {"AAA": 110.0}},
    ]
    result = benchmark.derive_momentum_trades(history)
    assert result["open"] == []
    assert len(result["closed"]) == 1
    trade = result["closed"][0]
    assert trade == {
        "symbol": "AAA", "entry_date": "2026-10-31", "entry_price": 100.0,
        "exit_date": "2026-11-01", "exit_price": 110.0, "return_pct": 10.0,
    }


def test_derive_momentum_trades_posizione_ancora_aperta_usa_mark_price_piu_recente():
    history = [
        {"date": "2026-10-31", "holdings": {"AAA": 1.0},
         "entry_prices": {"AAA": 100.0}, "mark_prices": {"AAA": 100.0}, "exit_prices": {}},
        {"date": "2026-11-01", "holdings": {"AAA": 1.0},
         "entry_prices": {"AAA": 100.0}, "mark_prices": {"AAA": 108.0}, "exit_prices": {}},
    ]
    result = benchmark.derive_momentum_trades(history)
    assert result["closed"] == []
    assert len(result["open"]) == 1
    open_trade = result["open"][0]
    assert open_trade["entry_date"] == "2026-10-31"
    assert open_trade["entry_price"] == 100.0
    assert open_trade["mark_price"] == 108.0
    assert open_trade["return_pct"] == 8.0


def test_derive_momentum_trades_entry_price_non_cambia_tra_chiusura_e_riapertura():
    """Se un titolo esce e poi rientra più tardi, la seconda apertura deve
    avere il SUO prezzo d'ingresso, non quello della volta precedente."""
    history = [
        {"date": "2026-10-31", "holdings": {"AAA": 1.0},
         "entry_prices": {"AAA": 100.0}, "mark_prices": {"AAA": 100.0}, "exit_prices": {}},
        {"date": "2026-11-01", "holdings": {},
         "entry_prices": {}, "mark_prices": {}, "exit_prices": {"AAA": 90.0}},
        {"date": "2026-11-03", "holdings": {"AAA": 1.0},
         "entry_prices": {"AAA": 95.0}, "mark_prices": {"AAA": 95.0}, "exit_prices": {}},
    ]
    result = benchmark.derive_momentum_trades(history)
    assert len(result["closed"]) == 1
    assert result["closed"][0]["entry_price"] == 100.0
    assert result["closed"][0]["exit_price"] == 90.0
    assert len(result["open"]) == 1
    assert result["open"][0]["entry_date"] == "2026-11-03"
    assert result["open"][0]["entry_price"] == 95.0


def test_derive_momentum_trades_storico_vuoto_non_crasha():
    assert benchmark.derive_momentum_trades([]) == {"closed": [], "open": []}


# ─── update_mean_reversion — opposto filosofico di Momentum: tiene chi è ────
# sceso di più, mai chi è salito (stessa _update_strategy, pick_fallen=True).


def test_meanrev_primo_giorno_sceglie_i_peggiori_top_n_senza_perdita_di_ieri(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    closes_by_symbol = {
        "AAA": [100.0, 100.0, 90.0],   # -10%, il peggiore: scelto
        "BBB": [100.0, 100.0, 95.0],   # -5%, secondo peggiore: scelto
        "CCC": [100.0, 100.0, 110.0],  # +10%, salito: escluso (mai comprato)
    }
    with patch("src.benchmark.prices.fetch_daily_history", side_effect=_momentum_fake_fetch(closes_by_symbol)):
        benchmark.update_mean_reversion(dt.date(2026, 10, 31), _EXPERIMENT)

    rec = storage.read_all(config.AI_TRADER_MEANREV_FILE)[0]
    assert rec["equity_usd"] == 100000.0
    assert rec["holdings"] == {"AAA": 0.175, "BBB": 0.175}
    assert rec["entry_prices"] == {"AAA": 90.0, "BBB": 95.0}
    assert rec["exit_prices"] == {}


def test_meanrev_nessun_titolo_sceso_va_tutto_in_contanti(tmp_path, monkeypatch):
    """Specchio di test_momentum_nessun_titolo_con_momentum_positivo_va_tutto_in_contanti:
    qui è il caso opposto, nessun titolo sceso -> niente da comprare."""
    _isolate(tmp_path, monkeypatch)
    closes_by_symbol = {
        "AAA": [100.0, 100.0, 105.0],
        "BBB": [100.0, 100.0, 110.0],
        "CCC": [100.0, 100.0, 101.0],
    }
    with patch("src.benchmark.prices.fetch_daily_history", side_effect=_momentum_fake_fetch(closes_by_symbol)):
        benchmark.update_mean_reversion(dt.date(2026, 10, 31), _EXPERIMENT)

    rec = storage.read_all(config.AI_TRADER_MEANREV_FILE)[0]
    assert rec["holdings"] == {}
    assert rec["entry_prices"] == {}


def test_meanrev_secondo_giorno_segna_a_mercato_il_paniere_di_ieri(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    storage.append_record(config.AI_TRADER_MEANREV_FILE, {
        "date": "2026-10-31", "equity_usd": 100000.0,
        "holdings": {"AAA": 1.0}, "entry_prices": {"AAA": 90.0},
        "mark_prices": {"AAA": 90.0}, "exit_prices": {},
    })
    # AAA continua a scendere (ancora la peggiore): resta in portafoglio.
    closes_by_symbol = {
        "AAA": [100.0, 90.0, 85.0],
        "BBB": [100.0, 100.0, 102.0],
        "CCC": [100.0, 100.0, 103.0],
    }
    with patch("src.benchmark.prices.fetch_daily_history", side_effect=_momentum_fake_fetch(closes_by_symbol)):
        benchmark.update_mean_reversion(dt.date(2026, 11, 1), _EXPERIMENT)

    rec = storage.read_all(config.AI_TRADER_MEANREV_FILE)[1]
    # (85/90 - 1) = -5.56% (sopra lo stop -8%) -> 100000 * 0.9444
    assert rec["equity_usd"] == 94444.44
    assert rec["entry_prices"]["AAA"] == 90.0  # invariato, non è entrata oggi
    assert rec["mark_prices"]["AAA"] == 85.0


def test_meanrev_stesso_giorno_e_idempotente_nessuna_chiamata_di_rete(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    storage.append_record(config.AI_TRADER_MEANREV_FILE, {
        "date": "2026-10-31", "equity_usd": 100000.0,
        "holdings": {}, "entry_prices": {}, "mark_prices": {}, "exit_prices": {},
    })

    def boom(*a, **k):
        raise AssertionError("non deve fare nessuna richiesta di rete: oggi è già registrato")

    with patch("src.benchmark.prices.fetch_daily_history", side_effect=boom):
        benchmark.update_mean_reversion(dt.date(2026, 10, 31), _EXPERIMENT)

    assert len(storage.read_all(config.AI_TRADER_MEANREV_FILE)) == 1


def test_meanrev_momentum_isolati_su_file_separati(tmp_path, monkeypatch):
    """Le due strategie non devono mai scriversi a vicenda nello stesso file
    — stesso universo e stesso giorno, ma selezione opposta (chi scende per
    Mean Reversion è escluso da Momentum e viceversa)."""
    _isolate(tmp_path, monkeypatch)
    closes_by_symbol = {
        "AAA": [100.0, 100.0, 110.0],
        "BBB": [100.0, 100.0, 90.0],
        "CCC": [100.0, 100.0, 105.0],
    }
    with patch("src.benchmark.prices.fetch_daily_history", side_effect=_momentum_fake_fetch(closes_by_symbol)):
        benchmark.update_momentum(dt.date(2026, 10, 31), _EXPERIMENT)
        benchmark.update_mean_reversion(dt.date(2026, 10, 31), _EXPERIMENT)

    momentum_rec = storage.read_all(config.AI_TRADER_MOMENTUM_FILE)[0]
    meanrev_rec = storage.read_all(config.AI_TRADER_MEANREV_FILE)[0]
    assert momentum_rec["holdings"] == {"AAA": 0.175, "CCC": 0.175}
    assert meanrev_rec["holdings"] == {"BBB": 0.35}


def test_derive_meanrev_trades_usa_la_stessa_logica_di_derive_strategy_trades():
    history = [
        {"date": "2026-10-31", "holdings": {"BBB": 1.0},
         "entry_prices": {"BBB": 90.0}, "mark_prices": {"BBB": 90.0}, "exit_prices": {}},
        {"date": "2026-11-01", "holdings": {},
         "entry_prices": {}, "mark_prices": {}, "exit_prices": {"BBB": 95.0}},
    ]
    result = benchmark.derive_meanrev_trades(history)
    assert result["open"] == []
    assert result["closed"][0]["return_pct"] == pytest.approx((95.0 / 90.0 - 1) * 100, abs=0.01)


# ─── Punteggio tecnico: PRECEDENZA, non filtro (richiesto dall'utente ──────
# il 2026-11-02, "non voglio filtri rigidi... gli altri titoli devono
# comunque poter essere selezionati se hanno un buon rendimento").


def test_momentum_tier_sui_confini_dichiarati_con_lutente():
    assert benchmark._momentum_tier(5) == 2  # alta
    assert benchmark._momentum_tier(4) == 2  # alta
    assert benchmark._momentum_tier(3) == 1  # media
    assert benchmark._momentum_tier(2) == 1  # media
    assert benchmark._momentum_tier(1) == 0  # bassa
    assert benchmark._momentum_tier(0) == 0  # bassa


def test_meanrev_tier_sui_confini_dichiarati_con_lutente():
    assert benchmark._meanrev_tier(4) == 2  # alta
    assert benchmark._meanrev_tier(3) == 2  # alta
    assert benchmark._meanrev_tier(2) == 1  # media
    assert benchmark._meanrev_tier(1) == 1  # media
    assert benchmark._meanrev_tier(0) == 0  # bassa


def test_momentum_technical_score_storico_insufficiente_vale_zero_non_esclude():
    """Nessuno dei 5 indicatori è calcolabile con solo 5 barre (servono
    almeno 15 per l'RSI, 50/200 per le medie, 21 per il volume relativo):
    il punteggio è 0, MAI un errore o un'esclusione — la barra più corta
    possibile che il resto del modulo accetta comunque (len>=2)."""
    bars = _bars_from_closes([100.0, 101.0, 99.0, 102.0, 103.0])
    assert benchmark._momentum_technical_score(bars) == 0


def test_meanrev_technical_score_storico_insufficiente_vale_zero_non_esclude():
    bars = _bars_from_closes([100.0, 99.0, 98.0, 97.0, 96.0])
    assert benchmark._meanrev_technical_score(bars) == 0


def test_sma_rising_vero_falso_e_storico_insufficiente(monkeypatch):
    monkeypatch.setattr(config, "AI_TRADER_SMA_RISING_LOOKBACK_DAYS", 2)
    # SMA(3) oggi: media di [103,104,105]=104; SMA(3) di 2 giorni fa (su
    # [100,101,102,103]): media di [101,102,103]=102 -> crescente.
    rising = _bars_from_closes([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
    assert benchmark._sma_rising(rising, period=3) is True

    # Stessa logica al contrario: SMA(3) oggi 101, 2 giorni fa 103 -> calante.
    falling = _bars_from_closes([105.0, 104.0, 103.0, 102.0, 101.0, 100.0])
    assert benchmark._sma_rising(falling, period=3) is False

    # Storico troppo corto per una SMA(50): None, mai una delle due bool
    # sopra (il chiamante lo conta 0 punti, non un punto contro).
    assert benchmark._sma_rising(_bars_from_closes([100.0, 101.0]), period=50) is None


def test_momentum_technical_score_titolo_in_salita_sana_prende_punteggio_pieno(monkeypatch):
    """200 giorni piatti (SMA 200 stabile) poi 20 giorni di salita moderata
    con alternanza su/giù (RSI in zona 50-75, non ipercomprato) e volume
    dell'ultimo giorno sopra la media: tutti e 5 i criteri soddisfatti.
    Valori verificati con un calcolo diretto prima di scrivere il test, non
    indovinati — vedi i commenti con i valori osservati."""
    monkeypatch.setattr(config, "AI_TRADER_SMA_RISING_LOOKBACK_DAYS", 5)
    closes = [100.0] * 200
    pattern = [1.0, -0.8, 1.0, -0.7, 1.0, -0.8, 1.0, -0.7, 1.0, -0.8,
               1.0, -0.6, 1.0, -0.5, 0.8, -0.4, 0.8, -0.3, 0.8, 0.5]
    for pct in pattern:
        closes.append(round(closes[-1] * (1 + pct / 100), 4))
    volumes = [1_000_000] * (len(closes) - 1) + [1_500_000]
    bars = _bars_from_closes(closes, volumes=volumes)

    # RSI osservato ~67.5 (dentro 50-75), prezzo sopra SMA50/SMA200, SMA50
    # crescente, volume relativo 1.5 (>=1.2): punteggio pieno.
    assert benchmark._momentum_technical_score(bars) == 5
    assert benchmark._momentum_tier(5) == 2


def test_meanrev_technical_score_correzione_in_trend_di_fondo_positivo(monkeypatch):
    """200 giorni di salita lenta e costante (SMA 200 ben sotto il prezzo
    attuale, trend di lungo periodo ancora intatto) poi una correzione
    netta di 16 giorni (RSI basso): soddisfa RSI<40, prezzo>SMA200 e volume
    relativo — non la SMA50 crescente, che una correzione di questa
    entità trascina giù con sé (coerente con l'averla resa un indicatore
    di contesto, non un requisito). 3 punti su 4, già fascia alta."""
    monkeypatch.setattr(config, "AI_TRADER_SMA_RISING_LOOKBACK_DAYS", 5)
    closes = [100.0]
    for _ in range(199):
        closes.append(round(closes[-1] * 1.0015, 4))
    decline = [-1.0, -1.2, -0.8, -1.0, -0.9, -1.1, -0.7, -1.0, -0.8, -0.9,
               -0.6, -0.8, -0.5, -0.6, -0.4, -0.5]
    for pct in decline:
        closes.append(round(closes[-1] * (1 + pct / 100), 4))
    volumes = [1_000_000] * (len(closes) - 1) + [1_500_000]
    bars = _bars_from_closes(closes, volumes=volumes)

    assert benchmark._meanrev_technical_score(bars) == 3
    assert benchmark._meanrev_tier(3) == 2


def test_momentum_la_fascia_tecnica_ha_precedenza_sul_rendimento_puro(tmp_path, monkeypatch):
    """Prova end-to-end della richiesta dell'utente: A ha il rendimento PIÙ
    BASSO dei tre (+5%, contro +10% di B e +8% di C) ma soddisfa tutti i
    criteri tecnici (punteggio patchato a 5, fascia alta) — deve passare
    avanti a C (miglior rendimento di A, ma 0 punti tecnici) e restare
    selezionato insieme a B nonostante top_n=2. Il punteggio tecnico reale
    è testato a parte sopra: qui si verifica solo che _update_strategy lo
    usi correttamente per riordinare, non lo ricalcola."""
    _isolate(tmp_path, monkeypatch)
    # Lookback=2 (da _isolate): rendimento = closes[-1]/closes[-3] - 1.
    closes_by_symbol = {
        "AAA": [100.0, 100.0, 105.0],  # +5%, il peggiore per rendimento
        "BBB": [100.0, 100.0, 110.0],  # +10%, il migliore
        "CCC": [100.0, 100.0, 108.0],  # +8%, secondo per rendimento
    }
    scores = {"AAA": 5, "BBB": 0, "CCC": 0}

    def fake_score(bars):
        # bars[0]["close"] (sempre 100.0 qui) non distingue i simboli:
        # si risale al simbolo dal valore dell'ultima chiusura, univoco
        # per ciascuno in questo fixture (105/110/108).
        last = bars[-1]["close"]
        symbol = {105.0: "AAA", 110.0: "BBB", 108.0: "CCC"}[last]
        return scores[symbol]

    with patch("src.benchmark.prices.fetch_daily_history", side_effect=_momentum_fake_fetch(closes_by_symbol)), \
         patch("src.benchmark._momentum_technical_score", side_effect=fake_score):
        benchmark.update_momentum(dt.date(2026, 10, 31), _EXPERIMENT)

    rec = storage.read_all(config.AI_TRADER_MOMENTUM_FILE)[0]
    # A (peggior rendimento, punteggio pieno) e B (miglior rendimento,
    # punteggio zero come C) selezionati; C (secondo per rendimento, ma
    # stessa fascia bassa di B e rendimento peggiore di B) escluso.
    assert set(rec["holdings"]) == {"AAA", "BBB"}


def test_meanrev_la_fascia_tecnica_ha_precedenza_sul_rendimento_puro(tmp_path, monkeypatch):
    """Specchio del test sopra per Mean Reversion: A è sceso MENO degli
    altri due (-5%, contro -10% di B e -8% di C) ma ha punteggio tecnico
    pieno — deve passare avanti a C."""
    _isolate(tmp_path, monkeypatch)
    closes_by_symbol = {
        "AAA": [100.0, 100.0, 95.0],   # -5%, il meno sceso
        "BBB": [100.0, 100.0, 90.0],   # -10%, il più sceso
        "CCC": [100.0, 100.0, 92.0],   # -8%
    }
    scores = {"AAA": 4, "BBB": 0, "CCC": 0}

    def fake_score(bars):
        last = bars[-1]["close"]
        symbol = {95.0: "AAA", 90.0: "BBB", 92.0: "CCC"}[last]
        return scores[symbol]

    with patch("src.benchmark.prices.fetch_daily_history", side_effect=_momentum_fake_fetch(closes_by_symbol)), \
         patch("src.benchmark._meanrev_technical_score", side_effect=fake_score):
        benchmark.update_mean_reversion(dt.date(2026, 10, 31), _EXPERIMENT)

    rec = storage.read_all(config.AI_TRADER_MEANREV_FILE)[0]
    assert set(rec["holdings"]) == {"AAA", "BBB"}


def test_momentum_punteggio_zero_non_svuota_mai_la_selezione(tmp_path, monkeypatch):
    """Nessun criterio tecnico soddisfatto da nessuno dei candidati (storico
    troppo corto per calcolarli) non deve mai ridurre la selezione rispetto
    a prima di questa funzionalità: con un buon rendimento si entra
    comunque, fascia bassa per tutti o no."""
    _isolate(tmp_path, monkeypatch)
    closes_by_symbol = {
        "AAA": [100.0, 100.0, 110.0],
        "BBB": [100.0, 100.0, 90.0],  # negativo, escluso da Momentum
        "CCC": [100.0, 100.0, 105.0],
    }
    with patch("src.benchmark.prices.fetch_daily_history", side_effect=_momentum_fake_fetch(closes_by_symbol)):
        benchmark.update_momentum(dt.date(2026, 10, 31), _EXPERIMENT)

    rec = storage.read_all(config.AI_TRADER_MOMENTUM_FILE)[0]
    assert set(rec["holdings"]) == {"AAA", "CCC"}


def _stop_tp_record(filepath):
    storage.append_record(filepath, {
        "date": "2026-10-31", "equity_usd": 100000.0,
        "holdings": {"AAA": 0.35}, "entry_prices": {"AAA": 100.0},
        "mark_prices": {"AAA": 100.0}, "exit_prices": {},
    })


def _bars_hl(closes, highs, lows):
    end = dt.date(2026, 10, 30)
    return [
        {"date": (end - dt.timedelta(days=len(closes) - 1 - i)).isoformat(), "close": c, "high": h, "low": l}
        for i, (c, h, l) in enumerate(zip(closes, highs, lows))
    ]


def _run_momentum_with(bars_by_symbol):
    def fake(symbol, range_="1y"):
        return bars_by_symbol[symbol]
    with patch("src.benchmark.prices.fetch_daily_history", side_effect=fake):
        benchmark.update_momentum(dt.date(2026, 11, 1), _EXPERIMENT)


def test_stop_loss_intraday_esce_al_livello_e_non_rientra(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    _stop_tp_record(config.AI_TRADER_MOMENTUM_FILE)
    # Il minimo di oggi tocca -9% (sotto lo stop -8%) ma chiude a +2%: esce a 92.
    _run_momentum_with({
        "AAA": _bars_hl([100.0, 100.0, 102.0], [100.0, 100.0, 103.0], [100.0, 100.0, 91.0]),
        "BBB": _bars_hl([100.0, 100.0, 101.0], [100.0] * 3, [100.0] * 3),
        "CCC": _bars_hl([100.0, 100.0, 100.5], [100.0] * 3, [100.0] * 3),
    })
    rec = storage.read_all(config.AI_TRADER_MOMENTUM_FILE)[1]
    assert rec["exit_prices"] == {"AAA": 92.0}
    assert "AAA" not in rec["holdings"]  # niente rientro lo stesso giorno
    assert rec["equity_usd"] == round(100000 * (1 + 0.35 * (92 / 100 - 1)), 2)


def test_take_profit_intraday_esce_al_livello(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    _stop_tp_record(config.AI_TRADER_MOMENTUM_FILE)
    _run_momentum_with({
        "AAA": _bars_hl([100.0, 100.0, 110.0], [100.0, 100.0, 120.0], [100.0, 100.0, 99.0]),
        "BBB": _bars_hl([100.0, 100.0, 101.0], [100.0] * 3, [100.0] * 3),
        "CCC": _bars_hl([100.0, 100.0, 100.5], [100.0] * 3, [100.0] * 3),
    })
    rec = storage.read_all(config.AI_TRADER_MOMENTUM_FILE)[1]
    assert rec["exit_prices"] == {"AAA": 116.0}
    assert rec["equity_usd"] == round(100000 * (1 + 0.35 * 0.16), 2)


def test_stop_e_take_profit_lo_stesso_giorno_vale_lo_stop(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    _stop_tp_record(config.AI_TRADER_MOMENTUM_FILE)
    _run_momentum_with({
        "AAA": _bars_hl([100.0, 100.0, 105.0], [100.0, 100.0, 120.0], [100.0, 100.0, 90.0]),
        "BBB": _bars_hl([100.0, 100.0, 101.0], [100.0] * 3, [100.0] * 3),
        "CCC": _bars_hl([100.0, 100.0, 100.5], [100.0] * 3, [100.0] * 3),
    })
    rec = storage.read_all(config.AI_TRADER_MOMENTUM_FILE)[1]
    assert rec["exit_prices"] == {"AAA": 92.0}


def test_stop_loss_vale_anche_per_mean_reversion(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    _stop_tp_record(config.AI_TRADER_MEANREV_FILE)
    def fake(symbol, range_="1y"):
        return {
            "AAA": _bars_hl([100.0, 100.0, 95.0], [100.0, 100.0, 100.0], [100.0, 100.0, 90.0]),
            "BBB": _bars_hl([100.0, 100.0, 97.0], [100.0] * 3, [100.0] * 3),
            "CCC": _bars_hl([100.0, 100.0, 98.0], [100.0] * 3, [100.0] * 3),
        }[symbol]
    with patch("src.benchmark.prices.fetch_daily_history", side_effect=fake):
        benchmark.update_mean_reversion(dt.date(2026, 11, 1), _EXPERIMENT)
    rec = storage.read_all(config.AI_TRADER_MEANREV_FILE)[1]
    assert rec["exit_prices"] == {"AAA": 92.0}
    assert "AAA" not in rec["holdings"]


def test_dati_vecchi_non_scrivono_il_giorno(tmp_path, monkeypatch):
    """Se l'ultima barra è precedente all'ultima seduta attesa per quasi
    tutti i titoli, il giorno non viene registrato (niente rendimento zero
    con prezzi vecchi) e lo stato di salute segnala il problema."""
    _isolate(tmp_path, monkeypatch)
    _stop_tp_record(config.AI_TRADER_MOMENTUM_FILE)
    old = {
        "AAA": [{"date": "2026-10-28", "close": 100.0}, {"date": "2026-10-29", "close": 101.0}],
    }
    def fake(symbol, range_="1y"):
        return old["AAA"]
    with patch("src.benchmark.prices.fetch_daily_history", side_effect=fake):
        benchmark.update_momentum(dt.date(2026, 11, 2), _EXPERIMENT)
    assert len(storage.read_all(config.AI_TRADER_MOMENTUM_FILE)) == 1  # nessun nuovo record


def test_ultima_seduta_attesa_salta_weekend_e_festivi():
    assert benchmark._expected_last_session(dt.date(2026, 11, 2)) == "2026-10-30"  # lunedì -> venerdì
    assert benchmark._expected_last_session(dt.date(2026, 11, 4)) == "2026-11-03"
