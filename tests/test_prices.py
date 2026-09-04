"""Test unitari per src/data_sources/prices.py: fetch_daily_history() deve
davvero passare il range_ richiesto alle fonti sottostanti, non ignorarlo.

Regressione reale trovata in revisione del codice il 2026-09-04:
fetch_daily_history(ticker, range_="2y") accettava range_ ma non lo
inoltrava mai a _yahoo_daily_history()/_twelvedata_daily_history() — ogni
chiamante otteneva sempre ~1 anno di storico (il default), a prescindere
da cosa avesse richiesto."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.data_sources import prices


def _yahoo_response(dates_closes: list[tuple[str, float]]):
    import datetime as dt

    timestamps = [
        int(dt.datetime.fromisoformat(d).replace(tzinfo=dt.timezone.utc).timestamp())
        for d, _ in dates_closes
    ]
    closes = [c for _, c in dates_closes]
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(
        return_value={
            "chart": {
                "result": [
                    {
                        "timestamp": timestamps,
                        "indicators": {
                            "quote": [
                                {
                                    "close": closes,
                                    "volume": [None] * len(closes),
                                    "high": [None] * len(closes),
                                    "low": [None] * len(closes),
                                }
                            ]
                        },
                    }
                ]
            }
        }
    )
    return resp


def test_fetch_daily_history_passa_il_range_richiesto_a_yahoo():
    with patch(
        "src.data_sources.prices.http.get",
        return_value=_yahoo_response([("2026-09-01", 100.0)]),
    ) as mock_get:
        prices.fetch_daily_history("NVDA", range_="2y")

    called_params = mock_get.call_args.kwargs["params"]
    assert called_params["range"] == "2y"


def test_fetch_daily_history_default_e_1y():
    with patch(
        "src.data_sources.prices.http.get",
        return_value=_yahoo_response([("2026-09-01", 100.0)]),
    ) as mock_get:
        prices.fetch_daily_history("NVDA")

    assert mock_get.call_args.kwargs["params"]["range"] == "1y"


def test_fetch_daily_history_range_2y_si_traduce_in_outputsize_maggiore_per_twelvedata():
    with patch("src.data_sources.prices._yahoo_daily_history", side_effect=Exception("yahoo giù")), patch(
        "src.data_sources.prices.os.environ.get", return_value="fake-key"
    ), patch("src.data_sources.prices.http.get") as mock_get:
        mock_get.return_value.raise_for_status = MagicMock()
        mock_get.return_value.json = MagicMock(
            return_value={"values": [{"datetime": "2026-09-01", "close": "100.0"}]}
        )
        prices.fetch_daily_history("NVDA", range_="2y")

    assert mock_get.call_args.kwargs["params"]["outputsize"] == 520
