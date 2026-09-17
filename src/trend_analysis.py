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


def build_weekly_series(bars: list[DailyBar], ma_weeks: int) -> list[dict]:
    """Serie settimanale completa (prezzo + media mobile a `ma_weeks`) per
    il grafico "in che fase del ciclo siamo" sulla pagina Robotica — a
    differenza di compute_price_vs_long_ma_pct (che ritorna solo l'ultimo
    punto), qui serve l'intera serie da disegnare. ma è null finché la
    finestra non è piena (prime `ma_weeks` settimane): niente MA calcolata
    su una finestra parziale, che sarebbe fuorviante da leggere su un
    grafico senza un'indicazione esplicita."""
    weekly = _weekly_closes(bars)
    closes = [c for _, c in weekly]
    out: list[dict] = []
    for i, (d, close) in enumerate(weekly):
        window = closes[max(0, i - ma_weeks + 1) : i + 1]
        ma = sum(window) / len(window) if len(window) >= ma_weeks else None
        out.append({"date": d.isoformat(), "close": close, "ma": round(ma, 4) if ma is not None else None})
    return out


def _months_between(d1: dt.date, d2: dt.date) -> float:
    """Mesi (con decimali) tra due date, sempre >= 0 (assume d2 >= d1)."""
    return (d2 - d1).days / 30.44  # 365.25/12, media giorni/mese


def find_extended_episodes(weekly_series: list[dict], threshold_pct: float = 40.0) -> list[dict]:
    """Trova le fasi storiche in cui il titolo era "molto esteso" (prezzo
    sopra la propria media mobile di quanto definito da threshold_pct —
    40%, la stessa soglia di classify_cycle_phase per "molto_estesa", cosi
    le fasi trovate qui sono le stesse che il badge segnala oggi) e misura
    l'esito REALE di ognuna: mesi dall'inizio della fase al picco, ampiezza
    della correzione dal picco, mesi di recupero.

    Puro calcolo su prezzi storici già scaricati — nessuna chiamata AI,
    nessun numero stimato: o l'esito è misurabile dai dati (fase chiusa,
    con un trough e magari un recupero osservati), o l'episodio è escluso
    dal risultato. Una fase ancora in corso (il titolo non è ancora
    ridisceso sotto soglia entro i dati disponibili, es. lo stato attuale)
    non ha un esito da misurare per definizione e viene sempre esclusa —
    non è un limite di questa funzione, è che quell'esito semplicemente
    non è ancora accaduto."""
    n = len(weekly_series)
    episodes: list[dict] = []
    i = 0
    while i < n:
        vs_ma = weekly_series[i]["ma"]
        pct = (weekly_series[i]["close"] / vs_ma - 1) * 100 if vs_ma else None
        if pct is None or pct < threshold_pct:
            i += 1
            continue
        start_idx = i
        while i < n:
            ma = weekly_series[i]["ma"]
            p = (weekly_series[i]["close"] / ma - 1) * 100 if ma else None
            if p is None or p < threshold_pct:
                break
            i += 1
        end_idx = i - 1
        is_ongoing = end_idx == n - 1

        segment = weekly_series[start_idx : end_idx + 1]
        peak_point = max(segment, key=lambda p: p["close"])
        peak_idx = start_idx + segment.index(peak_point)

        episodes.append(
            {
                "start_date": weekly_series[start_idx]["date"],
                "peak_date": peak_point["date"],
                "peak_price": peak_point["close"],
                "peak_idx": peak_idx,
                "is_ongoing": is_ongoing,
            }
        )

    resolved: list[dict] = []
    for ep in episodes:
        if ep["is_ongoing"]:
            continue
        peak_idx = ep["peak_idx"]
        peak_price = ep["peak_price"]
        peak_date = dt.date.fromisoformat(ep["peak_date"])

        trough_price = peak_price
        trough_date = peak_date
        recovered_date: dt.date | None = None
        for j in range(peak_idx + 1, n):
            point = weekly_series[j]
            close_j = point["close"]
            if close_j < trough_price:
                trough_price = close_j
                trough_date = dt.date.fromisoformat(point["date"])
            if close_j >= peak_price:
                recovered_date = dt.date.fromisoformat(point["date"])
                break

        if trough_price >= peak_price:
            continue  # non è mai sceso sotto il picco: nessuna correzione da misurare

        resolved.append(
            {
                "start_date": ep["start_date"],
                "peak_date": ep["peak_date"],
                "trough_date": trough_date.isoformat(),
                "months_to_peak": round(_months_between(dt.date.fromisoformat(ep["start_date"]), peak_date), 1),
                "correction_pct": round((trough_price / peak_price - 1) * 100, 1),
                "recovery_months": round(_months_between(trough_date, recovered_date), 1) if recovered_date else None,
                "recovered": recovered_date is not None,
            }
        )

    return resolved


def summarize_extended_episodes(episodes: list[dict]) -> dict:
    """Sintesi statistica degli episodi trovati da find_extended_episodes:
    su N episodi simili, correzione media e recupero medio. None/0 se non
    ci sono episodi risolti nello storico disponibile (non abbastanza
    anni, o il titolo non è mai stato così esteso prima) — mai un numero
    inventato per riempire il buco."""
    if not episodes:
        return {"num_episodes": 0, "avg_correction_pct": None, "avg_recovery_months": None, "num_not_recovered": 0, "episodes": []}
    corrections = [e["correction_pct"] for e in episodes]
    recoveries = [e["recovery_months"] for e in episodes if e["recovery_months"] is not None]
    return {
        "num_episodes": len(episodes),
        "avg_correction_pct": round(sum(corrections) / len(corrections), 1),
        "avg_recovery_months": round(sum(recoveries) / len(recoveries), 1) if recoveries else None,
        "num_not_recovered": sum(1 for e in episodes if not e["recovered"]),
        "episodes": episodes,
    }


def compute_ath_distance(bars: list[DailyBar]) -> dict:
    """Distanza del prezzo attuale dal massimo storico assoluto (su tutto
    lo storico scaricato — non necessariamente il vero ATH di sempre se la
    fonte dati parte più tardi della quotazione, ma è il massimo di cui
    disponiamo verifica reale). Il massimo a 52 settimane è già coperto da
    technicals.compute_52w_range_position, non duplicato qui."""
    if not bars:
        return {"ath_price": None, "ath_date": None, "pct_from_ath": None}
    last_price = bars[-1]["close"]
    ath_bar = max(bars, key=lambda b: b["close"])
    if not ath_bar["close"]:
        return {"ath_price": None, "ath_date": None, "pct_from_ath": None}
    return {
        "ath_price": ath_bar["close"],
        "ath_date": ath_bar["date"],
        "pct_from_ath": round((last_price / ath_bar["close"] - 1) * 100, 2),
    }


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
