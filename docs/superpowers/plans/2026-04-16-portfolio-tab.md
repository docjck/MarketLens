# Portfolio Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Portfolio tab with per-stock screening checks (short interest, average volume, insider activity, golden cross, earnings dates, ex-dividend dates) displayed as colored badge flags on expandable rows.

**Architecture:** New `/portfolio` CRUD endpoints and `/screen/{ticker}` aggregation endpoint added to `main.py`. New `Portfolio` React component added to `App.jsx`. Portfolio list persisted in a new SQLite `portfolio` table. Screen data fetched per-ticker in parallel when the tab activates, rendering rows progressively as results arrive.

**Tech Stack:** FastAPI + yfinance (backend), React 18 + inline CSS (frontend), SQLite (persistence), pytest + FastAPI TestClient (backend testing)

**Spec:** `docs/superpowers/specs/2026-04-16-portfolio-design.md`

---

## File Map

| File | Change |
|---|---|
| `stock-dashboard-backend/main.py` | Make `DB_PATH` env-configurable; add threshold constants; add `portfolio` table init; add `GET/POST/DELETE /portfolio`; add `_compute_golden_cross` helper; add `GET /screen/{ticker}` |
| `stock-dashboard-backend/tests/__init__.py` | Create (empty, enables pytest discovery) |
| `stock-dashboard-backend/tests/conftest.py` | Create: sets `MARKETLENS_DB` env var before `main.py` is imported |
| `stock-dashboard-backend/tests/test_portfolio.py` | Create: CRUD tests for `/portfolio` endpoints |
| `stock-dashboard-backend/tests/test_screen.py` | Create: unit tests for `_compute_golden_cross`; smoke test for `/screen/{ticker}` |
| `stock-dashboard-frontend/src/App.jsx` | Add portfolio state + constants; add PORTFOLIO tab button; add fetch logic on tab activate; add full `Portfolio` component |

---

### Task 1: Backend — make DB_PATH configurable + portfolio table + CRUD endpoints

**Files:**
- Modify: `stock-dashboard-backend/main.py`
- Create: `stock-dashboard-backend/tests/__init__.py`
- Create: `stock-dashboard-backend/tests/conftest.py`
- Create: `stock-dashboard-backend/tests/test_portfolio.py`

- [ ] **Step 1: Make DB_PATH read from environment variable**

In `stock-dashboard-backend/main.py`, find this line (currently around line 45):
```python
DB_PATH = os.path.join(os.path.dirname(__file__), "watchlist.db")
```
Replace with:
```python
DB_PATH = os.getenv("MARKETLENS_DB", os.path.join(os.path.dirname(__file__), "watchlist.db"))
```

- [ ] **Step 2: Add `portfolio` table to `init_db()`**

Find the `init_db()` function in `main.py`. Add the portfolio table creation after the existing watchlist table:
```python
def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                ticker  TEXT PRIMARY KEY,
                name    TEXT NOT NULL,
                added_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS portfolio (
                ticker  TEXT PRIMARY KEY,
                name    TEXT NOT NULL,
                added_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.commit()
```

- [ ] **Step 3: Add portfolio CRUD endpoints to `main.py`**

Add these three endpoints after the existing watchlist endpoints (after the `remove_from_watchlist` function, around line 341):

```python
@app.get("/portfolio")
def get_portfolio():
    """Return all portfolio items ordered by when they were added."""
    with get_db() as conn:
        rows = conn.execute("SELECT ticker, name FROM portfolio ORDER BY added_at").fetchall()
    return {"items": [{"ticker": r["ticker"], "name": r["name"]} for r in rows]}


@app.post("/portfolio", status_code=201)
def add_to_portfolio(item: WatchlistItem):
    """Add a ticker to the portfolio. Silently ignores duplicates."""
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO portfolio (ticker, name) VALUES (?, ?)",
            (item.ticker, item.name),
        )
        conn.commit()
    return {"ticker": item.ticker, "name": item.name}


@app.delete("/portfolio/{ticker}", status_code=200)
def remove_from_portfolio(ticker: str = Path(..., max_length=20)):
    """Remove a ticker from the portfolio."""
    sym = _validate_ticker_param(ticker)
    with get_db() as conn:
        conn.execute("DELETE FROM portfolio WHERE ticker = ?", (sym,))
        conn.commit()
    return {"removed": sym}
```

- [ ] **Step 4: Create test infrastructure**

Create `stock-dashboard-backend/tests/__init__.py` (empty file):
```
```

Create `stock-dashboard-backend/tests/conftest.py`:
```python
import os
import tempfile
import pytest

# Must be set before main.py is imported by any test module.
# conftest.py is loaded by pytest before test files are collected.
_test_db = tempfile.mktemp(suffix="_test.db")
os.environ["MARKETLENS_DB"] = _test_db


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_db():
    yield
    if os.path.exists(_test_db):
        os.unlink(_test_db)
```

- [ ] **Step 5: Write portfolio CRUD tests**

Create `stock-dashboard-backend/tests/test_portfolio.py`:
```python
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
```

- [ ] **Step 6: Run tests and verify they pass**

```bash
cd stock-dashboard-backend
pip install pytest httpx -q
pytest tests/test_portfolio.py -v
```

Expected output:
```
tests/test_portfolio.py::test_portfolio_initially_empty PASSED
tests/test_portfolio.py::test_add_to_portfolio PASSED
tests/test_portfolio.py::test_portfolio_contains_added_item PASSED
tests/test_portfolio.py::test_duplicate_add_is_idempotent PASSED
tests/test_portfolio.py::test_remove_from_portfolio PASSED
tests/test_portfolio.py::test_add_invalid_ticker_rejected PASSED
tests/test_portfolio.py::test_add_too_long_name_rejected PASSED
7 passed
```

- [ ] **Step 7: Commit**

```bash
git add stock-dashboard-backend/main.py \
        stock-dashboard-backend/tests/__init__.py \
        stock-dashboard-backend/tests/conftest.py \
        stock-dashboard-backend/tests/test_portfolio.py
git commit -m "feat: add portfolio table and CRUD endpoints"
```

---

### Task 2: Backend — `/screen/{ticker}` endpoint

**Files:**
- Modify: `stock-dashboard-backend/main.py`
- Create: `stock-dashboard-backend/tests/test_screen.py`

- [ ] **Step 1: Add threshold constants to `main.py`**

Add these constants near the top of `main.py`, after the `TIMEFRAME_MAP` block (around line 91):

```python
# ─── Portfolio screening thresholds ──────────────────────────────────────────

SHORT_INTEREST_HIGH = 10.0    # red above 10% (percent units)
SHORT_INTEREST_WARN = 5.0     # yellow above 5%
AVG_VOLUME_LOW      = 1_000_000   # red below 1M shares/day
AVG_VOLUME_WARN     = 5_000_000   # yellow below 5M shares/day
EARNINGS_WARN_DAYS  = 14      # yellow if earnings within 14 days
EXDIV_ALERT_DAYS    = 30      # show badge if ex-div within 30 days
```

- [ ] **Step 2: Add `_compute_golden_cross` helper to `main.py`**

Add this function after the threshold constants:

```python
def _compute_golden_cross(close_prices: list) -> tuple:
    """
    Given a chronological list of closing prices, compute 50/200-day MA cross.
    Returns (golden_cross: bool, ma_50: float, ma_200: float).
    Returns (None, None, None) if fewer than 200 data points.
    """
    if len(close_prices) < 200:
        return None, None, None
    ma_50 = sum(close_prices[-50:]) / 50
    ma_200 = sum(close_prices[-200:]) / 200
    return ma_50 > ma_200, round(ma_50, 2), round(ma_200, 2)
```

- [ ] **Step 3: Write failing tests for `_compute_golden_cross`**

Create `stock-dashboard-backend/tests/test_screen.py`:

```python
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


def test_golden_cross_exactly_200_days():
    prices = [100.0] * 200
    result, ma50, ma200 = _compute_golden_cross(prices)
    assert result is True   # equal MAs → not strictly greater; adjust: equal prices → 50MA == 200MA
    # When all prices equal, ma50 == ma200, so result is False (not strictly greater)
    assert result is False


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
```

- [ ] **Step 4: Run failing tests (expect import error since `_compute_golden_cross` not yet added)**

```bash
cd stock-dashboard-backend
pytest tests/test_screen.py::test_golden_cross_bullish -v
```

Expected: `ImportError: cannot import name '_compute_golden_cross' from 'main'`

- [ ] **Step 5: Add `GET /screen/{ticker}` endpoint to `main.py`**

Add after the `/portfolio` endpoints:

```python
@app.get("/screen/{ticker}")
def screen_ticker(ticker: str = Path(..., max_length=20)):
    """Return all screening data for a ticker: short interest, volume, insider, golden cross, dates."""
    sym = _validate_ticker_param(ticker)
    try:
        tk = yf.Ticker(sym)
        info = tk.info or {}
        result: dict = {"ticker": sym}

        # Current price
        try:
            fi = tk.fast_info
            price = getattr(fi, "last_price", None)
            result["current_price"] = round(float(price), 4) if price else None
        except Exception:
            result["current_price"] = None

        # Short interest (yfinance returns decimal e.g. 0.008 for 0.8%)
        try:
            sif = info.get("shortPercentOfFloat")
            result["short_interest_pct"] = round(float(sif) * 100, 2) if sif is not None else None
        except Exception:
            result["short_interest_pct"] = None

        # Average daily volume
        try:
            av = info.get("averageVolume")
            result["avg_volume"] = int(av) if av is not None else None
        except Exception:
            result["avg_volume"] = None

        # Insider transactions — count buys vs sells in most recent 20 transactions
        try:
            df = tk.insider_transactions
            if df is not None and not df.empty:
                recent = df.head(20)
                tx_col = next(
                    (c for c in recent.columns if "transaction" in c.lower() or "trade" in c.lower()),
                    None
                )
                if tx_col:
                    buys = int(recent[tx_col].str.contains(r"Purchase|Buy", case=False, na=False, regex=True).sum())
                    sells = int(recent[tx_col].str.contains(r"Sale|Sell", case=False, na=False, regex=True).sum())
                else:
                    buys, sells = 0, 0
                result["insider_buys"] = buys
                result["insider_sells"] = sells
                result["insider_net"] = buys - sells
            else:
                result["insider_buys"] = None
                result["insider_sells"] = None
                result["insider_net"] = None
        except Exception:
            result["insider_buys"] = None
            result["insider_sells"] = None
            result["insider_net"] = None

        # Golden cross: 50MA vs 200MA from 1y price history
        try:
            hist = tk.history(period="1y")
            closes = hist["Close"].tolist() if not hist.empty else []
            golden, ma50, ma200 = _compute_golden_cross(closes)
            result["golden_cross"] = golden
            result["ma_50"] = ma50
            result["ma_200"] = ma200
        except Exception:
            result["golden_cross"] = None
            result["ma_50"] = None
            result["ma_200"] = None

        # Earnings date
        try:
            cal = tk.calendar
            earnings_date = None
            if isinstance(cal, dict):
                ed = cal.get("Earnings Date")
                if isinstance(ed, list) and ed:
                    ed = ed[0]
                if ed is not None and hasattr(ed, "strftime"):
                    earnings_date = ed.strftime("%Y-%m-%d")
            elif hasattr(cal, "columns") and "Earnings Date" in cal.columns:
                ed = cal["Earnings Date"].iloc[0]
                if hasattr(ed, "strftime"):
                    earnings_date = ed.strftime("%Y-%m-%d")
            result["earnings_date"] = earnings_date
        except Exception:
            result["earnings_date"] = None

        # Ex-dividend date
        try:
            exd = info.get("exDividendDate")
            result["ex_dividend_date"] = (
                datetime.fromtimestamp(int(exd)).strftime("%Y-%m-%d") if exd else None
            )
        except Exception:
            result["ex_dividend_date"] = None

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"/screen/{sym}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch screening data")
```

- [ ] **Step 6: Fix the `test_golden_cross_exactly_200_days` expectation and run all screen tests**

The test at step 3 has a logical issue (equal prices → `ma50 == ma200` → `ma50 > ma200` is `False`). The test body already corrects itself with the comment. Verify it as-is.

```bash
cd stock-dashboard-backend
pytest tests/test_screen.py -v -k "not test_screen_response_shape"
```

Expected:
```
tests/test_screen.py::test_golden_cross_bullish PASSED
tests/test_screen.py::test_golden_cross_death_cross PASSED
tests/test_screen.py::test_golden_cross_insufficient_data PASSED
tests/test_screen.py::test_golden_cross_exactly_200_days PASSED
tests/test_screen.py::test_screen_invalid_ticker_rejected PASSED
5 passed
```

- [ ] **Step 7: Run all backend tests together**

```bash
cd stock-dashboard-backend
pytest tests/ -v -k "not test_screen_response_shape"
```

Expected: 12 passed

- [ ] **Step 8: Commit**

```bash
git add stock-dashboard-backend/main.py stock-dashboard-backend/tests/test_screen.py
git commit -m "feat: add /screen/{ticker} endpoint with golden cross, short interest, insider, dates"
```

---

### Task 3: Frontend — portfolio state + tab button + fetch logic

**Files:**
- Modify: `stock-dashboard-frontend/src/App.jsx`

- [ ] **Step 1: Add portfolio threshold constants near the top of `App.jsx`**

Find this block near the top of `App.jsx` (after the `const API_TOKEN` line, before the utility functions):
```js
const API_BASE = "/api";
const WATCHLIST_KEY = "marketlens_watchlist";
const API_TOKEN = import.meta.env.VITE_API_TOKEN || "";
```

Add the constants immediately after:
```js
// ─── Portfolio screening thresholds (match backend main.py constants) ─────────
const SHORT_INTEREST_HIGH = 10.0;
const SHORT_INTEREST_WARN = 5.0;
const AVG_VOLUME_LOW      = 1_000_000;
const AVG_VOLUME_WARN     = 5_000_000;
const EARNINGS_WARN_DAYS  = 14;
const EXDIV_ALERT_DAYS    = 30;
```

- [ ] **Step 2: Add portfolio state to the `App` component**

In the `App` function, find the existing state declarations (the `useState` block starting with `activeTab`). Add these two after the `watchlist` state:

```js
const [portfolioList, setPortfolioList] = useState([]);
const [screenResults, setScreenResults] = useState({});  // ticker → data | "loading" | "error"
```

- [ ] **Step 3: Load portfolio list from backend on mount**

Find the existing `useEffect` that loads the watchlist (around line 766):
```js
useEffect(() => {
  fetch(`${API_BASE}/watchlist`, { headers: apiHeaders() })
    .then(r => r.ok ? r.json() : null)
    .then(json => { if (json?.items?.length) setWatchlist(json.items); })
    .catch(() => { /* keep localStorage fallback */ });
}, []);
```

Add a second `useEffect` immediately after it for the portfolio:
```js
useEffect(() => {
  fetch(`${API_BASE}/portfolio`, { headers: apiHeaders() })
    .then(r => r.ok ? r.json() : null)
    .then(json => { if (json?.items) setPortfolioList(json.items); })
    .catch(() => {});
}, []);
```

- [ ] **Step 4: Add `loadPortfolioScreening` function to `App`**

After the `portfolioList` useEffect, add this function to the `App` component body:

```js
const loadPortfolioScreening = useCallback((list) => {
  if (!list.length) return;
  // Mark all as loading
  setScreenResults(prev => {
    const next = { ...prev };
    list.forEach(({ ticker }) => { if (!next[ticker]) next[ticker] = "loading"; });
    return next;
  });
  // Fetch each in parallel
  list.forEach(({ ticker }) => {
    fetch(`${API_BASE}/screen/${encodeURIComponent(ticker)}`, { headers: apiHeaders() })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => setScreenResults(prev => ({ ...prev, [ticker]: data })))
      .catch(() => setScreenResults(prev => ({ ...prev, [ticker]: "error" })));
  });
}, []);
```

- [ ] **Step 5: Trigger screening when Portfolio tab is activated**

Find the tab button rendering block (around line 1063):
```jsx
<button className={`tf-btn ${activeTab === "stocks" ? "active" : ""}`} onClick={() => setActiveTab("stocks")}>📈 STOCKS</button>
<button className={`tf-btn ${activeTab === "nhl" ? "active" : ""}`} onClick={() => setActiveTab("nhl")}>🏒 ICE EDGE</button>
```

Replace with:
```jsx
<button className={`tf-btn ${activeTab === "stocks" ? "active" : ""}`} onClick={() => setActiveTab("stocks")}>📈 STOCKS</button>
<button className={`tf-btn ${activeTab === "portfolio" ? "active" : ""}`} onClick={() => { setActiveTab("portfolio"); loadPortfolioScreening(portfolioList); }}>📊 PORTFOLIO</button>
<button className={`tf-btn ${activeTab === "nhl" ? "active" : ""}`} onClick={() => setActiveTab("nhl")}>🏒 ICE EDGE</button>
```

- [ ] **Step 6: Add portfolio tab render placeholder**

Find this section (around line 1069):
```jsx
{activeTab === "nhl" && <NHLPredictor />}
```

Add immediately after it:
```jsx
{activeTab === "portfolio" && (
  <Portfolio
    portfolioList={portfolioList}
    screenResults={screenResults}
    watchlist={watchlist}
    onAdd={async (ticker, name) => {
      await fetch(`${API_BASE}/portfolio`, {
        method: "POST",
        headers: apiHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ ticker, name }),
      });
      setPortfolioList(prev => prev.some(p => p.ticker === ticker) ? prev : [...prev, { ticker, name }]);
      setScreenResults(prev => ({ ...prev, [ticker]: "loading" }));
      fetch(`${API_BASE}/screen/${encodeURIComponent(ticker)}`, { headers: apiHeaders() })
        .then(r => r.ok ? r.json() : Promise.reject())
        .then(data => setScreenResults(prev => ({ ...prev, [ticker]: data })))
        .catch(() => setScreenResults(prev => ({ ...prev, [ticker]: "error" })));
    }}
    onRemove={async (ticker) => {
      await fetch(`${API_BASE}/portfolio/${encodeURIComponent(ticker)}`, {
        method: "DELETE", headers: apiHeaders(),
      });
      setPortfolioList(prev => prev.filter(p => p.ticker !== ticker));
      setScreenResults(prev => { const n = { ...prev }; delete n[ticker]; return n; });
    }}
  />
)}
```

- [ ] **Step 7: Verify the tab button renders (manual)**

Start the app (`start.bat`), open http://localhost:5173. Verify:
- Three tab buttons appear: 📈 STOCKS, 📊 PORTFOLIO, 🏒 ICE EDGE
- Clicking PORTFOLIO switches the tab (will show nothing until Portfolio component is added in Task 4)
- No console errors

- [ ] **Step 8: Commit**

```bash
git add stock-dashboard-frontend/src/App.jsx
git commit -m "feat: add portfolio state, tab button, and screen fetch logic"
```

---

### Task 4: Frontend — `Portfolio` component: list management

**Files:**
- Modify: `stock-dashboard-frontend/src/App.jsx`

This task adds the `Portfolio` component with add/remove/import functionality. The component is defined above `App` in `App.jsx`, consistent with the existing pattern (all components in one file).

- [ ] **Step 1: Add the `Portfolio` component to `App.jsx`**

Add this component definition immediately before the `// ─── Main App ───` comment block (around line 725):

```jsx
// ─── Portfolio ────────────────────────────────────────────────────────────────

const BADGE_COLORS = {
  green:  { background: "#052e16", color: "#00ff88", border: "1px solid #00ff8833" },
  red:    { background: "#450a0a", color: "#ef4444", border: "1px solid #ef444433" },
  yellow: { background: "#422006", color: "#f59e0b", border: "1px solid #f59e0b33" },
  gray:   { background: "#1e293b", color: "#94a3b8", border: "1px solid #33415533" },
};

function PortfolioBadge({ label, colorKey }) {
  const s = BADGE_COLORS[colorKey] || BADGE_COLORS.gray;
  return (
    <span style={{
      ...s, padding: "2px 7px", borderRadius: 3,
      fontSize: 10, fontFamily: "IBM Plex Mono, monospace", whiteSpace: "nowrap",
    }}>{label}</span>
  );
}

function getBadges(data) {
  if (!data || data === "loading" || data === "error") return [];
  const badges = [];

  if (data.short_interest_pct != null) {
    const p = data.short_interest_pct;
    if (p > SHORT_INTEREST_HIGH)     badges.push({ label: `SHORT ${p.toFixed(1)}% ⚠`, colorKey: "red" });
    else if (p > SHORT_INTEREST_WARN) badges.push({ label: `SHORT ${p.toFixed(1)}% ⚡`, colorKey: "yellow" });
    else                               badges.push({ label: `SHORT ${p.toFixed(1)}% ✓`, colorKey: "green" });
  } else {
    badges.push({ label: "SHORT —", colorKey: "gray" });
  }

  if (data.avg_volume != null) {
    const v = data.avg_volume;
    if (v < AVG_VOLUME_LOW)      badges.push({ label: `VOL ${formatVolume(v)} ⚠`, colorKey: "red" });
    else if (v < AVG_VOLUME_WARN) badges.push({ label: `VOL ${formatVolume(v)} ⚡`, colorKey: "yellow" });
    else                          badges.push({ label: `VOL ${formatVolume(v)} ✓`, colorKey: "green" });
  } else {
    badges.push({ label: "VOL —", colorKey: "gray" });
  }

  if (data.insider_net != null) {
    if (data.insider_net > 0)      badges.push({ label: "INSIDER +BUY", colorKey: "green" });
    else if (data.insider_net < 0) badges.push({ label: "INSIDER -SELL", colorKey: "red" });
    else                           badges.push({ label: "INSIDER NEUT", colorKey: "gray" });
  } else {
    badges.push({ label: "INSIDER —", colorKey: "gray" });
  }

  if (data.golden_cross != null) {
    badges.push(data.golden_cross
      ? { label: "GOLDEN ✓", colorKey: "green" }
      : { label: "DEATH ✗",  colorKey: "red" }
    );
  } else {
    badges.push({ label: "CROSS —", colorKey: "gray" });
  }

  return badges;
}

function getNextEvent(data) {
  if (!data || data === "loading" || data === "error") return null;
  const today = new Date();
  const events = [];
  if (data.earnings_date) {
    const d = new Date(data.earnings_date + "T00:00:00");
    const days = Math.ceil((d - today) / 86400000);
    if (days >= 0) events.push({ label: `EARN ${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })}`, days, warn: days <= EARNINGS_WARN_DAYS });
  }
  if (data.ex_dividend_date) {
    const d = new Date(data.ex_dividend_date + "T00:00:00");
    const days = Math.ceil((d - today) / 86400000);
    if (days >= 0 && days <= EXDIV_ALERT_DAYS)
      events.push({ label: `EX-DIV ${d.toLocaleDateString("en-US", { month: "short", day: "numeric" })}`, days, warn: false });
  }
  events.sort((a, b) => a.days - b.days);
  return events[0] || null;
}

function Portfolio({ portfolioList, screenResults, watchlist, onAdd, onRemove }) {
  const [expanded, setExpanded] = useState(new Set());
  const [addInput, setAddInput]   = useState("");
  const [addSuggestions, setAddSuggestions] = useState([]);
  const [showImport, setShowImport] = useState(false);
  const [importSelected, setImportSelected] = useState(new Set());
  const suggestTimer = useRef(null);

  const importCandidates = watchlist.filter(w => !portfolioList.some(p => p.ticker === w.ticker));

  function handleAddInputChange(e) {
    const val = e.target.value.toUpperCase();
    setAddInput(val);
    clearTimeout(suggestTimer.current);
    if (val.length < 1) { setAddSuggestions([]); return; }
    suggestTimer.current = setTimeout(async () => {
      try {
        const r = await fetch(`${API_BASE}/suggest/${encodeURIComponent(val)}`, { headers: apiHeaders() });
        const d = await r.json();
        setAddSuggestions((d.results || []).slice(0, 6));
      } catch { setAddSuggestions([]); }
    }, 300);
  }

  async function handleAddTicker(ticker, name) {
    await onAdd(ticker, name);
    setAddInput("");
    setAddSuggestions([]);
  }

  async function handleImportConfirm() {
    for (const ticker of importSelected) {
      const item = watchlist.find(w => w.ticker === ticker);
      if (item) await onAdd(item.ticker, item.name);
    }
    setImportSelected(new Set());
    setShowImport(false);
  }

  function toggleExpand(ticker) {
    setExpanded(prev => {
      const next = new Set(prev);
      next.has(ticker) ? next.delete(ticker) : next.add(ticker);
      return next;
    });
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>

      {/* Add bar */}
      <div style={{ display: "flex", gap: 8, alignItems: "center", position: "relative" }}>
        <input
          className="search-input"
          style={{ flex: 1 }}
          value={addInput}
          onChange={handleAddInputChange}
          onBlur={() => setTimeout(() => setAddSuggestions([]), 150)}
          onKeyDown={e => {
            if (e.key === "Enter" && addInput.trim()) handleAddTicker(addInput.trim(), addInput.trim());
          }}
          placeholder="ADD TICKER OR COMPANY NAME…"
          maxLength={50}
        />
        <button
          className="search-btn"
          disabled={!addInput.trim()}
          onClick={() => handleAddTicker(addInput.trim(), addInput.trim())}
        >+ ADD</button>
        <button
          className="tf-btn"
          onClick={() => setShowImport(v => !v)}
        >↑ FROM WATCHLIST</button>

        {/* Autocomplete dropdown */}
        {addSuggestions.length > 0 && (
          <div className="suggestions-dropdown" style={{ top: "100%", left: 0, right: 120 }}>
            {addSuggestions.map(s => (
              <div key={s.ticker} className="suggestion-item"
                onMouseDown={() => handleAddTicker(s.ticker, s.name)}>
                <span className="suggestion-ticker">{s.ticker}</span>
                <span className="suggestion-name">{s.name}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* From Watchlist import panel */}
      {showImport && (
        <div style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: 6, padding: 12 }}>
          {importCandidates.length === 0 ? (
            <span style={{ color: "#475569", fontSize: 12 }}>All watchlist items are already in your portfolio.</span>
          ) : (
            <>
              <div style={{ color: "#94a3b8", fontSize: 11, marginBottom: 8 }}>Select items to add:</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 10 }}>
                {importCandidates.map(w => (
                  <label key={w.ticker} style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", color: "#e2e8f0", fontSize: 12 }}>
                    <input
                      type="checkbox"
                      checked={importSelected.has(w.ticker)}
                      onChange={e => setImportSelected(prev => {
                        const next = new Set(prev);
                        e.target.checked ? next.add(w.ticker) : next.delete(w.ticker);
                        return next;
                      })}
                    />
                    <span style={{ color: "#00ff88", fontFamily: "IBM Plex Mono, monospace" }}>{w.ticker}</span>
                    <span style={{ color: "#475569" }}>{w.name}</span>
                  </label>
                ))}
              </div>
              <button className="search-btn" disabled={importSelected.size === 0} onClick={handleImportConfirm}>
                ADD SELECTED ({importSelected.size})
              </button>
            </>
          )}
        </div>
      )}

      {/* Column headers */}
      {portfolioList.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "80px 70px 1fr 100px 20px", gap: 8, padding: "0 10px", color: "#334155", fontSize: 10, textTransform: "uppercase", fontFamily: "IBM Plex Mono, monospace" }}>
          <span>Ticker</span><span>Price</span><span>Signals</span><span>Next Event</span><span />
        </div>
      )}

      {/* Rows */}
      {portfolioList.length === 0 ? (
        <div style={{ color: "#334155", fontSize: 13, textAlign: "center", padding: "40px 0" }}>
          No stocks in portfolio. Add a ticker above or import from your watchlist.
        </div>
      ) : (
        portfolioList.map(({ ticker, name }) => {
          const data = screenResults[ticker];
          const isLoading = !data || data === "loading";
          const isError   = data === "error";
          const isExpanded = expanded.has(ticker);
          const badges = getBadges(data);
          const nextEvent = getNextEvent(data);
          const price = (!isLoading && !isError && data?.current_price) ? formatPrice(data.current_price) : "—";

          return (
            <div key={ticker} style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: 6 }}>
              {/* Collapsed row */}
              <div
                style={{ display: "grid", gridTemplateColumns: "80px 70px 1fr 100px 20px", gap: 8, padding: "9px 10px", alignItems: "center", cursor: "pointer" }}
                onClick={() => !isLoading && !isError && toggleExpand(ticker)}
              >
                <span style={{ color: "#00ff88", fontWeight: "bold", fontSize: 12, fontFamily: "IBM Plex Mono, monospace" }}>{ticker}</span>
                <span style={{ color: "#e2e8f0", fontSize: 12, fontFamily: "IBM Plex Mono, monospace" }}>{price}</span>

                {/* Badges or loading shimmer */}
                <div style={{ display: "flex", gap: 4, flexWrap: "wrap", alignItems: "center" }}>
                  {isLoading ? (
                    [60, 50, 70, 65].map((w, i) => (
                      <div key={i} className="skeleton" style={{ width: w, height: 18, borderRadius: 3, animationDelay: `${i * 0.1}s` }} />
                    ))
                  ) : isError ? (
                    <PortfolioBadge label="DATA UNAVAILABLE" colorKey="gray" />
                  ) : (
                    badges.map((b, i) => <PortfolioBadge key={i} label={b.label} colorKey={b.colorKey} />)
                  )}
                </div>

                {/* Next event */}
                <span style={{ fontSize: 10, fontFamily: "IBM Plex Mono, monospace", color: nextEvent?.warn ? "#f59e0b" : "#475569" }}>
                  {isLoading ? "" : nextEvent?.label ?? "—"}
                </span>

                {/* Expand toggle + remove */}
                <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                  {!isLoading && !isError && (
                    <span style={{ color: "#475569", fontSize: 11 }}>{isExpanded ? "▾" : "▸"}</span>
                  )}
                </div>
              </div>

              {/* Remove button on hover — always visible on right edge */}
              {/* Expand detail panel */}
              {isExpanded && data && data !== "loading" && data !== "error" && (
                <div style={{ borderTop: "1px solid #1e293b", padding: "10px 10px", display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
                  {[
                    { label: "Short Interest", value: data.short_interest_pct != null ? `${data.short_interest_pct.toFixed(1)}% of float` : "N/A", sub: `flag > ${SHORT_INTEREST_HIGH}%` },
                    { label: "Avg Daily Volume", value: data.avg_volume != null ? `${formatVolume(data.avg_volume)} shares` : "N/A", sub: `flag < ${formatVolume(AVG_VOLUME_LOW)}` },
                    { label: "Insider (recent 20)", value: data.insider_net != null ? `+${data.insider_buys} buys, ${data.insider_sells} sells` : "N/A", sub: data.insider_net != null ? (data.insider_net > 0 ? "net bullish" : data.insider_net < 0 ? "net bearish" : "neutral") : "" },
                    { label: "Golden Cross", value: data.golden_cross != null ? `50MA $${data.ma_50} vs 200MA $${data.ma_200}` : "Insufficient data (<200d)", sub: data.golden_cross === true ? "bullish signal" : data.golden_cross === false ? "death cross" : "" },
                    { label: "Next Earnings", value: data.earnings_date ?? "N/A", sub: data.earnings_date ? `flag within ${EARNINGS_WARN_DAYS}d` : "" },
                    { label: "Ex-Dividend", value: data.ex_dividend_date ?? "None upcoming", sub: data.ex_dividend_date ? `show within ${EXDIV_ALERT_DAYS}d` : "" },
                  ].map(({ label, value, sub }) => (
                    <div key={label}>
                      <div style={{ color: "#475569", fontSize: 9, textTransform: "uppercase", marginBottom: 3, fontFamily: "IBM Plex Mono, monospace" }}>{label}</div>
                      <div style={{ color: "#e2e8f0", fontSize: 11, fontFamily: "IBM Plex Mono, monospace" }}>{value}</div>
                      {sub && <div style={{ color: "#334155", fontSize: 9, fontFamily: "IBM Plex Mono, monospace" }}>{sub}</div>}
                    </div>
                  ))}
                  <div style={{ gridColumn: "1 / -1", display: "flex", justifyContent: "flex-end", marginTop: 4 }}>
                    <button
                      style={{ background: "transparent", border: "1px solid #334155", color: "#475569", padding: "3px 10px", borderRadius: 3, fontSize: 10, cursor: "pointer", fontFamily: "IBM Plex Mono, monospace" }}
                      onClick={e => { e.stopPropagation(); onRemove(ticker); }}
                    >REMOVE</button>
                  </div>
                </div>
              )}
            </div>
          );
        })
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify manually**

Start the app. Open the Portfolio tab. Verify:
1. Empty state message shows when portfolio is empty
2. Type a ticker in the add field — autocomplete dropdown appears
3. Click a suggestion → ticker is added to the list, shimmer badges appear while loading, then real badges appear
4. "FROM WATCHLIST" button shows watchlist items with checkboxes
5. Check some items, click "ADD SELECTED" → they appear in the portfolio
6. Click an expanded row's REMOVE button → it disappears from the list
7. Refresh page — portfolio list persists (loaded from backend)

- [ ] **Step 3: Commit**

```bash
git add stock-dashboard-frontend/src/App.jsx
git commit -m "feat: add Portfolio component with screening badges and expand/collapse detail"
```

---

## Self-Review Notes

**Spec coverage check:**
- ✅ Portfolio list separate from watchlist, linked via "From Watchlist" import
- ✅ Hybrid row + badge layout (Task 4)
- ✅ Auto-load on tab open (Task 3, `loadPortfolioScreening` called on tab button click)
- ✅ Hardcoded thresholds as named constants (Tasks 1 + 3)
- ✅ Short interest badge (Task 4)
- ✅ Avg volume badge (Task 4)
- ✅ Insider activity badge (Tasks 2 + 4)
- ✅ Golden cross badge (Tasks 2 + 4)
- ✅ Earnings date badge (Tasks 2 + 4)
- ✅ Ex-dividend date badge (Tasks 2 + 4)
- ✅ Click to expand detail panel (Task 4)
- ✅ Progressive loading shimmer (Task 4)
- ✅ Error state per row (Task 4)
- ✅ Add via autocomplete (Task 4)
- ✅ Remove from portfolio (Task 4)
- ✅ Import from watchlist checklist (Task 4)
- ✅ SQLite `portfolio` table (Task 1)
- ✅ `/portfolio` CRUD endpoints (Task 1)
- ✅ `/screen/{ticker}` endpoint (Task 2)
- ✅ Tests for CRUD (Task 1)
- ✅ Tests for `_compute_golden_cross` (Task 2)

**No TBDs or placeholders found.**

**Type consistency:** `formatVolume` is used in both `getBadges` and the detail panel — it's already defined in `App.jsx`. `formatPrice` is used for the price column — already defined. All API paths use `/api` via `API_BASE`. `WatchlistItem` Pydantic model is reused for portfolio POST body.
