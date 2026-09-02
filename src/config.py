"""Configurazione centrale dell'agente predittivo."""
from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")

# --- Asset ---------------------------------------------------------------

ASSETS = ["NVDA", "MSFT", "AAPL"]

# Tutte azioni (nessun ETF attivo al momento): fondamentali via SEC EDGAR.
ASSET_TYPE = {"NVDA": "stock", "MSFT": "stock", "AAPL": "stock"}

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
# (ora, minuto)
PREDICTION_SLOTS_ET = [
    (9, 45),
    (12, 0),
    (15, 45),
]

# Una scheduled run di GitHub Actions può partire in ritardo rispetto al
# cron (anche di ore, su repo pubblici in orari di picco). Uno slot resta
# "recuperabile" fino a questa finestra dopo l'orario nominale, così un
# run in ritardo esegue comunque il prossimo slot dovuto invece di saltarlo.
SLOT_CATCHUP_MINUTES = 180

# --- Soglia di volatilità per UP/DOWN/FLAT ---------------------------------
# threshold_pct = VOLATILITY_K * ATR% (14 giorni) * sqrt(trading_days)
# ATR invece di una deviazione standard a finestra fissa: più reattivo a un
# cambio di regime di volatilità recente e include i gap overnight, che una
# misura chiusura-chiusura ignora. K=0.5 è un punto di partenza ragionevole
# ma arbitrario, da ricalibrare in futuro sulla base dei risultati reali in
# REPORT.md (nessuna previsione storica precedente a questo cambio è rimasta
# valida da confrontare: lo storico è stato azzerato insieme al cambio).
VOLATILITY_K = 0.5

# --- Modello Anthropic ------------------------------------------------------

ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_MAX_TOKENS = 500

# --- Tetto di spesa (enforcement lato codice) ------------------------------
# 3 asset x 3 orizzonti x 3 slot/giorno = 27 chiamate attese al massimo.
MAX_AI_CALLS_PER_DAY = 32

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
