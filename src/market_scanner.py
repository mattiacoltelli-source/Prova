"""Scanner di mercato: segnali quantitativi su una watchlist più ampia.

Modulo indipendente dal motore predittivo (nessuna previsione, nessuna
chiamata AI, nessuna dipendenza da ASSETS/ROBOTICS_ASSETS): scorre
config.SCANNER_STOCKS + config.SCANNER_CRYPTO e calcola 3 segnali
puramente quantitativi — volume anomalo, gap in apertura, vicinanza al
massimo di un mese — per far emergere a colpo d'occhio i titoli con
movimento fuori norma.

Fonte dati: Yahoo Finance (stessa fonte primaria di
src/data_sources/prices.py), unica fonte gratuita verificata con
copertura sia USA sia Tokyo sia crypto in una sola chiamata per simbolo
(meta + storico 1 mese, da cui si calcolano media volume e massimo
recente senza una seconda richiesta).
"""
from __future__ import annotations

import datetime as dt
import statistics

from . import config
from .data_sources import http

YAHOO_UA = {"User-Agent": "Mozilla/5.0 (predictive-agent research script)"}
TIMEOUT = 15


class ScannerError(RuntimeError):
    pass


def fetch_symbol(symbol: str, lookback_days: int = config.SCANNER_LOOKBACK_DAYS) -> dict:
    """Un solo simbolo: prezzo/volume odierno + storico di un mese, da cui
    si ricavano i segnali. Solleva ScannerError se il simbolo non ha dati
    sufficienti — mai silenzioso: chi chiama (scan()) decide se saltarlo."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    resp = http.get(
        url, params={"range": "1mo", "interval": "1d"}, headers=YAHOO_UA, timeout=TIMEOUT
    )
    resp.raise_for_status()
    results = resp.json().get("chart", {}).get("result")
    if not results:
        raise ScannerError(f"Nessun dato Yahoo per {symbol}")
    result = results[0]
    meta = result.get("meta", {})
    quote = result.get("indicators", {}).get("quote", [{}])[0]

    opens = quote.get("open") or []
    highs = quote.get("high") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []
    if not opens or not highs or not closes or not volumes:
        raise ScannerError(f"Storico mancante per {symbol}")
    if len(closes) < 2:
        raise ScannerError(f"Storico troppo corto per {symbol}")

    # L'ultima barra è la giornata odierna (anche a mercato aperto, quindi
    # parziale): esclusa da media volume e massimo storico, altrimenti si
    # confronterebbe il volume di oggi con una media che include se stesso.
    past_volumes = [v for v in volumes[:-1] if v is not None][-lookback_days:]
    past_highs = [h for h in highs[:-1] if h is not None][-lookback_days:]
    if not past_volumes or not past_highs:
        raise ScannerError(f"Storico insufficiente per {symbol}")

    price = meta.get("regularMarketPrice")
    # NON meta.chartPreviousClose: con range="1mo" (serve qui per lo storico
    # di un mese) quel campo torna la chiusura di PRIMA dell'inizio del
    # grafico (~1 mese fa), non quella di ieri — verificato dal vivo su
    # RIVN: chartPreviousClose=14.97 contro closes[-2]=11.45 (la vera
    # chiusura di ieri). Con range="1d" invece chartPreviousClose è giusto:
    # il valore dipende dal range richiesto, non è un bug isolato di un
    # titolo. closes[-2] è la seconda barra dalla fine nello stesso array
    # già usato sopra, sempre coerente con qualunque range.
    previous_close = closes[-2]
    today_open = opens[-1]
    today_volume = meta.get("regularMarketVolume")
    if price is None or previous_close is None or today_volume is None:
        raise ScannerError(f"Campi essenziali mancanti per {symbol}")

    avg_volume = statistics.mean(past_volumes)
    recent_high = max(past_highs)

    gap_pct = (today_open - previous_close) / previous_close * 100 if today_open else None
    volume_ratio = today_volume / avg_volume if avg_volume else None
    breakout_pct = (price - recent_high) / recent_high * 100 if recent_high else None
    change_pct = meta.get("regularMarketChangePercent")

    return {
        "symbol": symbol,
        "name": meta.get("shortName") or meta.get("longName") or symbol,
        # THK/Harmonic Drive (6481.T/6324.T) quotano in yen, non in dollari:
        # il frontend sceglie il simbolo giusto da qui invece di assumere
        # sempre "$" (lo fa già altrove nel sito, ma lì ogni asset è sempre
        # in USD — qui la watchlist mescola valute).
        "currency": meta.get("currency") or "USD",
        "price": round(price, 4),
        "change_pct": round(change_pct, 2) if change_pct is not None else None,
        "volume": int(today_volume),
        "average_volume": round(avg_volume),
        "volume_ratio": round(volume_ratio, 2) if volume_ratio is not None else None,
        "gap_pct": round(gap_pct, 2) if gap_pct is not None else None,
        "recent_high": round(recent_high, 4),
        "breakout_pct": round(breakout_pct, 2) if breakout_pct is not None else None,
    }


def is_flagged(row: dict) -> bool:
    """Un titolo è "flagged" se almeno uno dei 3 segnali supera la soglia
    configurata — non un voto, solo per ordinare i risultati più
    interessanti in cima (vedi scan())."""
    volume_ratio = row.get("volume_ratio")
    gap_pct = row.get("gap_pct")
    breakout_pct = row.get("breakout_pct")
    if volume_ratio is not None and volume_ratio >= config.SCANNER_VOLUME_RATIO_FLAG:
        return True
    if gap_pct is not None and abs(gap_pct) >= config.SCANNER_GAP_PCT_FLAG:
        return True
    if breakout_pct is not None and breakout_pct >= config.SCANNER_BREAKOUT_PCT_FLAG:
        return True
    return False


def scan(symbols: list[str]) -> dict:
    """Scansiona tutti i simboli passati. Un simbolo che fallisce (dati
    mancanti, errore di rete, ticker illiquido) non interrompe gli altri —
    finisce nella lista separata "errors", mai fatale per l'intero run: con
    50+ simboli da una fonte gratuita un fallimento isolato è normale, farlo
    fallire tutto per un ticker sarebbe peggio che perderne uno."""
    good_rows: list[dict] = []
    errors: list[dict] = []
    for symbol in symbols:
        try:
            row = fetch_symbol(symbol)
            row["flagged"] = is_flagged(row)
            good_rows.append(row)
        except Exception as exc:  # noqa: BLE001 - un simbolo per volta, mai fatale
            errors.append({"symbol": symbol, "error": str(exc)})
    good_rows.sort(key=lambda r: (not r["flagged"], -(r.get("volume_ratio") or 0)))
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        # Esposte nel JSON così il frontend può spiegare le soglie nel testo
        # (scannerDetailRow() in index.html) leggendole da qui invece di
        # duplicarle a mano in un secondo punto — già cambiate una volta in
        # config.py, un valore scritto due volte sarebbe già disallineato.
        "thresholds": {
            "volume_ratio": config.SCANNER_VOLUME_RATIO_FLAG,
            "gap_pct": config.SCANNER_GAP_PCT_FLAG,
            "breakout_pct": config.SCANNER_BREAKOUT_PCT_FLAG,
        },
        "results": good_rows,
        "errors": errors,
    }


def all_symbols() -> list[str]:
    return [*config.SCANNER_STOCKS, *config.SCANNER_CRYPTO]
