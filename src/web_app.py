"""Web Application (Flask) per la visualizzazione e gestione della dashboard.
Supporta installazione come PWA su Android, visualizzazione di predizioni,
storico, grafici Reali vs Previsti e % di accuratezza per SPY e AAPL insieme.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

from flask import Flask, jsonify, render_template_string, request

# Aggiungi cartella radice al path per import di src
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config, evaluate_run, predict_run, report, storage

app = Flask(__name__)


def get_dashboard_data() -> dict[str, Any]:
    """Raccoglie predizioni, outcomes, metriche di accuratezza e serie temporali per la dashboard."""
    all_outcomes = report.load_all_outcomes()

    # Metriche generali
    total_outcomes = len(all_outcomes)
    correct_outcomes = sum(1 for o in all_outcomes if o.get("correct"))
    overall_accuracy = round(correct_outcomes / total_outcomes * 100, 1) if total_outcomes > 0 else 0.0

    # Metriche e serie per asset
    assets_data = {}
    for asset in config.ASSETS:
        preds = storage.read_all(config.predictions_file(asset))
        outs = storage.read_all(config.outcomes_file(asset))

        asset_total = len(outs)
        asset_correct = sum(1 for o in outs if o.get("correct"))
        asset_accuracy = round(asset_correct / asset_total * 100, 1) if asset_total > 0 else 0.0

        # Mappa predizioni per ID per lookup veloce nei grafici
        preds_map = {p["id"]: p for p in preds}

        # Serie Reale vs Previsto per i grafici
        # Combiniamo gli outcomes per vedere la data target, prezzo di partenza, prezzo target reale, classe prevista e reale
        chart_points = []
        for o in sorted(outs, key=lambda x: x.get("evaluated_at", "")):
            p_id = o.get("prediction_id")
            p_info = preds_map.get(p_id, {})
            chart_points.append({
                "date": o.get("target_bar_date") or o.get("evaluated_at", "")[:10],
                "price_start": p_info.get("price_at_generation"),
                "price_target": o.get("price_at_target"),
                "actual_change_pct": o.get("actual_change_pct"),
                "predicted_class": o.get("predicted_class"),
                "actual_class": o.get("actual_class"),
                "correct": o.get("correct", False),
                "horizon": o.get("horizon")
            })

        assets_data[asset] = {
            "accuracy": asset_accuracy,
            "total_evals": asset_total,
            "correct_evals": asset_correct,
            "recent_predictions": sorted(preds, key=lambda x: x.get("generated_at", ""), reverse=True)[:10],
            "recent_outcomes": sorted(outs, key=lambda x: x.get("evaluated_at", ""), reverse=True)[:10],
            "chart_points": chart_points
        }

    pending = storage.load_pending()

    return {
        "overall_accuracy": overall_accuracy,
        "total_outcomes": total_outcomes,
        "correct_outcomes": correct_outcomes,
        "assets_data": assets_data,
        "pending_count": len(pending),
        "pending_list": pending
    }


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Market Predictor Dashboard</title>
    <link rel="manifest" href="/manifest.json">
    <meta name="theme-color" content="#121826">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --card-border: #334155;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --accent-green: #10b981;
            --accent-red: #ef4444;
            --accent-yellow: #f59e0b;
            --accent-blue: #3b82f6;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }

        body {
            background-color: var(--bg-color);
            color: var(--text-main);
            padding: 16px;
            padding-bottom: 80px;
        }

        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 12px;
            border-bottom: 1px solid var(--card-border);
        }

        h1 {
            font-size: 1.4rem;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .refresh-btn {
            background: var(--accent-blue);
            color: white;
            border: none;
            padding: 8px 14px;
            border-radius: 8px;
            font-size: 0.9rem;
            font-weight: 600;
            cursor: pointer;
        }

        .summary-banner {
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 20px;
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 12px;
            text-align: center;
        }

        .stat-box {
            display: flex;
            flex-direction: column;
        }

        .stat-label {
            font-size: 0.75rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .stat-value {
            font-size: 1.4rem;
            font-weight: 700;
            margin-top: 4px;
        }

        .stat-value.green { color: var(--accent-green); }
        .stat-value.blue { color: var(--accent-blue); }

        .actions-panel {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin-bottom: 24px;
        }

        .btn-action {
            background-color: var(--card-bg);
            border: 1px solid var(--card-border);
            color: var(--text-main);
            padding: 12px;
            border-radius: 10px;
            font-size: 0.9rem;
            font-weight: 600;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            transition: background-color 0.2s;
        }

        .btn-action:active {
            background-color: var(--card-border);
        }

        .grid-two-assets {
            display: grid;
            grid-template-columns: 1fr;
            gap: 20px;
        }

        @media (min-width: 768px) {
            .grid-two-assets {
                grid-template-columns: 1fr 1fr;
            }
        }

        .asset-card {
            background-color: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 14px;
            padding: 16px;
        }

        .asset-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }

        .asset-title {
            font-size: 1.2rem;
            font-weight: 700;
        }

        .badge-accuracy {
            background-color: rgba(16, 185, 129, 0.15);
            color: var(--accent-green);
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 0.85rem;
            font-weight: 700;
        }

        .chart-container {
            position: relative;
            height: 200px;
            margin-bottom: 16px;
        }

        .section-title {
            font-size: 0.95rem;
            font-weight: 600;
            margin-bottom: 10px;
            color: var(--text-muted);
            border-bottom: 1px solid var(--card-border);
            padding-bottom: 4px;
        }

        .table-wrapper {
            overflow-x: auto;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.82rem;
        }

        th, td {
            padding: 8px 6px;
            text-align: left;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        }

        th {
            color: var(--text-muted);
            font-weight: 600;
        }

        .badge {
            padding: 2px 6px;
            border-radius: 4px;
            font-weight: 700;
            font-size: 0.75rem;
            display: inline-block;
        }

        .badge-UP { background-color: rgba(16, 185, 129, 0.2); color: var(--accent-green); }
        .badge-DOWN { background-color: rgba(239, 68, 68, 0.2); color: var(--accent-red); }
        .badge-FLAT { background-color: rgba(245, 158, 11, 0.2); color: var(--accent-yellow); }

        .correct-true { color: var(--accent-green); font-weight: bold; }
        .correct-false { color: var(--accent-red); font-weight: bold; }

        .toast {
            position: fixed;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            background-color: var(--accent-blue);
            color: white;
            padding: 10px 20px;
            border-radius: 30px;
            font-size: 0.9rem;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            display: none;
            z-index: 1000;
        }
    </style>
</head>
<body>

    <header>
        <h1>📈 AI Predictor</h1>
        <button class="refresh-btn" onclick="location.reload()">🔄 Aggiorna</button>
    </header>

    <div class="summary-banner">
        <div class="stat-box">
            <span class="stat-label">Accuratezza AI</span>
            <span class="stat-value green">{{ data.overall_accuracy }}%</span>
        </div>
        <div class="stat-box">
            <span class="stat-label">Valutati</span>
            <span class="stat-value">{{ data.total_outcomes }}</span>
        </div>
        <div class="stat-box">
            <span class="stat-label">In Attesa</span>
            <span class="stat-value blue">{{ data.pending_count }}</span>
        </div>
    </div>

    <div class="actions-panel">
        <button class="btn-action" onclick="runAction('/api/predict')">
            ⚡ Nuova Predizione
        </button>
        <button class="btn-action" onclick="runAction('/api/evaluate')">
            🎯 Valuta Risultati
        </button>
    </div>

    <div class="grid-two-assets">
        {% for asset in ['SPY', 'AAPL'] %}
        {% set a_data = data.assets_data[asset] %}
        <div class="asset-card">
            <div class="asset-header">
                <span class="asset-title">{{ asset }}</span>
                <span class="badge-accuracy">Accuratezza: {{ a_data.accuracy }}%</span>
            </div>

            <div class="chart-container">
                <canvas id="chart-{{ asset }}"></canvas>
            </div>

            <div class="section-title">Ultimi Risultati Valutati</div>
            <div class="table-wrapper">
                <table>
                    <thead>
                        <tr>
                            <th>Data</th>
                            <th>Orizzonte</th>
                            <th>Preditto</th>
                            <th>Reale</th>
                            <th>Esito</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% if a_data.recent_outcomes %}
                            {% for row in a_data.recent_outcomes %}
                            <tr>
                                <td>{{ row.evaluated_at[:10] }}</td>
                                <td>{{ row.horizon }}</td>
                                <td><span class="badge badge-{{ row.predicted_class }}">{{ row.predicted_class }}</span></td>
                                <td><span class="badge badge-{{ row.actual_class }}">{{ row.actual_class }}</span></td>
                                <td class="correct-{{ row.correct }}">{{ '✅ SI' if row.correct else '❌ NO' }}</td>
                            </tr>
                            {% endfor %}
                        {% else %}
                            <tr><td colspan="5" style="text-align:center; color: var(--text-muted);">Nessuna valutazione ancora.</td></tr>
                        {% endif %}
                    </tbody>
                </table>
            </div>

            <div class="section-title" style="margin-top: 16px;">Ultimi Segnali Generati</div>
            <div class="table-wrapper">
                <table>
                    <thead>
                        <tr>
                            <th>Data</th>
                            <th>Orizzonte</th>
                            <th>Classe</th>
                            <th>Conf.</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% if a_data.recent_predictions %}
                            {% for p in a_data.recent_predictions %}
                            <tr>
                                <td>{{ p.generated_at[:10] }}</td>
                                <td>{{ p.horizon }}</td>
                                <td><span class="badge badge-{{ p.predicted_class }}">{{ p.predicted_class }}</span></td>
                                <td>{{ p.confidence }}%</td>
                            </tr>
                            {% endfor %}
                        {% else %}
                            <tr><td colspan="4" style="text-align:center; color: var(--text-muted);">Nessuna predizione registrata.</td></tr>
                        {% endif %}
                    </tbody>
                </table>
            </div>
        </div>
        {% endfor %}
    </div>

    <div id="toast" class="toast">Elaborazione in corso...</div>

    <script>
        function showToast(msg) {
            const toast = document.getElementById('toast');
            toast.innerText = msg;
            toast.style.display = 'block';
            setTimeout(() => { toast.style.display = 'none'; }, 3000);
        }

        async function runAction(url) {
            showToast('Esecuzione in corso...');
            try {
                const res = await fetch(url, { method: 'POST' });
                const json = await res.json();
                if (json.status === 'ok') {
                    showToast('Completato con successo!');
                    setTimeout(() => location.reload(), 1500);
                } else {
                    showToast('Errore: ' + json.message);
                }
            } catch (err) {
                showToast('Errore di connessione');
            }
        }

        // Render Grafici Reale vs Previsto
        const rawData = {{ data|tojson }};

        ['SPY', 'AAPL'].forEach(asset => {
            const points = rawData.assets_data[asset].chart_points;
            const labels = points.map(p => p.date);
            const priceStart = points.map(p => p.price_start);
            const priceTarget = points.map(p => p.price_target);

            const ctx = document.getElementById(`chart-${asset}`).getContext('2d');
            new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels.length ? labels : ['Nessun dato'],
                    datasets: [
                        {
                            label: 'Prezzo Iniziale',
                            data: priceStart.length ? priceStart : [0],
                            borderColor: '#3b82f6',
                            borderDash: [5, 5],
                            tension: 0.1
                        },
                        {
                            label: 'Prezzo Target Reale',
                            data: priceTarget.length ? priceTarget : [0],
                            borderColor: '#10b981',
                            backgroundColor: 'rgba(16, 185, 129, 0.1)',
                            fill: true,
                            tension: 0.1
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { labels: { color: '#94a3b8', font: { size: 10 } } }
                    },
                    scales: {
                        x: { ticks: { color: '#94a3b8', font: { size: 9 } }, grid: { color: 'rgba(255,255,255,0.05)' } },
                        y: { ticks: { color: '#94a3b8', font: { size: 9 } }, grid: { color: 'rgba(255,255,255,0.05)' } }
                    }
                }
            });
        });
    </script>
</body>
</html>
"""


@app.route("/")
@app.route("/index.html")
def index():
    # Se esiste index.html nella radice, serviamolo per coerenza con GitHub Pages
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    index_path = os.path.join(root_dir, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    data = get_dashboard_data()
    return render_template_string(HTML_TEMPLATE, data=data)


@app.route("/manifest.json")
def manifest():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    manifest_path = os.path.join(root_dir, "manifest.json")
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            return app.response_class(f.read(), mimetype="application/json")
    return jsonify({
        "name": "AI Market Predictor",
        "short_name": "Predictor",
        "start_url": "./index.html",
        "display": "standalone",
        "background_color": "#0f172a",
        "theme_color": "#121826",
        "icons": [
            {
                "src": "https://img.icons8.com/color/192/line-chart.png",
                "sizes": "192x192",
                "type": "image/png"
            }
        ]
    })


@app.route("/sw.js")
def service_worker():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sw_path = os.path.join(root_dir, "sw.js")
    if os.path.exists(sw_path):
        with open(sw_path, "r", encoding="utf-8") as f:
            return app.response_class(f.read(), mimetype="application/javascript")
    return "", 404


@app.route("/data/<path:filename>")
def serve_data_files(filename):
    from flask import send_from_directory
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(root_dir, "data")
    return send_from_directory(data_dir, filename)


@app.route("/api/predict", methods=["POST"])
def api_predict():
    try:
        predict_run.run(dry_run=False, force=True)
        return jsonify({"status": "ok", "message": "Predizioni generate con successo!"})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.route("/api/evaluate", methods=["POST"])
def api_evaluate():
    try:
        evaluate_run.run(dry_run=False)
        return jsonify({"status": "ok", "message": "Valutazione completata con successo!"})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"status": "error", "message": str(exc)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
