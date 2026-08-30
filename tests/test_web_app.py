"""Test unitari per le rotte della web dashboard (src/web_app.py)."""
import json
import pytest
from src.web_app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_index_route(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "AI Predictor" in response.get_data(as_text=True)
    assert "SPY" in response.get_data(as_text=True)
    assert "AAPL" in response.get_data(as_text=True)


def test_manifest_route(client):
    response = client.get("/manifest.json")
    assert response.status_code == 200
    data = json.loads(response.get_data(as_text=True))
    assert data["name"] == "AI Market Predictor"
    assert data["display"] == "standalone"


def test_api_evaluate_route(client):
    response = client.post("/api/evaluate")
    assert response.status_code == 200
    data = json.loads(response.get_data(as_text=True))
    assert data["status"] == "ok"
