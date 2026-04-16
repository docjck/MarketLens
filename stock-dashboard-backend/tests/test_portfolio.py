import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_portfolio_initially_empty():
    r = client.get("/portfolio")
    assert r.status_code == 200
    assert r.json() == {"items": []}


def test_add_to_portfolio():
    r = client.post("/portfolio", json={"ticker": "AAPL", "name": "Apple Inc."})
    assert r.status_code == 201
    data = r.json()
    assert data["ticker"] == "AAPL"
    assert data["name"] == "Apple Inc."


def test_portfolio_contains_added_item():
    r = client.get("/portfolio")
    items = r.json()["items"]
    assert any(i["ticker"] == "AAPL" for i in items)


def test_duplicate_add_is_idempotent():
    client.post("/portfolio", json={"ticker": "AAPL", "name": "Apple Inc."})
    r = client.get("/portfolio")
    assert len([i for i in r.json()["items"] if i["ticker"] == "AAPL"]) == 1


def test_remove_from_portfolio():
    client.post("/portfolio", json={"ticker": "MSFT", "name": "Microsoft Corp."})
    r = client.delete("/portfolio/MSFT")
    assert r.status_code == 200
    assert r.json()["removed"] == "MSFT"
    r2 = client.get("/portfolio")
    assert all(i["ticker"] != "MSFT" for i in r2.json()["items"])


def test_add_invalid_ticker_rejected():
    r = client.post("/portfolio", json={"ticker": "BAD TICKER!", "name": "Test"})
    assert r.status_code == 422


def test_add_too_long_name_rejected():
    r = client.post("/portfolio", json={"ticker": "TST", "name": "x" * 201})
    assert r.status_code == 422
