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

# --- Asset "trend" (fase 2: robotica/meccanica di precisione) --------------
# Sistema separato da ASSETS/HORIZONS sopra: qui l'obiettivo non è una
# previsione puntuale UP/DOWN/FLAT a breve termine, ma la classificazione
# del regime di trend di lungo periodo (vedi trend_analysis.py). Cadenza
# mensile (trend.yml — era settimanale, portata a mensile il 2026-09-17 su
# feedback utente): un ciclo semiconduttori/robotica si muove su anni, non
# ha senso ricalcolarlo più di una volta al mese.
#
# Perché THK/Harmonic Drive e non ABB: analisi storica del 2026-09-17 (10
# anni di dati) — ABB ha ceduto la divisione Robotics a SoftBank (chiusura
# prevista H2 2026), quindi da qui in avanti non è più un "puro" gioco
# robotica. THK (guide lineari/cuscinetti di precisione) e Harmonic Drive
# Systems (riduttori a gioco zero) sono i prodotti letteralmente richiesti
# e restano quotate come pure-play.
#
# TER (Teradyne) aggiunta il 2026-09-17: possiede Universal Robots (cobot)
# e MiR (robot mobili), ma il core business è test equipment per
# semiconduttori — cattura in un solo titolo sia il tema robotica sia il
# vero driver macro di questo paniere (correlazione SOX, vedi sotto).
# A differenza di THK/Harmonic Drive è quotata NASDAQ: nessun problema di
# accesso al mercato per un broker generalista, e a differenza loro ha
# copertura reale su SEC EDGAR (fondamentali) e Finnhub (news per ticker) —
# le due fonti che per i ticker Tokyo restano vuote in questo sistema.
#
# VRT (Vertiv Holdings) aggiunta il 2026-09-17: non è robotica, è
# infrastruttura elettrica/raffreddamento per data center AI — stessa
# logica "domanda visibile perché già in backlog pluriennale, non ipotesi"
# della tesi robotica/SOX, ma un tema diverso (capex data center AI, non
# capex robotica/precisione). Per questo il sistema resta lo stesso
# (trend_analysis.py è già agnostico rispetto al settore) ma la pagina è
# stata rietichettata da "Robotica" a "Trend strutturali" nel frontend, e
# il testo del prompt AI è parametrizzato per asset (vedi
# TREND_PROMPT_CONTEXT sotto) invece di assumere sempre "robotica".
# Quotata NYSE: nessun problema di accesso al mercato, fondamentali reali
# disponibili via SEC EDGAR.
ROBOTICS_ASSETS = ["THK", "HARMONIC_DRIVE", "TER", "VRT"]

# Ticker Yahoo Finance. THK/Harmonic Drive: Tokyo Stock Exchange (Harmonic
# Drive Systems ha ticker 6324, non 6371 come inizialmente ipotizzato —
# verificato per disponibilità dati storici prima di essere fissato qui).
# TER/VRT: NASDAQ/NYSE, stesso ticker ovunque.
ROBOTICS_TICKER = {"THK": "6481.T", "HARMONIC_DRIVE": "6324.T", "TER": "TER", "VRT": "VRT"}

# Query passata a news.fetch_recent_news(): per THK/Harmonic Drive è testo
# libero (non il ticker), perché Finnhub/Alpha Vantage in pratica non hanno
# news per ticker Tokyo su piano gratuito — solo GDELT (fallback finale,
# nessuna key) funziona lì, e gli serve una query sensata invece del
# ticker crudo "6481.T". TER/VRT sono invece ticker USA con copertura reale
# su Finnhub: qui la query è il ticker stesso, così la cascata funziona sul
# serio dal primo livello invece di scendere sempre a GDELT.
ROBOTICS_NEWS_QUERY = {
    "THK": "THK Co Ltd linear motion robotics",
    "HARMONIC_DRIVE": "Harmonic Drive Systems robot reducer",
    "TER": "TER",
    "VRT": "VRT",
}

# Benchmark macro per questo sistema: scoperto empiricamente per il
# paniere robotica (correlazione 0.55-0.76 sui rendimenti annuali
# 2016-2026, vs quasi zero con la Produzione Industriale USA) — il vero
# driver è il ciclo capex semiconduttori/AI, non l'industria generica.
# Indice Philadelphia Semiconductor, nessuna key richiesta (stessa fonte
# Yahoo dei prezzi). Riusato anche per VRT come proxy ragionevole dello
# stesso ciclo di spesa AI (semiconduttori e data center sono finanziati
# dallo stesso capex degli hyperscaler), ma senza la stessa verifica
# empirica specifica fatta per la robotica — vedi TREND_PROMPT_CONTEXT,
# che tiene il claim onesto (proxy non validata) invece di spacciarlo per
# lo stesso "driver dominante scoperto empiricamente" della robotica.
ROBOTICS_BENCHMARK_TICKER = "^SOX"

# Cadenza di rigenerazione per asset, in mesi. THK/Harmonic Drive/TER
# restano mensili (feedback utente 2026-09-17). VRT è trimestrale: il
# segnale che conta davvero per la tesi (crescita backlog/ordini) esce
# solo con le trimestrali, quindi rigenerare la lettura ogni mese
# sprecherebbe budget AI senza nuovo segnale reale nel mezzo.
ASSET_CADENCE_MONTHS = {"THK": 1, "HARMONIC_DRIVE": 1, "TER": 1, "VRT": 3}

# Testo del prompt che varia per asset (trend_predictor.build_trend_prompt):
# la robotica ha un'analisi storica specifica alle spalle (correlazione
# SOX verificata, range di drawdown 45-80% osservato sui 10 anni di dati),
# VRT no — il testo per VRT è più cauto invece di riciclare claim empirici
# validati solo per l'altro paniere.
TREND_PROMPT_CONTEXT = {
    "THK": {
        "sector_label": "robotica/automazione/meccanica di precisione",
        "benchmark_intro": "Driver macro dominante per questo paniere (scoperto empiricamente, non produzione industriale generica)",
        "cyclicality_note": (
            "questo è un titolo storicamente CICLICO (boom-bust di 3-4 anni legati al ciclo capex "
            "semiconduttori/AI, con drawdown storici del 45-80% dai picchi), non un trend lineare"
        ),
    },
    "HARMONIC_DRIVE": {
        "sector_label": "robotica/automazione/meccanica di precisione",
        "benchmark_intro": "Driver macro dominante per questo paniere (scoperto empiricamente, non produzione industriale generica)",
        "cyclicality_note": (
            "questo è un titolo storicamente CICLICO (boom-bust di 3-4 anni legati al ciclo capex "
            "semiconduttori/AI, con drawdown storici del 45-80% dai picchi), non un trend lineare"
        ),
    },
    "TER": {
        "sector_label": "robotica/automazione/meccanica di precisione (test equipment per semiconduttori)",
        "benchmark_intro": "Driver macro dominante per questo paniere (scoperto empiricamente, non produzione industriale generica)",
        "cyclicality_note": (
            "questo è un titolo storicamente CICLICO (boom-bust di 3-4 anni legati al ciclo capex "
            "semiconduttori/AI, con drawdown storici del 45-80% dai picchi), non un trend lineare"
        ),
    },
    "VRT": {
        "sector_label": "infrastruttura elettrica e di raffreddamento per data center AI",
        "benchmark_intro": (
            "Indice preso come proxy del ciclo di spesa in semiconduttori/infrastrutture AI (stessa area "
            "di domanda del paniere robotica di questo sistema, ma correlazione non ancora validata in "
            "modo specifico su questo titolo)"
        ),
        "cyclicality_note": (
            "valuta la ciclicità di questo titolo sui numeri sopra (drawdown massimo, volatilità, fase "
            "rispetto alla media mobile) invece di assumere il pattern osservato sul paniere robotica: "
            "una fase 'molto_estesa' tende comunque a essere seguita da correzioni anche quando il trend "
            "di fondo resta positivo, ma l'ampiezza storica dei drawdown non è verificata per questo titolo"
        ),
    },
}

# Orizzonti di analisi trend, in anni (non giorni/orizzonti brevi come
# HORIZONS sopra).
TREND_HORIZONS_YEARS = [1, 3, 5, 10]

# Finestra della media mobile di lungo periodo usata per classificare la
# fase del ciclo (ESTESA/NEUTRALE/COMPRESSA): 200 settimane (~4 anni),
# coerente con l'analisi storica che ha mostrato cicli boom-bust di 3-4
# anni su questo paniere.
TREND_MA_WEEKS = 200

# Tetto di spesa AI separato da MAX_AI_CALLS_PER_DAY: cadenza MENSILE (non
# settimanale — un ciclo pluriennale non ha senso ricalcolarlo più spesso,
# feedback utente 2026-09-17), 3 asset x 1 chiamata = 3 attese, margine
# ampio per eventuali retry/test manuali nello stesso mese.
MAX_TREND_AI_CALLS_PER_MONTH = 9

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

# Più ampio di ANTHROPIC_MAX_TOKENS: l'output atteso qui è una narrativa
# discorsiva (driver, rischi) invece di un singolo JSON compatto UP/DOWN/FLAT.
TREND_ANTHROPIC_MAX_TOKENS = 700

# --- Tetto di spesa (enforcement lato codice) ------------------------------
# 3 asset x 3 orizzonti x 1 slot/giorno = 9 chiamate attese al massimo.
MAX_AI_CALLS_PER_DAY = 15

# Istantanee prezzi (snapshot_run.py): 3 round/giorno, corrispondenti ai 3
# tick cron di snapshot.yml. Il tetto vale per il TOTALE giornaliero
# (automatici + manuali insieme, non 3 automatici + altri 3 manuali): un
# round manuale forzato da dashboard consuma uno degli stessi 3, così se
# uno scheduled tick non è scattato lo si può recuperare a mano senza
# rischiare di finire con più di 3 istantanee in un giorno.
SNAPSHOT_MAX_PER_DAY = 3

# --- Percorsi ---------------------------------------------------------------

DATA_DIR = "data"
STATE_DIR = "data/_state"
PENDING_FILE = "data/pending.json"
REPORT_FILE = "REPORT.md"
ERROR_ANALYSIS_FILE = "ERROR_ANALYSIS.md"


def asset_dir(asset: str) -> str:
    return f"{DATA_DIR}/{asset.lower()}"


def predictions_file(asset: str) -> str:
    return f"{asset_dir(asset)}/predictions.jsonl"


def outcomes_file(asset: str) -> str:
    return f"{asset_dir(asset)}/outcomes.jsonl"


def snapshot_file(asset: str) -> str:
    return f"{asset_dir(asset)}/snapshot.json"


def robotics_asset_dir(asset: str) -> str:
    return f"{DATA_DIR}/robotics/{asset.lower()}"


def trend_file(asset: str) -> str:
    return f"{robotics_asset_dir(asset)}/trend.jsonl"


def price_series_file(asset: str) -> str:
    return f"{robotics_asset_dir(asset)}/price_series.json"
