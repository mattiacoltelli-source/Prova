"""Rigenera ERROR_ANALYSIS.md: report diagnostico sui pattern di errore
sistematici del modello (bias di classe, casi in cui una previsione non
azzecca mai), pensato per essere rigenerato ogni ~2 settimane invece che ad
ogni evaluate.yml.

Complementare a REPORT.md (la dashboard di accuratezza aggiornata ad ogni
valutazione, con matrice di confusione grezza e calibrazione): qui
l'obiettivo è dare un primo indizio leggibile su EVENTUALI bias, senza
toccare mai soglie di volatilità, prompt o logica di previsione — resta un
report da leggere, non un meccanismo che si autocorregge. Con un campione
ancora piccolo (poche decine di previsioni valutate) un segnale forte qui
può benissimo essere solo rumore del periodo osservato, non un difetto
reale del modello: le soglie sotto sono scelte apposta larghe e il report
lo ricorda esplicitamente finché il campione resta sotto MIN_SAMPLE_SIZE.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from . import config
from .report import CLASSES, _accuracy, load_all_outcomes

# Sotto questo numero di previsioni valutate (su tutti gli asset/orizzonti
# insieme), i numeri di questo report sono un indizio da tenere d'occhio nel
# tempo, non una base per decidere qualcosa.
MIN_SAMPLE_SIZE = 30

# Scarto minimo (in punti percentuali) tra quota prevista e quota reale di
# una classe perché valga la pena segnalarlo come possibile bias.
BIAS_THRESHOLD_PCT = 20.0

# Sotto questo numero di previsioni per una classe, un'accuratezza dello 0%
# è troppo poco significativa per essere segnalata (potrebbe essere 0/1).
MIN_N_FOR_ZERO_ACCURACY_FLAG = 3


def _class_share(rows: list[dict], field: str) -> dict[str, tuple[int, float]]:
    total = len(rows)
    counts = {cls: 0 for cls in CLASSES}
    for r in rows:
        counts[r[field]] = counts.get(r[field], 0) + 1
    return {cls: (n, round(n / total * 100, 1) if total else 0.0) for cls, n in counts.items()}


def _per_asset_accuracy(rows: list[dict]) -> list[tuple[str, int, int, float]]:
    grouped = defaultdict(list)
    for r in rows:
        grouped[r["asset"]].append(r)
    return [(asset, *_accuracy(sub)) for asset, sub in sorted(grouped.items())]


def _per_predicted_class_accuracy(rows: list[dict]) -> list[tuple[str, int, int, float]]:
    grouped = defaultdict(list)
    for r in rows:
        grouped[r["predicted_class"]].append(r)
    return [(cls, *_accuracy(grouped[cls])) for cls in CLASSES if grouped.get(cls)]


def _flag_observations(rows: list[dict]) -> list[str]:
    """Segnalazioni puramente meccaniche (soglie semplici, nessuna
    inferenza statistica sofisticata): pensate per farsi notare in un
    report letto ogni due settimane, non per essere lette come conclusioni."""
    total = len(rows)
    if total == 0:
        return []

    flags = []
    predicted_share = _class_share(rows, "predicted_class")
    actual_share = _class_share(rows, "actual_class")

    for cls in CLASSES:
        pred_n, pred_pct = predicted_share[cls]
        actual_n, actual_pct = actual_share[cls]
        if pred_n == 0 and actual_n > 0:
            flags.append(
                f"**{cls}** osservata nella realtà {actual_n} volte ({actual_pct}%) ma mai prevista dal modello."
            )
        elif abs(pred_pct - actual_pct) >= BIAS_THRESHOLD_PCT:
            direction = "più spesso di quanto" if pred_pct > actual_pct else "meno spesso di quanto"
            flags.append(
                f"**{cls}** prevista {direction} accada davvero: {pred_pct}% delle previsioni contro "
                f"{actual_pct}% delle volte in cui si è verificata realmente."
            )

    for cls, _, n, pct in _per_predicted_class_accuracy(rows):
        if n >= MIN_N_FOR_ZERO_ACCURACY_FLAG and pct == 0.0:
            flags.append(f"Quando ha previsto **{cls}** ({n} volte), non ha mai indovinato.")

    return flags


def render_markdown(rows: list[dict]) -> str:
    generated_at = dt.datetime.now(dt.timezone.utc).isoformat()
    total = len(rows)
    lines = [f"# Analisi errori — aggiornato al {generated_at}", ""]

    if total < MIN_SAMPLE_SIZE:
        lines += [
            f"⚠️ Campione ancora piccolo ({total} previsioni valutate, soglia indicativa {MIN_SAMPLE_SIZE}): "
            "i numeri sotto sono un indizio da tenere d'occhio nel tempo, non una conclusione "
            "statisticamente solida. Non modificare soglie di volatilità o prompt sulla base di questo "
            "report finché il campione non cresce.",
            "",
        ]

    if total == 0:
        lines.append("Nessuna previsione ancora valutata.")
        return "\n".join(lines) + "\n"

    _, _, pct = _accuracy(rows)
    lines += [f"**Previsioni valutate: {total} — accuratezza complessiva: {pct}%**", ""]

    lines += ["## Per asset", "", "| Asset | Valutate | Corrette | Accuratezza |", "|---|---|---|---|"]
    for asset, correct_n, n, asset_pct in _per_asset_accuracy(rows):
        lines.append(f"| {asset} | {n} | {correct_n} | {asset_pct}% |")
    lines.append("")

    lines += ["## Per classe prevista", "", "| Prevista | N. volte | Corrette | Accuratezza |", "|---|---|---|---|"]
    seen_classes = set()
    for cls, correct_n, n, cls_pct in _per_predicted_class_accuracy(rows):
        lines.append(f"| {cls} | {n} | {correct_n} | {cls_pct}% |")
        seen_classes.add(cls)
    for cls in CLASSES:
        if cls not in seen_classes:
            lines.append(f"| {cls} | 0 | — | mai prevista |")
    lines.append("")

    lines += ["## Pattern osservati", ""]
    flags = _flag_observations(rows)
    if flags:
        lines += [f"- {f}" for f in flags]
    else:
        lines.append("Nessun bias evidente con le soglie attuali.")
    lines.append("")

    confidences = [r["confidence"] for r in rows]
    lines += ["## Confidence", "", f"Range dichiarato: {min(confidences)}-{max(confidences)}%."]
    if total < MIN_SAMPLE_SIZE:
        lines.append("Campione troppo piccolo per dire se la confidence discrimina i casi corretti da quelli sbagliati.")
    lines.append("")

    return "\n".join(lines) + "\n"


def generate_report() -> None:
    rows = load_all_outcomes()
    with open(config.ERROR_ANALYSIS_FILE, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(rows))


if __name__ == "__main__":
    generate_report()
