"""Test unitari per le rotte della web dashboard (src/web_app.py)."""
import json
import pytest
from src import config
from src.web_app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_index_route(client):
    response = client.get("/")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "AI Predictor" in text
    assert "NVDA" in text
    assert "MSFT" in text
    assert "AAPL" in text


def test_manifest_route(client):
    response = client.get("/manifest.json")
    assert response.status_code == 200
    data = json.loads(response.get_data(as_text=True))
    assert data["name"] == "AI Market Predictor"
    assert data["display"] == "standalone"


def test_api_evaluate_route(client, tmp_path, monkeypatch):
    # Isola la route dai dati reali del repo e dalla rete: senza questo,
    # evaluate_run.run(dry_run=False) scriverebbe davvero su data/ e
    # chiamerebbe API di prezzo live ad ogni esecuzione della test suite.
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "PENDING_FILE", str(tmp_path / "pending.json"))
    monkeypatch.setattr(config, "REPORT_FILE", str(tmp_path / "REPORT.md"))

    response = client.post("/api/evaluate")
    assert response.status_code == 200
    data = json.loads(response.get_data(as_text=True))
    assert data["status"] == "ok"
