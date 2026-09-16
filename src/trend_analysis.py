"""Metriche quantitative per l'analisi di trend di lungo periodo (asset
"robotica", config.ROBOTICS_ASSETS): CAGR multi-orizzonte, drawdown, fase
del ciclo rispetto alla media mobile lunga. Analogo di technicals.py ma per
orizzonti in anni invece che in giorni — nessuna fonte dati nuova, stesso
storico daily di prices.fetch_daily_history() già usato dal sistema
esistente.

Le soglie di classificazione (TREND_MA_WEEKS=200, bande ESTESA/COMPRESSA)
derivano dall'analisi storica 2026-09-17 su ABB/THK/Harmonic Drive (vedi
config.py): il paniere mostra cicli boom-bust di ~3-4 anni con drawdown
50-80% dai picchi, non una crescita lineare — da qui la scelta di misurare
la POSIZIONE nel ciclo (prezzo vs MA200w) invece di affidarsi solo al CAGR,
che da solo confonderebbe "in trend rialzista" con "già molto esteso e a
rischio di mean-reversion"."""
from __future__ import annotations

import datetime as dt

from .data_sources.prices import DailyBar


def compute_cagr(bars: list[DailyBar], years: int) -> float | None:
    """CAGR sulla finestra dei `years` più recenti. None se lo storico
    disponibile copre meno dell'85% della finestra richiesta (evita di
    riportare un "CAGR 10 anni" calcolato su 3 anni di dati reali per un
    IPO recente o una fonte con storico incompleto)."""
    if len(bars) < 20:
        return None
    end_date = dt.date.fromisoformat(bars[-1]["date"])
    start_cutoff = end_date - dt.timedelta(days=int(years * 365.25))
    window = [b for b in bars if dt.date.fromisoformat(b["date"]) >= start_cutoff]
    if len(window) < 20:
        return None
    actual_years = (
        dt.date.fromisoformat(window[-1]["date"]) - dt.date.fromisoformat(window[0]["date"])
    ).days / 365.25
    if actual_years < years * 0.85:
        return None
    start_price, end_price = window[0]["close"], window[-1]["close"]
    if start_price <= 0:
        return None
    return round((end_price / start_price) ** (1 / actual_years) - 1, 4)


def compute_max_drawdown(bars: list[DailyBar]) -> float | None:
    """Massimo ribasso percentuale da un picco precedente sull'intero
    storico disponibile. Negativo (es. -0.45 = -45%)."""
    if len(bars) < 2:
        return None
    peak = bars[0]["close"]
    max_dd = 0.0
    for b in bars:
        peak = max(peak, b["close"])
        if peak > 0:
            dd = (b["close"] - peak) / peak
            max_dd = min(max_dd, dd)
    return round(max_dd, 4)


def compute_annualized_volatility(bars: list[DailyBar]) -> float | None:
    """Deviazione standard dei rendimenti giornalieri, annualizzata
    (sqrt(252), giorni di trading/anno). None se lo storico è troppo
    corto per una stima sensata."""
    closes = [b["close"] for b in bars]
    if len(closes) < 30:
        return None
    rets = [
        (closes[i] - closes[i - 1]) / closes[i - 1]
        for i in range(1, len(closes))
        if closes[i - 1] != 0
    ]
    if len(rets) < 29:
        return None
    mean = sum(rets) / len(rets)
    variance = sum((r - mean) ** 2 for r in rets) / len(rets)
    return round((variance**0.5) * (252**0.5), 4)


def _weekly_closes(bars: list[DailyBar]) -> list[tuple[dt.date, float]]:
    """Riduce le barre daily a un punto per settimana solare (ultima
    chiusura della settimana), stesso approccio usato nell'analisi
    esplorativa: riduce il rumore prima di calcolare una media mobile
    pensata per un orizzonte di anni, non di giorni."""
    by_week: dict[tuple[int, int], tuple[dt.date, float]] = {}
    for b in bars:
        d = dt.date.fromisoformat(b["date"])
        key = d.isocalendar()[:2]  # (anno ISO, settimana ISO)
        by_week[key] = (d, b["close"])  # sovrascrive: resta l'ultima della settimana
    return sorted(by_week.values(), key=lambda t: t[0])


def compute_price_vs_long_ma_pct(bars: list[DailyBar], weeks: int) -> float | None:
    """Prezzo attuale vs media mobile a `weeks` settimane, in %: positivo =
    sopra la media di lungo periodo (fase estesa/rialzista), negativo =
    sotto (fase compressa/ribassista). None se lo storico settimanale non
    copre almeno metà della finestra richiesta."""
    weekly = _weekly_closes(bars)
    if len(weekly) < weeks // 2:
        return None
    window = weekly[-weeks:]
    ma = sum(c for _, c in window) / len(window)
    if ma == 0:
        return None
    last_price = weekly[-1][1]
    return round((last_price / ma - 1) * 100, 2)


def classify_cycle_phase(price_vs_ma_pct: float | None) -> str:
    """Fasi tarate sull'analisi storica 2026-09-17: ABB/THK/Harmonic Drive
    a inizio settembre 2026 erano tutte +49/+62% sopra la propria MA200w,
    livello dopo il quale storicamente sono seguiti drawdown del 45-80%.
    Bande scelte per distinguere questo caso da un trend "sano" (poche
    decine di punti sopra la media) da uno chiaramente ipercomprato."""
    if price_vs_ma_pct is None:
        return "sconosciuta"
    if price_vs_ma_pct >= 40:
        return "molto_estesa"
    if price_vs_ma_pct >= 15:
        return "estesa"
    if price_vs_ma_pct > -15:
        return "neutrale"
    if price_vs_ma_pct > -40:
        return "compressa"
    return "molto_compressa"


def compute_annual_returns(bars: list[DailyBar], last_n_years: int = 10) -> dict[str, float]:
    """Rendimento per anno solare (ultima chiusura vs ultima chiusura
    dell'anno precedente), sugli ultimi `last_n_years` anni solari con dati
    completi. Mostra la "forma" del ciclo (boom-bust) che il solo CAGR
    aggregato nasconde."""
    weekly = _weekly_closes(bars)
    if len(weekly) < 30:
        return {}
    by_year_last: dict[int, float] = {}
    for d, close in weekly:
        by_year_last[d.year] = close  # sovrascrive: resta l'ultimo prezzo dell'anno
    years_sorted = sorted(by_year_last.keys())[-(last_n_years + 1) :]
    out: dict[str, float] = {}
    for prev_y, y in zip(years_sorted, years_sorted[1:]):
        prev_close = by_year_last[prev_y]
        if prev_close == 0:
            continue
        out[str(y)] = round((by_year_last[y] / prev_close - 1) * 100, 2)
    return out


def compute_annual_return_correlation(asset_bars: list[DailyBar], benchmark_bars: list[DailyBar]) -> float | None:
    """Correlazione tra i rendimenti per anno solare dell'asset e del
    benchmark (es. ^SOX) sugli anni in comune. Usata per verificare/
    aggiornare nel tempo l'assunzione (fissata nell'analisi storica
    2026-09-17) che il ciclo semiconduttori sia il driver macro dominante
    di questo paniere. None se meno di 4 anni sono in comune (correlazione
    poco significativa sotto quella soglia)."""
    asset_returns = compute_annual_returns(asset_bars)
    bench_returns = compute_annual_returns(benchmark_bars)
    common_years = sorted(set(asset_returns) & set(bench_returns))
    if len(common_years) < 4:
        return None
    xs = [asset_returns[y] for y in common_years]
    ys = [bench_returns[y] for y in common_years]
    n = len(xs)
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / n
    var_x = sum((x - mean_x) ** 2 for x in xs) / n
    var_y = sum((y - mean_y) ** 2 for y in ys) / n
    if var_x == 0 or var_y == 0:
        return None
    return round(cov / (var_x**0.5 * var_y**0.5), 3)


def build_trend_metrics(
    bars: list[DailyBar],
    years_list: list[int],
    ma_weeks: int,
) -> dict:
    """Aggrega tutte le metriche quant in un unico dict, pronto per essere
    salvato nel record e passato al prompt del modello."""
    price_vs_ma = compute_price_vs_long_ma_pct(bars, ma_weeks)
    return {
        "last_price": bars[-1]["close"] if bars else None,
        "last_date": bars[-1]["date"] if bars else None,
        "first_date": bars[0]["date"] if bars else None,
        "cagr_by_years": {str(y): compute_cagr(bars, y) for y in years_list},
        "max_drawdown": compute_max_drawdown(bars),
        "annualized_volatility": compute_annualized_volatility(bars),
        "price_vs_ma_pct": price_vs_ma,
        "ma_weeks": ma_weeks,
        "cycle_phase": classify_cycle_phase(price_vs_ma),
        "annual_returns": compute_annual_returns(bars),
    }
