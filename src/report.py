"""Rigenera REPORT.md a partire dallo storico outcomes.jsonl: accuratezza
complessiva, per asset/orizzonte, matrice di confusione, calibrazione e
confronto con baseline naive (random, persistenza e frequenza storica)."""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from . import baseline, config, storage

CLASSES = ["UP", "DOWN", "FLAT"]
CONFIDENCE_BUCKETS = [(0, 50, "bassa (0-49)"), (50, 75, "media (50-74)"), (75, 101, "alta (75-100)")]


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
        bucket_rows = [r for r in rows if low <= r["confidence"] < high]
        _, total, pct = _accuracy(bucket_rows)
        out.append((label, total, pct))
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


def _historical_baseline(rows: list[dict], baseline_data: dict) -> tuple[int, float] | None:
    """Accuratezza attesa di chi prevedesse SEMPRE la classe storicamente più
    frequente, misurata sullo stesso mix di asset/orizzonti su cui l'agente è
    stato valutato.

    Il peso conta: se metà delle previsioni valutate sono NVDA/1d e metà
    AAPL/1m, la baseline giusta è la media pesata di quelle due, non un
    numero unico valido per tutti. Confrontare l'agente con una baseline
    calcolata su un mix diverso dal suo sarebbe un confronto truccato (in
    una direzione o nell'altra).
    """
    matched = 0
    expected = 0.0
    for r in rows:
        asset = baseline_data.get("assets", {}).get(r["asset"])
        if not asset:
            continue
        horizon = asset.get("horizons", {}).get(r["horizon"])
        if not horizon:
            continue
        matched += 1
        expected += horizon["majority_pct"]
    if not matched:
        return None
    return matched, round(expected / matched, 1)


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

    by_version: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        by_version[r.get("prompt_version", 1)].append(r)
    if len(by_version) > 1:
        lines += [
            "## Accuratezza per versione del prompt",
            "",
            "Cambiare il prompt cambia l'esperimento: un unico numero di accuratezza",
            "sopra versioni diverse nasconderebbe l'effetto del cambio. Le versioni sono",
            "descritte in `src/config.py` (`PROMPT_VERSION`).",
            "",
            "| Versione | N | Accuratezza |",
            "|---|---|---|",
        ]
        for version in sorted(by_version):
            _, v_total, v_pct = _accuracy(by_version[version])
            lines.append(f"| v{version} | {v_total} | {v_pct}% |")
        lines.append("")

    lines += ["## Confronto con baseline naive", ""]
    lines.append(f"- Random (3 classi equiprobabili): 33.3%")
    p_correct, p_total, p_pct = _persistence_baseline(rows)
    if p_total:
        lines.append(f"- Persistenza (ripete l'ultimo esito reale osservato): {p_pct}% (n={p_total})")
    else:
        lines.append("- Persistenza: non ancora calcolabile (serve più di un esito per coppia asset/orizzonte)")
    baseline_data = baseline.load()
    if baseline_data:
        historical = _historical_baseline(rows, baseline_data)
        if historical:
            n_matched, expected_pct = historical
            lines.append(
                f"- Classe più frequente (frequenza storica su decenni di prezzi, "
                f"pesata sullo stesso mix asset/orizzonte): {expected_pct}% (n={n_matched})"
            )
    lines.append(f"- **Agente AI: {pct}%**")
    lines.append("")

    if baseline_data:
        lines += [
            "> La baseline \"classe più frequente\" è la più dura delle tre: è",
            "> l'accuratezza di chi prevede sempre la stessa classe senza",
            "> guardare né prezzi né notizie. Batterla è il minimo perché",
            "> l'agente stia aggiungendo qualcosa. Dettaglio per asset e",
            "> orizzonte in `data/baseline.json` (rigenerabile con",
            "> `python -m src.baseline_run`).",
            "",
        ]

    return "\n".join(lines) + "\n"


def generate_report() -> None:
    rows = load_all_outcomes()
    with open(config.REPORT_FILE, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(rows))
