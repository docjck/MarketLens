import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from main import _compute_pct_change, app

client = TestClient(app)


def test_normal_gain():
    assert _compute_pct_change(105.0, 100.0) == 5.0


def test_normal_loss():
    assert _compute_pct_change(95.0, 100.0) == -5.0


def test_last_price_none():
    assert _compute_pct_change(None, 100.0) is None


def test_prev_close_none():
    assert _compute_pct_change(105.0, None) is None


def test_both_none():
    assert _compute_pct_change(None, None) is None


def test_prev_close_zero():
    assert _compute_pct_change(105.0, 0) is None


def test_result_rounded_to_two_decimals():
    result = _compute_pct_change(101.005, 100.0)
    assert result == 1.0


def _mock_fast_info(last_price, previous_close):
    fi = MagicMock()
    fi.last_price = last_price
    fi.previous_close = previous_close
    return fi


def test_prices_empty_tickers():
    resp = client.get("/prices")
    assert resp.status_code == 200
    assert resp.json() == {}


def test_prices_valid_ticker():
    mock_fi = _mock_fast_info(105.0, 100.0)
    with patch("main.yf.Ticker") as mock_ticker:
        mock_ticker.return_value.fast_info = mock_fi
        resp = client.get("/prices?tickers=AAPL")
    assert resp.status_code == 200
    data = resp.json()
    assert "AAPL" in data
    assert data["AAPL"] == 5.0


def test_prices_invalid_ticker_skipped():
    resp = client.get("/prices?tickers=INVALID!!!")
    assert resp.status_code == 200
    assert resp.json() == {}


def test_prices_null_on_missing_data():
    mock_fi = _mock_fast_info(None, None)
    with patch("main.yf.Ticker") as mock_ticker:
        mock_ticker.return_value.fast_info = mock_fi
        resp = client.get("/prices?tickers=AAPL")
    assert resp.status_code == 200
    assert resp.json() == {"AAPL": None}


def test_prices_index_ticker():
    """Index tickers starting with ^ must be accepted."""
    mock_fi = _mock_fast_info(5234.18, 5191.0)
    with patch("main.yf.Ticker") as mock_ticker:
        mock_ticker.return_value.fast_info = mock_fi
        resp = client.get("/prices?tickers=^GSPC")
    assert resp.status_code == 200
    assert "^GSPC" in resp.json()


def test_prices_futures_ticker():
    """Futures tickers with = must be accepted."""
    mock_fi = _mock_fast_info(2310.0, 2300.0)
    with patch("main.yf.Ticker") as mock_ticker:
        mock_ticker.return_value.fast_info = mock_fi
        resp = client.get("/prices?tickers=GC=F")
    assert resp.status_code == 200
    assert "GC=F" in resp.json()


def test_prices_truncates_at_50():
    tickers = ",".join([f"T{i:02d}" for i in range(60)])
    mock_fi = _mock_fast_info(10.0, 10.0)
    with patch("main.yf.Ticker") as mock_ticker:
        mock_ticker.return_value.fast_info = mock_fi
        resp = client.get(f"/prices?tickers={tickers}")
    assert resp.status_code == 200
    assert len(resp.json()) == 50


def test_prices_yfinance_error_returns_null():
    with patch("main.yf.Ticker") as mock_ticker:
        mock_ticker.side_effect = Exception("network error")
        resp = client.get("/prices?tickers=AAPL")
    assert resp.status_code == 200
    assert resp.json() == {"AAPL": None}
