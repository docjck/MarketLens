# Sidebar Live Prices — Design Spec

**Date:** 2026-03-26
**Project:** MarketLens
**Status:** Approved

---

## Overview

Show live % change (vs previous close) for every ticker in both the Markets and Watchlist sidebar panels. Prices refresh automatically every 60 seconds. Display is minimal: a green `+X.XX%` or red `−X.XX%` value on the right side of each sidebar item. A `—` placeholder is shown while the first fetch is in-flight or if a ticker returns no data.

---

## Backend

### New endpoint: `GET /prices`

**Location:** `stock-dashboard-backend/main.py`

**Query params:**
- `tickers` — comma-separated list of ticker symbols (e.g. `^GSPC,^IXIC,AAPL,GC=F`)

**Validation:**
- Each ticker validated against existing regex `^[\^A-Za-z0-9.\-=]{1,20}$` (includes `^` for index tickers and `=` for futures)
- Invalid tickers are silently skipped (not an error)
- Empty or missing `tickers` param returns `{}`
- Maximum 50 tickers per request; excess tickers are silently truncated

**Logic:**
- Fetch `fast_info` for each ticker in parallel using `ThreadPoolExecutor(max_workers=20)`
- Compute: `pct_change = (last_price - previous_close) / previous_close * 100`
- If either `last_price` or `previous_close` is `None`, or `previous_close == 0`, return `null` for that ticker
- Per-ticker errors (missing data, yfinance failure) return `null` for that key

**Response shape:**
```json
{
  "^GSPC": 0.82,
  "^IXIC": -1.14,
  "GC=F": 0.31,
  "AAPL": 1.23,
  "MISSING": null
}
```

**Rate limiting:** Explicit `@limiter.limit("10/minute")` override — each request fans out to up to 50 yfinance calls via the thread pool, so a tighter per-endpoint limit is appropriate.

**Timeouts:** The thread pool uses `concurrent.futures.wait(futures, timeout=8)`. Only futures in the `done` set are read; futures in the `not_done` set are abandoned (their results silently discarded — never call `.result()` on them). Tickers whose futures are in `not_done` return `null` in the response.

---

## Frontend

### State

In the main `App` component:

```js
const [prices, setPrices] = useState({});  // ticker → float | null
```

### `fetchPrices()` function

- Builds a combined tickers list: all static `MARKETS` tickers + all current `watchlist` tickers
- Calls `GET /api/prices?tickers=<comma-joined list>` with `apiHeaders()`
- On success: merges response into `prices` state
- On error: silently fails (leaves existing `prices` state intact — stale data is better than blanking)

### Polling

Use a `useRef` for both the watchlist and an in-flight flag so the interval is stable and concurrent fetches are prevented:

```js
const watchlistRef = useRef(watchlist);
useEffect(() => { watchlistRef.current = watchlist; }, [watchlist]);

const isFetchingRef = useRef(false);

useEffect(() => {
  const getPrices = () => {
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
  getPrices();
  const id = setInterval(getPrices, 60_000);
  return () => clearInterval(id);
}, []); // stable — watchlist and in-flight state read via refs
```

- The interval is created once on mount and never reset
- `isFetchingRef` prevents concurrent overlapping fetches; `.finally()` always resets it so a single timeout never permanently blocks future ticks
- Newly-added watchlist tickers are included on the next tick via `watchlistRef`

### Prop drilling

- `prices` passed as prop to `Markets` and `Watchlist` with updated signatures:
  - `Markets({ activeTicker, onSelect, prices })`
  - `Watchlist({ watchlist, activeTicker, onSelect, onRemove, prices })`

---

## UI

### Layout (both panels)

Each sidebar item gains a `% change` value on the right, matching the existing flex row layout:

```
[TICKER]        +0.82%
[name/label]
```

- **Green** (`#00ff88`) for positive values — matches existing accent color
- **Red** (`#ef4444`) for negative values — matches existing error color
- `—` in muted color (`#1e293b`) while loading or when value is `null`
- Font: `IBM Plex Mono`, 11px, weight 600

### No timestamp

No "refreshed X ago" indicator — omitted to keep the sidebar clean.

### Watchlist item layout

The existing remove button (`✕`) remains on the far right. % change sits to the left of it, between the ticker/name block and the remove button.

---

## Files Changed

| File | Change |
|---|---|
| `stock-dashboard-backend/main.py` | Add `GET /prices` endpoint |
| `stock-dashboard-frontend/src/App.jsx` | Add `prices` state + `fetchPrices` + polling; update `Markets` and `Watchlist` props and render |

---

## Out of Scope

- Absolute price display (% change only)
- WebSocket / push-based updates
- Per-ticker sparklines or trend indicators
- Price data persistence
