"""Configurazione centrale dell'agente predittivo."""
from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")

# --- Asset ---------------------------------------------------------------

ASSETS = ["NVDA", "MSFT", "AAPL"]

# Tutte azioni (nessun ETF attivo al momento): fondamentali via SEC EDGAR.
ASSET_TYPE = {"NVDA": "stock", "MSFT": "stock", "AAPL": "stock"}

# ETF di settore usato come secondo benchmark oltre a SPY (stessa fonte
# Yahoo Finance già usata per i prezzi, nessuna API nuova): forza relativa
# e beta vs il proprio settore, più specifici del solo mercato generale.
SECTOR_BENCHMARK = {"NVDA": "SMH", "MSFT": "XLK", "AAPL": "XLK"}

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
# Un solo slot vicino alla chiusura: rigenerare più volte nello stesso
# giorno cambiava pochissimo la previsione (prezzo di partenza quasi
# identico) per gli orizzonti 7g/1m, e triplicava senza un vero motivo le
# chiamate AI e la quota sulle fonti dati (es. Alpha Vantage, 25/giorno
# gratuite condivise con fondamentali/news/stime analisti).
# (ora, minuto)
PREDICTION_SLOTS_ET = [
    (15, 45),
]

# Una scheduled run di GitHub Actions può partire in ritardo rispetto al
# cron (anche di ore, su repo pubblici in orari di picco) o, come successo
# il 2026-09-02, non partire affatto per l'intera giornata (nessuno dei 5
# tick schedulati di predict.yml è scattato). Uno slot resta "recuperabile"
# fino a questa finestra dopo l'orario nominale, così un run in ritardo
# esegue comunque il prossimo slot dovuto invece di saltarlo — allargata da
# 180 a 480 minuti (8h) per coprire l'intera finestra utile dell'orario di
# mercato USA fino a sera, restando comunque nello stesso giorno di
# calendario ET (find_due_slot confronta sempre rispetto a "oggi" ET).
SLOT_CATCHUP_MINUTES = 480

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
# 3 asset x 3 orizzonti x 1 slot/giorno = 9 chiamate attese al massimo.
MAX_AI_CALLS_PER_DAY = 15

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
