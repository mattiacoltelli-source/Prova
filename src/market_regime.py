"""Regime di mercato: contesto condiviso da tutti gli asset (SPY/QQQ,
VIX), calcolato UNA VOLTA per run e passato identico a ogni previsione
invece di lasciare che il modello lo deduca da dati grezzi o non lo veda
affatto.

Nessuna fonte dati nuova: SPY/QQQ sono barre daily già scaricate con lo
stesso fetch_daily_history() usato per gli indicatori tecnici; VIX è già
fetchato da FRED in macro.py — qui si aggiunge solo la STORIA della serie
(per il percentile) invece del solo valore più recente.

Cosa risolve: prima di questo modulo il prompt esponeva solo la forza
RELATIVA dell'asset rispetto a SPY (relative_strength_vs_spy_pct) e il
valore grezzo del VIX, senza mai dire se il mercato nel suo complesso
sta salendo/scendendo o se il VIX di oggi è alto o basso rispetto alla
sua storia recente — un titolo può sovraperformare SPY dell'1% sia in un
mercato che sale del 5% sia in uno che scende del 4%, ma il prompt non
distingueva i due scenari."""
from __future__ import annotations

from .data_sources.prices import DailyBar

# Percentile VIX sopra/sotto cui il "modo" di mercato si considera
# risk-off/risk-on. Basati solo sul percentile VIX (segnale di paura
# immediato) e non fusi con lo spread dei rendimenti (yield_curve_10y_2y,
# già mostrato separatamente nel blocco macro): quello spread si muove su
# una scala di mesi/anni, non giorni — un AND fra i due produrrebbe un
# flag quasi sempre "neutro" perché raramente si muovono insieme sulla
# stessa finestra temporale.
RISK_OFF_PERCENTILE = 70
RISK_ON_PERCENTILE = 40

# Storico usato per il percentile VIX: ~1 anno di borsa, coerente con
# l'orizzonte "regime recente" (non l'intera storia dal 1990, che
# mescolerebbe regimi di volatilità molto diversi tra loro).
VIX_PERCENTILE_LOOKBACK_DAYS = 252


def compute_index_return_pct(bars: list[DailyBar], lookback_days: int) -> float | None:
    """Rendimento % dell'indice nelle ultime `lookback_days` barre di
    trading — il trend ASSOLUTO del mercato, non relativo a un singolo
    asset. None se lo storico è insufficiente."""
    if len(bars) < lookback_days + 1:
        return None
    start = bars[-(lookback_days + 1)]["close"]
    end = bars[-1]["close"]
    if start == 0:
        return None
    return round((end - start) / start * 100, 2)


def compute_vix_percentile(
    vix_history: list[dict], lookback_days: int = VIX_PERCENTILE_LOOKBACK_DAYS
) -> dict | None:
    """Percentile del valore VIX più recente rispetto agli ultimi
    `lookback_days` valori: risponde a "il VIX di oggi è alto o basso
    rispetto alla sua storia recente", non solo al suo valore grezzo (18
    è alto o basso? dipende dal regime). None se la storia è
    insufficiente.

    `vix_history` è una lista di {"value": float, "date": str} in ordine
    cronologico crescente (vedi macro.fetch_series_history)."""
    if len(vix_history) < lookback_days:
        return None
    window = vix_history[-lookback_days:]
    latest = window[-1]["value"]
    below_or_equal = sum(1 for v in window if v["value"] <= latest)
    percentile = round(below_or_equal / len(window) * 100, 1)
    return {"value": latest, "percentile": percentile, "date": window[-1]["date"]}


def classify_risk_mode(vix_percentile: float) -> str:
    """risk-on / neutro / risk-off derivato solo dal percentile VIX."""
    if vix_percentile >= RISK_OFF_PERCENTILE:
        return "risk-off"
    if vix_percentile <= RISK_ON_PERCENTILE:
        return "risk-on"
    return "neutro"


def compute_market_regime(
    spy_bars: list[DailyBar] | None,
    qqq_bars: list[DailyBar] | None,
    vix_history: list[dict] | None,
) -> dict:
    """Bundle di tutto il regime di mercato per il run corrente. Ogni
    componente è opzionale e indipendente dagli altri (una fonte che
    fallisce non deve azzerare le altre) — stesso principio "segnale
    opzionale, mai bloccante" già seguito per fondamentali/news/insider."""
    regime: dict = {}

    if spy_bars:
        regime["spy_return_1d_pct"] = compute_index_return_pct(spy_bars, 1)
        regime["spy_return_5d_pct"] = compute_index_return_pct(spy_bars, 5)
        regime["spy_return_20d_pct"] = compute_index_return_pct(spy_bars, 20)

    if qqq_bars:
        regime["qqq_return_1d_pct"] = compute_index_return_pct(qqq_bars, 1)
        regime["qqq_return_5d_pct"] = compute_index_return_pct(qqq_bars, 5)
        regime["qqq_return_20d_pct"] = compute_index_return_pct(qqq_bars, 20)

    if vix_history:
        vix = compute_vix_percentile(vix_history)
        if vix is not None:
            regime["vix"] = vix
            regime["risk_mode"] = classify_risk_mode(vix["percentile"])

    return regime
