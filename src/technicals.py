"""Indicatori tecnici aggiuntivi calcolati da OHLCV gratuito (Yahoo/Twelve
Data): nessuna fonte a pagamento, nessuna key extra rispetto a quelle già
usate per lo storico prezzo."""
from __future__ import annotations

from .data_sources.prices import DailyBar


def compute_obv_trend(bars: list[DailyBar], lookback: int = 10) -> str | None:
    """On-Balance Volume: cumulativo +volume nei giorni di rialzo, -volume
    in quelli di ribasso. Ritorna il trend (accumulazione/distribuzione/
    neutro) confrontando l'OBV attuale con quello di `lookback` barre fa,
    invece del valore assoluto (non direttamente interpretabile da solo).
    None se il volume non è disponibile dalla fonte usata."""
    if len(bars) < lookback + 1 or any("volume" not in b for b in bars[-(lookback + 1) :]):
        return None
    obv = [0.0]
    for i in range(1, len(bars)):
        if "volume" not in bars[i]:
            obv.append(obv[-1])
            continue
        if bars[i]["close"] > bars[i - 1]["close"]:
            obv.append(obv[-1] + bars[i]["volume"])
        elif bars[i]["close"] < bars[i - 1]["close"]:
            obv.append(obv[-1] - bars[i]["volume"])
        else:
            obv.append(obv[-1])

    window = obv[-(lookback + 1) :]
    delta = window[-1] - window[0]
    threshold = 0.02 * max(abs(v) for v in window) if any(window) else 0
    if delta > threshold:
        return "accumulazione"
    if delta < -threshold:
        return "distribuzione"
    return "neutro"


def compute_cmf(bars: list[DailyBar], period: int = 20) -> float | None:
    """Chaikin Money Flow sulle ultime `period` barre: valore tra -1 e +1,
    positivo indica pressione in acquisto, negativo in vendita. None se
    high/low/volume non sono disponibili dalla fonte usata."""
    window = bars[-period:]
    if len(window) < period or any(k not in b for b in window for k in ("high", "low", "volume")):
        return None
    mfv_sum = 0.0
    vol_sum = 0.0
    for b in window:
        hl_range = b["high"] - b["low"]
        if hl_range == 0:
            continue
        mfm = ((b["close"] - b["low"]) - (b["high"] - b["close"])) / hl_range
        mfv_sum += mfm * b["volume"]
        vol_sum += b["volume"]
    if vol_sum == 0:
        return None
    return round(mfv_sum / vol_sum, 4)


def compute_relative_strength_pct(
    asset_bars: list[DailyBar], benchmark_bars: list[DailyBar], lookback: int = 60
) -> float | None:
    """Rendimento % dell'asset meno quello del benchmark (S&P 500) sullo
    stesso periodo: positivo = l'asset sta sovraperformando il mercato
    (Mansfield Relative Strength semplificata)."""
    if len(asset_bars) < lookback + 1 or len(benchmark_bars) < lookback + 1:
        return None
    a0, a1 = asset_bars[-1 - lookback]["close"], asset_bars[-1]["close"]
    b0, b1 = benchmark_bars[-1 - lookback]["close"], benchmark_bars[-1]["close"]
    if a0 == 0 or b0 == 0:
        return None
    asset_ret = (a1 - a0) / a0 * 100
    bench_ret = (b1 - b0) / b0 * 100
    return round(asset_ret - bench_ret, 2)
