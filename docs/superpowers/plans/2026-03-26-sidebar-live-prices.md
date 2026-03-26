# Sidebar Live Prices Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show live % change vs previous close for every ticker in both the Markets and Watchlist sidebar panels, refreshing every 60 seconds.

**Architecture:** A new `GET /prices` endpoint in the FastAPI backend fetches `fast_info` for a batch of tickers in parallel and returns a `{ticker: pct_change}` map. The React frontend polls this endpoint every 60 seconds using a stable interval (refs for watchlist and in-flight state), then passes the prices map down to both sidebar components as a prop.

**Tech Stack:** Python (FastAPI, yfinance, concurrent.futures), React 18 (hooks: useState, useEffect, useRef)

---

## File Map

| File | Change |
|---|---|
| `stock-dashboard-backend/main.py` | Add `_compute_pct_change` helper + `GET /prices` endpoint |
| `stock-dashboard-backend/test_prices.py` | New — unit tests for `_compute_pct_change` and endpoint |
| `stock-dashboard-frontend/src/App.jsx` | Add `prices` state + polling logic; update `Markets` and `Watchlist` components and their call sites |

---

## Task 1: Backend — `_compute_pct_change` helper + tests

**Files:**
- Create: `stock-dashboard-backend/test_prices.py`
- Modify: `stock-dashboard-backend/main.py`

- [ ] **Step 1.1: Write the failing tests**

Create `stock-dashboard-backend/test_prices.py`:

```python
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from main import _compute_pct_change


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
    assert result == round((101.005 - 100.0) / 100.0 * 100, 2)
```

- [ ] **Step 1.2: Run tests — verify they fail**

```bash
cd stock-dashboard-backend
pytest test_prices.py -v
```

Expected: `ImportError` or `AttributeError` — `_compute_pct_change` doesn't exist yet.

- [ ] **Step 1.3: Add `_compute_pct_change` to `main.py`**

Add this function directly below the `_validate_ticker_param` function (after line 102):

```python
def _compute_pct_change(last_price, previous_close):
    """Return % change from previous close, or None if data is unavailable."""
    if last_price is None or previous_close is None or previous_close == 0:
        return None
    return round((last_price - previous_close) / previous_close * 100, 2)
```

- [ ] **Step 1.4: Run tests — verify they pass**

```bash
pytest test_prices.py -v
```

Expected: 7 tests PASSED.

- [ ] **Step 1.5: Commit**

```bash
git add stock-dashboard-backend/main.py stock-dashboard-backend/test_prices.py
git commit -m "feat: add _compute_pct_change helper with tests"
```

---

## Task 2: Backend — `GET /prices` endpoint + endpoint tests

**Files:**
- Modify: `stock-dashboard-backend/main.py`
- Modify: `stock-dashboard-backend/test_prices.py`

- [ ] **Step 2.1: Add import for `concurrent.futures` to `main.py`**

At the top of `main.py`, after the existing `import` block (around line 10), add:

```python
from concurrent.futures import ThreadPoolExecutor, wait as futures_wait
```

- [ ] **Step 2.2: Write the failing endpoint tests**

Append to `stock-dashboard-backend/test_prices.py`:

```python
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


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
    assert len(resp.json()) <= 50


def test_prices_yfinance_error_returns_null():
    with patch("main.yf.Ticker") as mock_ticker:
        mock_ticker.return_value.fast_info = MagicMock(side_effect=Exception("network error"))
        resp = client.get("/prices?tickers=AAPL")
    assert resp.status_code == 200
    assert resp.json() == {"AAPL": None}
```

- [ ] **Step 2.3: Run new tests — verify they fail**

```bash
pytest test_prices.py -v -k "test_prices"
```

Expected: failures because `GET /prices` doesn't exist yet (404s).

- [ ] **Step 2.4: Add `GET /prices` endpoint to `main.py`**

Add this endpoint after the `get_watchlist` / watchlist endpoints, before `get_all_timeframes` (around line 342). The `Request` parameter is required by slowapi for per-endpoint rate limiting.

```python
@app.get("/prices")
@limiter.limit("10/minute")
def get_prices(request: Request, tickers: str = ""):
    """Return % change from previous close for a batch of tickers."""
    if not tickers:
        return {}

    raw = [t.strip() for t in tickers.split(",") if t.strip()]
    valid = [t.upper() for t in raw if _TICKER_PATTERN.match(t)][:50]

    if not valid:
        return {}

    result = {}

    def fetch_one(sym):
        try:
            fi = yf.Ticker(sym).fast_info
            last = getattr(fi, "last_price", None)
            prev = getattr(fi, "previous_close", None)
            return sym, _compute_pct_change(last, prev)
        except Exception:
            return sym, None

    executor = ThreadPoolExecutor(max_workers=20)
    futures_map = {executor.submit(fetch_one, sym): sym for sym in valid}
    done, not_done = futures_wait(futures_map, timeout=8)
    executor.shutdown(wait=False)

    for f in done:
        sym, pct = f.result()
        result[sym] = pct

    for f in not_done:
        result[futures_map[f]] = None

    return result
```

- [ ] **Step 2.5: Run all backend tests — verify they pass**

```bash
pytest test_prices.py -v
```

Expected: all tests PASSED (both `_compute_pct_change` unit tests and endpoint tests).

- [ ] **Step 2.6: Commit**

```bash
git add stock-dashboard-backend/main.py stock-dashboard-backend/test_prices.py
git commit -m "feat: add GET /prices endpoint with parallel yfinance fetch"
```

---

## Task 3: Frontend — prices state and polling

**Files:**
- Modify: `stock-dashboard-frontend/src/App.jsx` (state declarations ~line 750, useEffects ~line 776)

- [ ] **Step 3.1: Add `prices` state and refs to the `App` component**

In the `App` component, locate the block of `useState` declarations (around line 765, after `loadingFundamentals`). Add:

```js
const [prices, setPrices] = useState({});
```

Then, immediately after the state declarations and before the first `useEffect` (around line 775), add the two refs:

```js
const watchlistRef = useRef(watchlist);
const isFetchingRef = useRef(false);
```

- [ ] **Step 3.2: Add the prices polling `useEffect`**

Add the following `useEffect` immediately after the existing watchlist-sync effect (the one at ~line 776 that does `localStorage.setItem`). Place it before the watchlist-from-backend effect:

```js
// Keep watchlistRef current so the polling closure always sees latest watchlist
useEffect(() => { watchlistRef.current = watchlist; }, [watchlist]);

// Fetch prices once on mount, then every 60 seconds
useEffect(() => {
  const fetchPrices = () => {
    if (isFetchingRef.current) return;
    isFetchingRef.current = true;
    const tickers = [
      ...MARKETS.flatMap(g => g.items.map(i => i.ticker)),
      ...watchlistRef.current.map(w => w.ticker),
    ].join(",");
    fetch(`${API_BASE}/prices?tickers=${tickers}`, { headers: apiHeaders() })
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) setPrices(prev => ({ ...prev, ...data })); })
      .catch(() => {})
      .finally(() => { isFetchingRef.current = false; });
  };
  fetchPrices();
  const id = setInterval(fetchPrices, 60_000);
  return () => clearInterval(id);
}, []); // stable — watchlist read via ref
```

- [ ] **Step 3.3: Smoke test — verify polling works**

Start the backend and frontend:
```bash
# Terminal 1
cd stock-dashboard-backend && uvicorn main:app --reload

# Terminal 2
cd stock-dashboard-frontend && npm run dev
```

Open browser DevTools → Network tab. Filter for `/prices`. Confirm:
- A `/prices` request fires on page load
- It returns a 200 with a JSON object of ticker → number/null
- A second request fires ~60 seconds later

- [ ] **Step 3.4: Commit**

```bash
git add stock-dashboard-frontend/src/App.jsx
git commit -m "feat: add prices state and 60s polling in App"
```

---

## Task 4: Frontend — update `Markets` component

**Files:**
- Modify: `stock-dashboard-frontend/src/App.jsx` (`Markets` component ~line 580, call site ~line 1065)

- [ ] **Step 4.1: Add `prices` prop to `Markets` and render % change**

Locate the `Markets` component (line 580). Replace it entirely with:

```jsx
function Markets({ activeTicker, onSelect, prices }) {
  return (
    <div>
      {MARKETS.map(group => (
        <div key={group.label}>
          <div style={{
            fontFamily: "'IBM Plex Mono', monospace",
            fontSize: 9,
            letterSpacing: "2.5px",
            color: "#334155",
            textTransform: "uppercase",
            margin: "12px 0 4px",
            padding: "0 4px",
          }}>
            {group.label}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {group.items.map(item => {
              const pct = prices?.[item.ticker];
              return (
                <div
                  key={item.ticker}
                  className={`watchlist-item ${activeTicker === item.ticker ? "watchlist-item-active" : ""}`}
                  onClick={() => onSelect(item.ticker)}
                >
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div className="wl-ticker">{item.ticker}</div>
                    <div className="wl-name">{item.label}</div>
                  </div>
                  <div style={{
                    fontFamily: "'IBM Plex Mono', monospace",
                    fontSize: 11,
                    fontWeight: 600,
                    paddingLeft: 8,
                    flexShrink: 0,
                    color: pct == null ? "#1e293b" : pct >= 0 ? "#00ff88" : "#ef4444",
                  }}>
                    {pct == null ? "—" : `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
      <div style={{ borderBottom: "1px solid rgba(255,255,255,0.05)", marginBottom: 12, paddingBottom: 12, marginTop: 8 }} />
    </div>
  );
}
```

- [ ] **Step 4.2: Pass `prices` to `Markets` at the call site**

Find the `Markets` call (line ~1065):
```jsx
<Markets activeTicker={ticker} onSelect={handleWatchlistSelect} />
```

Replace with:
```jsx
<Markets activeTicker={ticker} onSelect={handleWatchlistSelect} prices={prices} />
```

- [ ] **Step 4.3: Verify visually**

With the dev server running, open the app. The Markets sidebar should show `—` for each item briefly, then populate with colored % values once the first `/prices` response arrives (~1-2s).

- [ ] **Step 4.4: Commit**

```bash
git add stock-dashboard-frontend/src/App.jsx
git commit -m "feat: show live % change in Markets sidebar"
```

---

## Task 5: Frontend — update `Watchlist` component

**Files:**
- Modify: `stock-dashboard-frontend/src/App.jsx` (`Watchlist` component ~line 619, call site ~line 1067)

- [ ] **Step 5.1: Add `prices` prop to `Watchlist` and render % change**

Locate the `Watchlist` component (line 619). Replace it entirely with:

```jsx
function Watchlist({ watchlist, activeTicker, onSelect, onRemove, prices }) {
  if (!watchlist.length) return (
    <div className="watchlist-empty">
      <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: "#1e293b", letterSpacing: 1.5 }}>
        WATCHLIST EMPTY
      </span>
    </div>
  );
  return (
    <div className="watchlist">
      {watchlist.map(item => {
        const pct = prices?.[item.ticker];
        return (
          <div key={item.ticker}
            className={`watchlist-item ${activeTicker === item.ticker ? "watchlist-item-active" : ""}`}
            onClick={() => onSelect(item.ticker)}
          >
            <div style={{ minWidth: 0, flex: 1 }}>
              <div className="wl-ticker">{item.ticker}</div>
              <div className="wl-name">{item.name}</div>
            </div>
            <div style={{
              fontFamily: "'IBM Plex Mono', monospace",
              fontSize: 11,
              fontWeight: 600,
              paddingLeft: 8,
              flexShrink: 0,
              color: pct == null ? "#1e293b" : pct >= 0 ? "#00ff88" : "#ef4444",
            }}>
              {pct == null ? "—" : `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`}
            </div>
            <button className="wl-remove" onClick={e => { e.stopPropagation(); onRemove(item.ticker); }} title="Remove">✕</button>
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 5.2: Pass `prices` to `Watchlist` at the call site**

Find the `Watchlist` call (lines ~1067-1072):
```jsx
<Watchlist
  watchlist={watchlist}
  activeTicker={ticker}
  onSelect={handleWatchlistSelect}
  onRemove={handleRemoveFromWatchlist}
/>
```

Replace with:
```jsx
<Watchlist
  watchlist={watchlist}
  activeTicker={ticker}
  onSelect={handleWatchlistSelect}
  onRemove={handleRemoveFromWatchlist}
  prices={prices}
/>
```

- [ ] **Step 5.3: Verify visually**

With the dev server running, add a few tickers to the watchlist. Confirm:
- Each watchlist item shows `—` until prices load, then a colored % value
- The remove button (✕) is still present on the far right
- Adding a new ticker shows `—` initially, then picks up a price on the next 60s tick

- [ ] **Step 5.4: Run backend tests one final time**

```bash
cd stock-dashboard-backend && pytest test_prices.py -v
```

Expected: all tests PASSED.

- [ ] **Step 5.5: Final commit**

```bash
git add stock-dashboard-frontend/src/App.jsx
git commit -m "feat: show live % change in Watchlist sidebar"
```
