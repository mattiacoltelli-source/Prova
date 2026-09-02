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


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _ema_series(values: list[float], period: int) -> list[float] | None:
    """Serie di EMA su `values`: il primo valore è seminato con la SMA
    delle prime `period` osservazioni (pratica standard), poi ricorsivo con
    fattore di smoothing k = 2/(period+1). None se non ci sono abbastanza
    dati per seminare la serie."""
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    ema = [sum(values[:period]) / period]
    for v in values[period:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def compute_sma_trend(bars: list[DailyBar], short_period: int = 50, long_period: int = 200) -> str | None:
    """Regime di trend di fondo: SMA breve sopra la SMA lunga = rialzista
    (classico "golden cross"), sotto = ribassista. None se lo storico non
    copre ancora `long_period` barre."""
    closes = [b["close"] for b in bars]
    sma_short = _sma(closes, short_period)
    sma_long = _sma(closes, long_period)
    if sma_short is None or sma_long is None:
        return None
    if sma_short > sma_long:
        return "rialzista"
    if sma_short < sma_long:
        return "ribassista"
    return "neutro"


def compute_ema_trend(bars: list[DailyBar], short_period: int = 9, long_period: int = 21) -> str | None:
    """Come compute_sma_trend ma con medie esponenziali più reattive: utile
    come segnale di trend di brevissimo termine (orizzonti 1g/7g), mentre
    compute_sma_trend copre il trend di fondo (orizzonte 1m)."""
    closes = [b["close"] for b in bars]
    ema_short = _ema_series(closes, short_period)
    ema_long = _ema_series(closes, long_period)
    if ema_short is None or ema_long is None:
        return None
    if ema_short[-1] > ema_long[-1]:
        return "rialzista"
    if ema_short[-1] < ema_long[-1]:
        return "ribassista"
    return "neutro"


def compute_rsi(bars: list[DailyBar], period: int = 14) -> float | None:
    """Relative Strength Index (media semplice di guadagni/perdite, non
    smoothing di Wilder - stessa scelta "semplice e verificabile a mano"
    già fatta per CMF/OBV). Valore 0-100, >70 tipicamente ipercomprato,
    <30 ipervenduto. None se lo storico è insufficiente."""
    closes = [b["close"] for b in bars]
    if len(closes) < period + 1:
        return None
    diffs = [closes[i] - closes[i - 1] for i in range(1, len(closes))][-period:]
    gains = [d for d in diffs if d > 0]
    losses = [-d for d in diffs if d < 0]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 2)


def compute_macd(
    bars: list[DailyBar], fast_period: int = 12, slow_period: int = 26, signal_period: int = 9
) -> dict | None:
    """MACD standard: linea MACD (EMA veloce - EMA lenta), linea segnale
    (EMA della linea MACD) e istogramma (MACD - segnale). Istogramma > 0
    indica momentum rialzista in accelerazione. None se lo storico non
    copre ancora slow_period + signal_period - 1 barre."""
    closes = [b["close"] for b in bars]
    ema_fast = _ema_series(closes, fast_period)
    ema_slow = _ema_series(closes, slow_period)
    if ema_fast is None or ema_slow is None:
        return None
    offset = slow_period - fast_period
    macd_line = [f - s for f, s in zip(ema_fast[offset:], ema_slow)]
    signal_series = _ema_series(macd_line, signal_period)
    if signal_series is None:
        return None
    macd_value = macd_line[-1]
    signal_value = signal_series[-1]
    return {
        "macd": round(macd_value, 4),
        "signal": round(signal_value, 4),
        "histogram": round(macd_value - signal_value, 4),
    }


def compute_atr_pct(bars: list[DailyBar], period: int = 14) -> float | None:
    """Average True Range espresso in % dell'ultima chiusura (comparabile
    tra asset con prezzi molto diversi, come le altre metriche % di questo
    modulo). None se high/low mancano o lo storico è insufficiente."""
    window = bars[-(period + 1) :]
    if len(window) < period + 1 or any(k not in b for b in window for k in ("high", "low")):
        return None
    true_ranges = []
    for i in range(1, len(window)):
        prev_close = window[i - 1]["close"]
        high, low = window[i]["high"], window[i]["low"]
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    atr = sum(true_ranges) / period
    last_close = window[-1]["close"]
    if last_close == 0:
        return None
    return round(atr / last_close * 100, 2)


def compute_beta(
    asset_bars: list[DailyBar], benchmark_bars: list[DailyBar], lookback: int = 60
) -> float | None:
    """Beta vs benchmark (S&P 500): sensibilità dei rendimenti giornalieri
    dell'asset a quelli del benchmark sulle ultime `lookback` barre.
    >1 = più volatile del mercato, <1 = meno volatile, ~1 = in linea.
    None se lo storico è insufficiente o il benchmark non si muove mai."""
    if len(asset_bars) < lookback + 1 or len(benchmark_bars) < lookback + 1:
        return None
    asset_closes = [b["close"] for b in asset_bars[-(lookback + 1) :]]
    bench_closes = [b["close"] for b in benchmark_bars[-(lookback + 1) :]]
    asset_returns = [
        (asset_closes[i] - asset_closes[i - 1]) / asset_closes[i - 1]
        for i in range(1, len(asset_closes))
        if asset_closes[i - 1] != 0
    ]
    bench_returns = [
        (bench_closes[i] - bench_closes[i - 1]) / bench_closes[i - 1]
        for i in range(1, len(bench_closes))
        if bench_closes[i - 1] != 0
    ]
    if len(asset_returns) != lookback or len(bench_returns) != lookback:
        return None
    mean_a = sum(asset_returns) / lookback
    mean_b = sum(bench_returns) / lookback
    covariance = sum((a - mean_a) * (b - mean_b) for a, b in zip(asset_returns, bench_returns)) / lookback
    variance_b = sum((b - mean_b) ** 2 for b in bench_returns) / lookback
    if variance_b == 0:
        return None
    return round(covariance / variance_b, 2)
