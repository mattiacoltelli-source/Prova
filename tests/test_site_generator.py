"""Test per la generazione dei dati della PWA dashboard."""
import json
import os
from src import build_site


def test_build_data_structure():
    data = build_site.build_data()
    assert "global_accuracy_pct" in data
    assert "total_evaluated" in data
    assert "total_pending" in data
    assert "assets" in data
    assert "SPY" in data["assets"]
    assert "AAPL" in data["assets"]

    spy = data["assets"]["SPY"]
    assert "accuracy_pct" in spy
    assert "total_evaluated" in spy
    assert "evaluated" in spy
    assert "predictions" in spy
    assert "chart_points" in spy


def test_manifest_and_pwa_files_exist():
    assert os.path.exists("index.html")
    assert os.path.exists("manifest.json")
    assert os.path.exists("sw.js")
    assert os.path.exists("app.js")
    assert os.path.exists("style.css")

    with open("manifest.json", "r", encoding="utf-8") as f:
        manifest = json.load(f)
        assert manifest["display"] == "standalone"
        assert manifest["name"] == "AI Predictor"
