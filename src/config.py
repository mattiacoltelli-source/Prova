"""Configurazione centrale dell'agente predittivo."""
from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")

# --- Asset ---------------------------------------------------------------

ASSETS = ["SPY", "AAPL", "NVDA", "MSFT"]

# SPY è un ETF (nessun filing XBRL standard su SEC EDGAR); AAPL, NVDA, MSFT sono azioni.
ASSET_TYPE = {"SPY": "etf", "AAPL": "stock", "NVDA": "stock", "MSFT": "stock"}

# Email di contatto richiesta da SEC EDGAR nell'header User-Agent (non è una API key).
SEC_EDGAR_CONTACT_EMAIL = "mattia.coltelli@gmail.com"

# --- Orizzonti (fase 1) ----------------------------------------------------


@dataclass(frozen=True)
class Horizon:
    code: str
    days: int  # giorni di calendario usati per calcolare target_at
    trading_days: float  # giorni di trading usati per scalare la volatilità


HORIZONS = [
    Horizon(code="1d", days=1, trading_days=1),
    Horizon(code="7d", days=7, trading_days=5),
    Horizon(code="1m", days=30, trading_days=21),
]

# --- Slot di previsione giornalieri (ora locale US/Eastern) ----------------
# (ora, minuto, tolleranza in minuti)
PREDICTION_SLOTS_ET = [
    (9, 45, 20),
    (12, 0, 20),
    (15, 45, 20),
]

# --- Soglia di volatilità per UP/DOWN/FLAT ---------------------------------
# threshold_pct = VOLATILITY_K * (std dev rendimenti giornalieri storici) * sqrt(trading_days)
VOLATILITY_K = 0.5
VOLATILITY_LOOKBACK_DAYS = 60

# --- Modello Anthropic ------------------------------------------------------

ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_MAX_TOKENS = 500

# --- Tetto di spesa (enforcement lato codice) ------------------------------

MAX_AI_CALLS_PER_DAY = 24

# --- Percorsi ---------------------------------------------------------------

DATA_DIR = "data"
STATE_DIR = "data/_state"
PENDING_FILE = "data/pending.json"
REPORT_FILE = "REPORT.md"


def asset_dir(asset: str) -> str:
    return f"{DATA_DIR}/{asset.lower()}"


def predictions_file(asset: str) -> str:
    return f"{asset_dir(asset)}/predictions.jsonl"


def outcomes_file(asset: str) -> str:
    return f"{asset_dir(asset)}/outcomes.jsonl"
