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
#
# 7:00 ET, PRIMA dell'apertura (9:30 ET) invece che dopo la chiusura: a
# quell'ora prices.fetch_latest_price() (campo Yahoo regularMarketPrice)
# ritorna ancora l'ultima chiusura ufficiale, congelata dalle 16:00 ET di
# ieri fino alla riapertura — quindi il "prezzo di partenza" è identico a
# quello di uno slot post-chiusura, ma il modello vede in più le notizie
# overnight e gli utili trimestrali pubblicati prima dell'apertura (BMO,
# "before market open"), che uno slot post-chiusura si perde sempre (così
# come uno slot pre-chiusura si perde gli utili AMC, "after market close":
# gli slot alle 15:45 e alle 16:30 usati prima di questo avevano lo stesso
# problema, solo sull'altro lato della giornata).
#
# 8:00 -> 7:00 ET il 2026-09-04: un'ora in più di margine di recupero
# (150 minuti invece di 90) prima dell'apertura, a fronte di una probabilità
# leggermente più alta di non aver ancora visto gli utili BMO pubblicati
# proprio a ridosso dell'apertura (la maggior parte esce comunque tra le
# 6:00 e le 8:00 ET). Non richiede nessun altro cambio: il prezzo resta
# congelato per tutto l'intervallo 16:00 ET di ieri - 9:30 ET di oggi,
# qualunque ora in quella finestra dà lo stesso prezzo di riferimento.
#
# Il prezzo congelato pre-apertura richiede che target_at sia ancorato a
# quella chiusura invece che all'orario reale di esecuzione dello script —
# vedi predict_run.py: _reference_price()/_target_at(). Per lo stesso
# motivo la finestra di recupero sotto resta corta: dopo l'apertura il
# prezzo torna a muoversi in tempo reale e l'assunzione "prezzo congelato"
# non vale più (anche se _reference_price() gestisce anche questo caso,
# usando l'ultima chiusura storica invece del prezzo intraday).
# (ora, minuto)
PREDICTION_SLOTS_ET = [
    (7, 0),
]

# Una scheduled run di GitHub Actions può partire in ritardo rispetto al
# cron (anche di ore, su repo pubblici in orari di picco) o, come successo
# il 2026-09-02, non partire affatto per l'intera giornata (nessuno dei 5
# tick schedulati di predict.yml è scattato). Uno slot resta "recuperabile"
# fino a questa finestra dopo l'orario nominale, così un run in ritardo
# esegue comunque il prossimo slot dovuto invece di saltarlo.
#
# Qui la finestra è volutamente corta (145 minuti: 7:00-9:25 ET, 5 minuti
# di margine prima dell'apertura delle 9:30) invece che ampia come con lo
# slot post-chiusura di prima — un recupero che scattasse dopo l'apertura
# resta corretto (_reference_price() usa l'ultima chiusura storica invece
# del prezzo intraday quando serve), ma non ha senso allargare comunque la
# finestra oltre quel limite: lo slot esiste apposta per catturare le
# notizie pre-apertura, un recupero a mercato aperto le perde comunque. La
# ridondanza per compensare (più probabilità che GitHub faccia partire
# almeno un tick nella finestra più stretta) è
# nei tick sfalsati di predict.yml invece che in una finestra larga.
SLOT_CATCHUP_MINUTES = 145

# --- Soglia di volatilità per UP/DOWN/FLAT ---------------------------------
# threshold_pct = VOLATILITY_K * ATR% (14 giorni) * sqrt(trading_days)
# ATR invece di una deviazione standard a finestra fissa: più reattivo a un
# cambio di regime di volatilità recente e include i gap overnight, che una
# misura chiusura-chiusura ignora.
#
# K=0.5 -> 0.4 il 2026-09-03: prima ricalibrazione manuale (non ancora
# basata sulla tabella di calibrazione in REPORT.md, che con 1-2 giorni di
# dati reali era ancora troppo poco popolata per dire qualcosa — resta un
# punto di partenza ragionevole ma arbitrario, ancora da validare sui
# risultati reali). Storico azzerato insieme al cambio, stesso motivo e
# stesso pattern della ricalibrazione precedente (ATR al posto della
# deviazione standard): le soglie congelate nelle previsioni già fatte non
# sono più confrontabili con quelle calcolate con il nuovo K.
VOLATILITY_K = 0.4

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


def snapshot_file(asset: str) -> str:
    return f"{asset_dir(asset)}/snapshot.json"
