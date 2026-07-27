"""
smoke_ticker.py — health smoke test for MarketLens's yfinance data path.

Run:  python -m tests.smoke_ticker   (from the MarketLens repo root)

Exercises the app's own fetch_stock_data() for a known liquid ticker and
asserts it returns real OHLCV bars. Exits 0 on success, 1 on failure — so the
project health registry's `yfinance-smoke` check can detect yfinance breakage
(the API changes often) or breakage in the app's own fetch code.
"""

import os
import sys

_TICKER = "AAPL"
_PERIOD = "5d"
_INTERVAL = "1d"
_REQUIRED_KEYS = {"date", "open", "high", "low", "close", "volume"}

# The backend dir name has a hyphen, so it cannot be a normal package import.
# Put it on sys.path (resolved relative to this file, not the cwd) so we can
# import the app's real fetch function.
_BACKEND = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "stock-dashboard-backend",
)
sys.path.insert(0, _BACKEND)


def main() -> int:
    try:
        from main import fetch_stock_data
    except Exception as exc:
        print(f"[smoke] FAIL: could not import fetch_stock_data: {exc}")
        return 1

    try:
        bars = fetch_stock_data(_TICKER, _PERIOD, _INTERVAL)
    except Exception as exc:
        print(f"[smoke] FAIL: fetch_stock_data raised: {exc}")
        return 1

    if not bars:
        print(f"[smoke] FAIL: no bars returned for {_TICKER} ({_PERIOD}/{_INTERVAL})")
        return 1

    missing = _REQUIRED_KEYS - set(bars[0].keys())
    if missing:
        print(f"[smoke] FAIL: first bar missing keys {sorted(missing)}")
        return 1

    print(f"[smoke] OK: {_TICKER} returned {len(bars)} bars with OHLCV keys")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
