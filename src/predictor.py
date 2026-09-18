"""Costruzione del prompt, chiamata al modello Claude e parsing/validazione
della previsione strutturata."""
from __future__ import annotations

import json
import os
import re

import anthropic

from . import config
from .data_sources import news as news_source


class PredictionParseError(RuntimeError):
    pass


def build_prompt(
    asset: str,
    horizon_code: str,
    price: float,
    price_asof: str,
    threshold_pct: float,
    news: list[dict],
    fundamentals: dict | None,
    macro: dict,
    base_rates: dict | None = None,
    technicals: dict | None = None,
    analyst_outlook: dict | None = None,
    insider_summary: dict | None = None,
) -> str:
    news_block = (
        "\n".join(f"- ({n['published_at']}) {n['headline']}" for n in news[:8])
        if news
        else "Nessuna news recente disponibile."
    )
    sentiment_avg = news_source.average_sentiment(news)
    if sentiment_avg is not None:
        news_block += f"\n\nSentiment medio delle news (-1..+1): {sentiment_avg}"
    fundamentals_block = json.dumps(fundamentals["metrics"], indent=2) if fundamentals else "Non disponibili."
    macro_block = "\n".join(f"- {k}: {v['value']} (al {v['date']})" for k, v in macro.items()) or "Non disponibili."

    analyst_lines = []
    if analyst_outlook:
        if analyst_outlook.get("next_report_date"):
            analyst_lines.append(f"- Prossima data di bilancio: {analyst_outlook['next_report_date']}")
        if analyst_outlook.get("eps_estimate_average") is not None:
            analyst_lines.append(
                f"- Stima EPS media consenso analisti (trimestre chiuso al "
                f"{analyst_outlook.get('fiscal_quarter_ending')}): {analyst_outlook['eps_estimate_average']} "
                f"({analyst_outlook.get('eps_estimate_analyst_count')} analisti)"
            )
        up = analyst_outlook.get("eps_revisions_up_30d")
        down = analyst_outlook.get("eps_revisions_down_30d")
        if up is not None or down is not None:
            analyst_lines.append(
                f"- Revisioni stima EPS ultimi 30gg: {up or 0} al rialzo, {down or 0} al ribasso"
            )
    analyst_block = "\n".join(analyst_lines) or "Non disponibili."

    if insider_summary:
        insider_block = (
            f"Ultimi {insider_summary['lookback_days']}gg: "
            f"{insider_summary['buy_transactions']} acquisti sul mercato aperto, "
            f"{insider_summary['sell_transactions']} vendite, "
            f"netto {insider_summary['net_shares']:+} azioni "
            "(solo transazioni discrezionali, escluse vesting/opzioni/donazioni)"
        )
    else:
        insider_block = "Nessuna transazione insider rilevante nella finestra osservata."

    technicals = technicals or {}
    technical_lines = []
    if technicals.get("obv_trend"):
        technical_lines.append(f"- On-Balance Volume: {technicals['obv_trend']}")
    if technicals.get("cmf") is not None:
        technical_lines.append(f"- Chaikin Money Flow (20gg): {technicals['cmf']} (range -1..+1, >0 = pressione in acquisto)")
    if technicals.get("relative_strength_vs_spy_pct") is not None:
        technical_lines.append(
            f"- Forza relativa vs S&P 500 (60gg): {technicals['relative_strength_vs_spy_pct']}% "
            "(positivo = sta sovraperformando il mercato)"
        )
    sector_ticker = technicals.get("sector_benchmark")
    if technicals.get("relative_strength_vs_sector_pct") is not None and sector_ticker:
        technical_lines.append(
            f"- Forza relativa vs settore {sector_ticker} (60gg): "
            f"{technicals['relative_strength_vs_sector_pct']}% "
            "(positivo = sta sovraperformando il proprio settore, non solo il mercato generale)"
        )
    if technicals.get("sma_trend"):
        technical_lines.append(f"- Trend di fondo (SMA 50/200): {technicals['sma_trend']}")
    if technicals.get("ema_trend"):
        technical_lines.append(f"- Trend di breve termine (EMA 9/21): {technicals['ema_trend']}")
    if technicals.get("rsi_14") is not None:
        technical_lines.append(
            f"- RSI (14gg): {technicals['rsi_14']} (>70 ipercomprato, <30 ipervenduto)"
        )
    macd = technicals.get("macd")
    if macd is not None:
        technical_lines.append(
            f"- MACD (12/26/9): linea {macd['macd']}, segnale {macd['signal']}, "
            f"istogramma {macd['histogram']} (istogramma >0 = momentum rialzista)"
        )
    if technicals.get("atr_pct") is not None:
        technical_lines.append(
            f"- ATR (14gg): {technicals['atr_pct']}% del prezzo attuale (ampiezza media di movimento giornaliero)"
        )
    if technicals.get("beta_vs_spy") is not None:
        technical_lines.append(
            f"- Beta vs S&P 500 (60gg): {technicals['beta_vs_spy']} "
            "(>1 = più volatile del mercato, <1 = meno volatile)"
        )
    if technicals.get("beta_vs_sector") is not None and sector_ticker:
        technical_lines.append(
            f"- Beta vs settore {sector_ticker} (60gg): {technicals['beta_vs_sector']} "
            "(>1 = più volatile del proprio settore, <1 = meno volatile)"
        )
    if technicals.get("bollinger_percent_b") is not None:
        technical_lines.append(
            f"- Bande di Bollinger (%B, 20gg): {technicals['bollinger_percent_b']} "
            "(0 = bordo inferiore, 1 = bordo superiore, <0 o >1 = fuori banda)"
        )
    range_52w = technicals.get("range_52w")
    if range_52w is not None:
        technical_lines.append(
            f"- Distanza da massimo 52 settimane: {range_52w['pct_from_high']}%, "
            f"da minimo 52 settimane: {range_52w['pct_from_low']}%"
        )
    if technicals.get("relative_volume") is not None:
        technical_lines.append(
            f"- Volume relativo (ultima barra vs media 20gg): {technicals['relative_volume']}x "
            "(>1 = attività sopra la norma recente)"
        )
    technicals_block = "\n".join(technical_lines) or "Non disponibili."

    # Frequenze storiche reali della coppia asset/orizzonte. Sono il pezzo
    # che mancava nella v1 del prompt: senza di esse il modello riceveva
    # una lunga lista di indicatori di trend e nessun riferimento su quanto
    # spesso ciascuna classe si verifichi davvero. Il risultato misurato su
    # 45 previsioni valutate è stato UP previsto nel 62% dei casi contro un
    # 28-38% di occorrenza reale, e DOWN mai previsto contro un 45%.
    brier_note = """Le tue probabilità verranno punteggiate con il Brier Score quando l'esito sarà noto:
errore = (probability_up - esito_up)^2 + (probability_down - esito_down)^2 + (probability_flat - esito_flat)^2,
dove esito_X vale 1 per la classe realmente accaduta e 0 per le altre due. Conviene SEMPRE dichiarare
le probabilità che ritieni vere, non spostarle verso una singola classe per "sembrare sicuro": un 90%
sbagliato costa molto più di un 40%/35%/25% onesto che poi risulta sbagliato. Se non hai un vantaggio
informativo specifico, una distribuzione vicina alle FREQUENZE STORICHE sotto è la scelta onesta, non
un fallimento."""

    if base_rates:
        pct = base_rates["pct"]
        base_rates_block = f"""Su {base_rates['observations']} osservazioni storiche di questo stesso asset e
orizzonte (dal {base_rates['first_date']}), classificate con la STESSA formula di banda
usata qui, le tre classi si sono verificate con questa frequenza:
  UP {pct['UP']}%  ·  DOWN {pct['DOWN']}%  ·  FLAT {pct['FLAT']}%

Non è un suggerimento su cosa rispondere: è il metro con cui la tua previsione
verrà giudicata. Prevedere sempre "{base_rates['majority_class']}" senza guardare nulla otterrebbe
{base_rates['majority_pct']}% di accuratezza, ed è esattamente la strategia con cui vieni
confrontato. Per risultare utile devi discriminare meglio di così, non
allinearti a queste percentuali."""
    else:
        base_rates_block = (
            "Non disponibili per questa coppia asset/orizzonte."
        )

    return f"""Devi stimare la probabilità di ciascuno dei tre esiti possibili per {asset}
nell'orizzonte {horizon_code} a partire da adesso. Non è una valutazione del titolo né
una raccomandazione: è una distribuzione di probabilità su tre classi, verificabile con
il prezzo reale alla scadenza dell'orizzonte.

Prezzo attuale: {price} (rilevato: {price_asof})
Banda neutra (FLAT) calcolata sulla volatilità storica recente: +/- {threshold_pct}%
  → UP se la variazione alla scadenza sarà superiore a +{threshold_pct}%
  → DOWN se sarà inferiore a -{threshold_pct}%
  → FLAT se resterà entro la banda

DUE COSE DA NON CONFONDERE. Gli indicatori qui sotto (medie mobili, MACD, forza
relativa, consenso analisti) descrivono il REGIME ATTUALE del titolo: dicono se si
trova in una tendenza rialzista o ribassista. Non dicono quanto è probabile che
superi la banda di +/- {threshold_pct}% entro {horizon_code}. Sono domande diverse e
possono avere risposte opposte: un titolo in forte tendenza rialzista passa comunque
la maggior parte delle singole giornate dentro la banda, perché la tendenza è
l'accumulo di molti movimenti piccoli, non la garanzia di un movimento grande in
questo specifico orizzonte. "Il titolo sale" non implica "supererà +{threshold_pct}% entro {horizon_code}".

FREQUENZE STORICHE
{base_rates_block}

Tutte e tre le classi sono risposte legittime. In particolare DOWN: se gli indicatori
sono quasi sempre rialzisti su questi titoli, non ne segue che DOWN non si verifichi —
la frequenza storica sopra dice quanto si verifica per davvero.

{brier_note}

In `reasoning_short`, se ti discosti dalla frequenza storica, scrivi quale informazione
specifica di oggi lo giustifica.

News recenti:
{news_block}

Fondamentali/dati ETF disponibili:
{fundamentals_block}

Consenso analisti/prossimo bilancio:
{analyst_block}

Transazioni insider (dirigenti/amministratori, solo mercato aperto):
{insider_block}

Contesto macro:
{macro_block}

Indicatori tecnici aggiuntivi:
{technicals_block}

Rispondi ESCLUSIVAMENTE con un oggetto JSON valido, nessun altro testo, con questa forma esatta:
{{"probability_up": <0-1>, "probability_down": <0-1>, "probability_flat": <0-1>, "reasoning_short": "<massimo 3 frasi>"}}
Le tre probabilità devono sommare a 1 (tolleranza +/- 0.02).
"""


def _extract_json(text: str) -> dict:
    text = text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise PredictionParseError(f"Nessun JSON trovato nella risposta del modello: {text!r}")
    return json.loads(match.group(0))


def call_model(prompt: str) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=config.ANTHROPIC_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in resp.content if block.type == "text")


CLASS_TO_PROB_KEY = {"UP": "probability_up", "DOWN": "probability_down", "FLAT": "probability_flat"}

# Tolleranza sulla somma delle tre probabilità: il modello arrotonda a mano,
# 1.02 (es. 0.34+0.34+0.34) è normale rumore di arrotondamento, non un
# errore di formato. Oltre questa soglia il record viene scartato invece di
# normalizzato in silenzio: una somma molto lontana da 1 (es. 1.4) indica
# che il modello ha frainteso il formato, non un arrotondamento — meglio
# uno skipped_model_error esplicito che una probabilità silenziosamente
# sbagliata scritta per sempre nella hash-chain.
SUM_TOLERANCE = 0.05


def parse_prediction(raw_text: str) -> dict:
    data = _extract_json(raw_text)
    reasoning = str(data.get("reasoning_short", "")).strip()

    probs: dict[str, float] = {}
    for cls, key in CLASS_TO_PROB_KEY.items():
        value = data.get(key)
        if not isinstance(value, (int, float)) or not (0 <= value <= 1):
            raise PredictionParseError(f"{key} non valida: {value!r}")
        probs[cls] = float(value)

    total = sum(probs.values())
    if abs(total - 1.0) > SUM_TOLERANCE:
        raise PredictionParseError(f"le probabilità non sommano a 1 (somma={total!r}): {probs!r}")
    # Normalizzazione esatta a somma 1 dopo la validazione: l'arrotondamento
    # del modello (es. somma 0.99 o 1.01) non deve propagarsi al Brier
    # Score, che assume una distribuzione di probabilità valida.
    probs = {cls: v / total for cls, v in probs.items()}

    if not reasoning:
        raise PredictionParseError("reasoning_short mancante")

    # predicted_class/confidence restano nel record, DERIVATI dalle
    # probabilità invece che auto-dichiarati dal modello: predicted_class è
    # la classe più probabile, confidence è la sua probabilità in punti
    # percentuali. Mantiene compatibile tutto ciò che già usa questi due
    # campi (matrice di confusione, bucket di calibrazione, badge nel
    # frontend) senza che il modello debba più "inventarsi" una confidence
    # separata dalle probabilità che ha appena dichiarato.
    predicted_class = max(probs, key=probs.get)
    confidence = round(probs[predicted_class] * 100)

    return {
        "predicted_class": predicted_class,
        "confidence": confidence,
        "probability_up": round(probs["UP"], 4),
        "probability_down": round(probs["DOWN"], 4),
        "probability_flat": round(probs["FLAT"], 4),
        "reasoning_short": reasoning,
    }


def generate_prediction(
    asset: str,
    horizon_code: str,
    price: float,
    price_asof: str,
    threshold_pct: float,
    news: list[dict],
    fundamentals: dict | None,
    macro: dict,
    base_rates: dict | None = None,
    technicals: dict | None = None,
    analyst_outlook: dict | None = None,
    insider_summary: dict | None = None,
) -> dict:
    # Argomenti per nome, non posizionali: la firma di build_prompt ha già
    # dieci parametri opzionali e un inserimento in mezzo sposterebbe in
    # silenzio tutto quello che segue.
    prompt = build_prompt(
        asset=asset,
        horizon_code=horizon_code,
        price=price,
        price_asof=price_asof,
        threshold_pct=threshold_pct,
        news=news,
        fundamentals=fundamentals,
        macro=macro,
        base_rates=base_rates,
        technicals=technicals,
        analyst_outlook=analyst_outlook,
        insider_summary=insider_summary,
    )
    raw = call_model(prompt)
    return parse_prediction(raw)
