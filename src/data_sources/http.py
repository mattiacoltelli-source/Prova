"""GET condiviso con un singolo retry silenzioso sui soli errori di rete
(la richiesta non è nemmeno arrivata a destinazione — DNS, timeout,
connessione rifiutata), mai su una risposta HTTP vera (quella resta un
esito definitivo, gestito da chi chiama con .raise_for_status() o
controllando lo status code). Stesso principio già usato in
qa-agent/api-doctor/lib/http.mjs: un blip di rete isolato non deve
bastare a far scartare una fonte e passare subito al fallback
successivo.

Eccezione opt-in: `retry_on_rate_limit=True` fa riprovare anche sul 429
(troppe richieste), aspettando prima di ritentare. Non è attivo di
default perché per la maggior parte delle fonti un 429 significa "quota
giornaliera finita" — aspettare qualche secondo non la rimette a posto e
ritarderebbe solo il passaggio al fallback successivo. Serve invece dove
un 429 è tipicamente momentaneo E non c'è un fallback dietro: GDELT
limita per IP, e gli IP dei runner GitHub sono condivisi con mezzo mondo.
"""
from __future__ import annotations

import time

import requests

NETWORK_ERROR_MAX_RETRIES = 1

# Due tentativi in più, distanziati: se dopo ~15 secondi complessivi il
# limite non si è ancora liberato non è un picco di traffico condiviso, ed
# è giusto che chi chiama lo tratti come fonte non disponibile.
RATE_LIMIT_MAX_RETRIES = 2
RATE_LIMIT_WAITS_S = (5, 10)
# Tetto all'attesa dichiarata dal server: un Retry-After di dieci minuti
# non deve bloccare un run che gira su uno slot programmato.
RATE_LIMIT_MAX_WAIT_S = 30


def _rate_limit_wait_seconds(resp: requests.Response, attempt: int) -> float:
    """Quanto aspettare prima del tentativo successivo: la testata
    Retry-After se il server la manda in secondi (è il dato migliore, lo
    conosce solo lui), altrimenti l'attesa fissa crescente."""
    header = resp.headers.get("Retry-After") if getattr(resp, "headers", None) else None
    if header:
        try:
            return min(float(header), RATE_LIMIT_MAX_WAIT_S)
        except (TypeError, ValueError):
            pass  # Retry-After può anche essere una data HTTP: ignorata, si usa il default
    return RATE_LIMIT_WAITS_S[min(attempt, len(RATE_LIMIT_WAITS_S) - 1)]


def get(url: str, retry_on_rate_limit: bool = False, **kwargs) -> requests.Response:
    last_exc: requests.exceptions.RequestException | None = None
    for _ in range(NETWORK_ERROR_MAX_RETRIES + 1):
        try:
            resp = requests.get(url, **kwargs)
        except requests.exceptions.RequestException as exc:
            last_exc = exc
            continue

        if retry_on_rate_limit:
            for attempt in range(RATE_LIMIT_MAX_RETRIES):
                if resp.status_code != 429:
                    break
                time.sleep(_rate_limit_wait_seconds(resp, attempt))
                try:
                    resp = requests.get(url, **kwargs)
                except requests.exceptions.RequestException:
                    # Il 429 di prima resta l'esito più informativo da
                    # restituire: un errore di rete al secondo giro non
                    # aggiunge nulla per chi chiama.
                    break
        return resp
    raise last_exc
