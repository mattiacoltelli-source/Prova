"""GET condiviso con un singolo retry silenzioso sui soli errori di rete
(la richiesta non è nemmeno arrivata a destinazione — DNS, timeout,
connessione rifiutata), mai su una risposta HTTP vera (quella resta un
esito definitivo, gestito da chi chiama con .raise_for_status() o
controllando lo status code). Stesso principio già usato in
qa-agent/api-doctor/lib/http.mjs: un blip di rete isolato non deve
bastare a far scartare una fonte e passare subito al fallback
successivo."""
from __future__ import annotations

import requests

NETWORK_ERROR_MAX_RETRIES = 1


def get(url: str, **kwargs) -> requests.Response:
    last_exc: requests.exceptions.RequestException | None = None
    for _ in range(NETWORK_ERROR_MAX_RETRIES + 1):
        try:
            return requests.get(url, **kwargs)
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            continue
    raise last_exc
