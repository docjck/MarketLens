import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from main import _compute_golden_cross


def test_golden_cross_bullish():
    # 200 prices where last 50 are higher → 50MA > 200MA
    prices = [100.0] * 150 + [120.0] * 50
    result, ma50, ma200 = _compute_golden_cross(prices)
    assert result is True
    assert ma50 > ma200


def test_golden_cross_death_cross():
    # 200 prices where last 50 are lower → 50MA < 200MA
    prices = [120.0] * 150 + [100.0] * 50
    result, ma50, ma200 = _compute_golden_cross(prices)
    assert result is False
    assert ma50 < ma200


def test_golden_cross_insufficient_data():
    prices = [100.0] * 50   # only 50 days
    result, ma50, ma200 = _compute_golden_cross(prices)
    assert result is None
    assert ma50 is None
    assert ma200 is None


def test_golden_cross_exactly_200_days_equal_prices():
    # Equal prices → ma50 == ma200 → not strictly greater → False
    prices = [100.0] * 200
    result, ma50, ma200 = _compute_golden_cross(prices)
    assert result is False
    assert ma50 == ma200


def test_screen_invalid_ticker_rejected():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    r = client.get("/screen/BAD%20TICKER")
    assert r.status_code == 400


def test_screen_response_shape():
    """Integration test — requires network. Skipped if yfinance unavailable."""
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)
    r = client.get("/screen/AAPL")
    if r.status_code == 500:
        pytest.skip("yfinance network unavailable")
    assert r.status_code == 200
    data = r.json()
    required_keys = [
        "ticker", "current_price", "short_interest_pct", "avg_volume",
        "insider_buys", "insider_sells", "insider_net",
        "golden_cross", "ma_50", "ma_200", "earnings_date", "ex_dividend_date",
    ]
    for key in required_keys:
        assert key in data, f"Missing key in /screen response: {key}"
