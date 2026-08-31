"""Rigenera REPORT.md a partire dallo storico outcomes.jsonl: accuratezza
complessiva, per asset/orizzonte, matrice di confusione, calibrazione e
confronto con baseline naive (random e persistenza)."""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from . import config, storage

CLASSES = ["UP", "DOWN", "FLAT"]
CONFIDENCE_BUCKETS = [(0, 50, "bassa (0-49)"), (50, 75, "media (50-74)"), (75, 101, "alta (75-100)")]

CONFIDENCE_ANALYSIS_BUCKETS = [
    (50, 60, "50–59%"),
    (60, 70, "60–69%"),
    (70, 80, "70–79%"),
    (80, 90, "80–89%"),
    (90, 101, "90–100%"),
]


def load_all_outcomes() -> list[dict]:
    outcomes = []
    for asset in config.ASSETS:
        outcomes.extend(storage.read_all(config.outcomes_file(asset)))
    return outcomes


def _accuracy(rows: list[dict]) -> tuple[int, int, float]:
    total = len(rows)
    correct = sum(1 for r in rows if r["correct"])
    pct = round(correct / total * 100, 1) if total else 0.0
    return correct, total, pct


def _confusion_matrix(rows: list[dict]) -> dict[tuple[str, str], int]:
    matrix = defaultdict(int)
    for r in rows:
        matrix[(r["predicted_class"], r["actual_class"])] += 1
    return matrix


def _calibration(rows: list[dict]) -> list[tuple[str, int, float]]:
    out = []
    for low, high, label in CONFIDENCE_BUCKETS:
        bucket_rows = [r for r in rows if r.get("confidence") is not None and low <= r["confidence"] < high]
        _, total, pct = _accuracy(bucket_rows)
        out.append((label, total, pct))
    return out


def analyze_confidence_buckets(rows: list[dict]) -> list[dict]:
    """Analisi per fasce di confidence (50–59%, 60–69%, 70–79%, 80–89%, 90–100%).
    Calcola per ogni fascia: n, corrette, accuracy_pct, mean_confidence.
    Gestisce fasce vuote e ignora o gestisce in modo sicuro record con confidence invalida/fuori range.
    """
    out = []
    for low, high, label in CONFIDENCE_ANALYSIS_BUCKETS:
        bucket_rows = [
            r for r in rows
            if isinstance(r.get("confidence"), (int, float)) and low <= r["confidence"] < high
        ]
        n = len(bucket_rows)
        correct = sum(1 for r in bucket_rows if r.get("correct"))
        accuracy_pct = round(correct / n * 100, 1) if n > 0 else 0.0
        mean_conf = round(sum(r["confidence"] for r in bucket_rows) / n, 1) if n > 0 else 0.0

        out.append({
            "bucket_label": label,
            "total": n,
            "correct": correct,
            "accuracy_pct": accuracy_pct,
            "mean_confidence": mean_conf,
        })
    return out


def _persistence_baseline(rows: list[dict]) -> tuple[int, int, float]:
    """Baseline naive: prevede la stessa classe reale osservata nell'ultimo
    outcome risolto per la stessa coppia asset/orizzonte."""
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        grouped[(r["asset"], r["horizon"])].append(r)

    correct = total = 0
    for series in grouped.values():
        series.sort(key=lambda r: r["evaluated_at"])
        for i in range(1, len(series)):
            total += 1
            if series[i]["actual_class"] == series[i - 1]["actual_class"]:
                correct += 1
    pct = round(correct / total * 100, 1) if total else 0.0
    return correct, total, pct


def render_markdown(rows: list[dict]) -> str:
    generated_at = dt.datetime.now(dt.timezone.utc).isoformat()
    lines = [f"# Report accuratezza — aggiornato al {generated_at}", ""]

    correct, total, pct = _accuracy(rows)
    lines += [f"**Previsioni valutate: {total} — accuratezza complessiva: {pct}%**", ""]

    if not rows:
        lines.append("Nessuna previsione ancora valutata.")
        return "\n".join(lines) + "\n"

    lines += ["## Per asset / orizzonte", "", "| Asset | Orizzonte | N | Accuratezza |", "|---|---|---|---|"]
    grouped = defaultdict(list)
    for r in rows:
        grouped[(r["asset"], r["horizon"])].append(r)
    for (asset, horizon), sub in sorted(grouped.items()):
        _, n, sub_pct = _accuracy(sub)
        lines.append(f"| {asset} | {horizon} | {n} | {sub_pct}% |")
    lines.append("")

    lines += ["## Matrice di confusione (predetto vs reale, tutti gli asset/orizzonti)", ""]
    matrix = _confusion_matrix(rows)
    header = "| Predetto \\ Reale | " + " | ".join(CLASSES) + " |"
    lines += [header, "|---" * (len(CLASSES) + 1) + "|"]
    for pred in CLASSES:
        row = [str(matrix.get((pred, actual), 0)) for actual in CLASSES]
        lines.append(f"| {pred} | " + " | ".join(row) + " |")
    lines.append("")

    lines += ["## Calibrazione (confidence dichiarata vs accuratezza reale)", "", "| Fascia confidence | N | Accuratezza |", "|---|---|---|"]
    for label, n, cal_pct in _calibration(rows):
        lines.append(f"| {label} | {n} | {cal_pct}% |")
    lines.append("")

    lines += [
        "## Analisi Correlazione Confidence vs Successo",
        "",
        "| Fascia Confidence | N Previsioni | Corrette | Accuratezza % | Confidence Media |",
        "|---|---|---|---|---|",
    ]
    for b in analyze_confidence_buckets(rows):
        lines.append(
            f"| {b['bucket_label']} | {b['total']} | {b['correct']} | {b['accuracy_pct']}% | {b['mean_confidence']}% |"
        )
    lines.append("")

    lines += ["## Confronto con baseline naive", ""]
    lines.append(f"- Random (3 classi equiprobabili): 33.3%")
    p_correct, p_total, p_pct = _persistence_baseline(rows)
    if p_total:
        lines.append(f"- Persistenza (ripete l'ultimo esito reale osservato): {p_pct}% (n={p_total})")
    else:
        lines.append("- Persistenza: non ancora calcolabile (serve più di un esito per coppia asset/orizzonte)")
    lines.append(f"- **Agente AI: {pct}%**")
    lines.append("")

    return "\n".join(lines) + "\n"


def generate_report() -> None:
    rows = load_all_outcomes()
    with open(config.REPORT_FILE, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(rows))
