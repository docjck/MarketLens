# Portfolio Tab — Design Spec

**Date:** 2026-04-16
**Status:** Approved

---

## Overview

Add a new **Portfolio** tab to MarketLens between STOCKS and ICE EDGE. The tab shows a user-managed list of stocks with automated screening checks: short interest, average volume, insider activity, golden cross signal, upcoming earnings, and ex-dividend dates. Each stock renders as a compact row with colored badge flags; clicking a row expands to show full detail.

---

## Portfolio List

- Separate from the existing Watchlist, but linked to it.
- Stored in a new `portfolio` SQLite table (same schema as `watchlist`: `ticker`, `name`, `added_at`).
- Managed via new CRUD endpoints: `GET /portfolio`, `POST /portfolio`, `DELETE /portfolio/{ticker}`.
- **Adding stocks:** Ticker autocomplete input (reuses existing `/suggest/{query}` endpoint) + `+ ADD` button.
- **From Watchlist:** A `↑ FROM WATCHLIST` button expands an inline checklist of watchlist items not already in the portfolio. User checks items and confirms with "Add Selected". No modal.

---

## Screening Checks

Six checks per stock, all sourced from a single new backend endpoint `GET /screen/{ticker}`.

| Check | yfinance source | Badge logic |
|---|---|---|
| **Short Interest** | `tk.info["shortPercentOfFloat"]` | green < 5%, yellow 5–10%, red > 10% |
| **Avg Volume** | `tk.info["averageVolume"]` | green > 5M, yellow 1–5M, red < 1M |
| **Insider Activity** | `tk.insider_transactions` (last 90 days) | green = net buys, red = net sells, gray = no activity |
| **Golden Cross** | 200d price history → 50MA vs 200MA | green = 50MA > 200MA, red = death cross, gray = < 200 days data |
| **Earnings Date** | `tk.calendar` | show date; yellow badge if within 14 days |
| **Ex-Dividend Date** | `tk.info["exDividendDate"]` | show date if within 30 days; gray if none |

### Thresholds (named constants in `main.py`)

```python
SHORT_INTEREST_HIGH  = 10.0   # red above 10% (percent units, matches short_interest_pct)
SHORT_INTEREST_WARN  = 5.0    # yellow above 5%
AVG_VOLUME_LOW       = 1_000_000    # red below 1M
AVG_VOLUME_WARN      = 5_000_000    # yellow below 5M
EARNINGS_WARN_DAYS   = 14     # yellow if earnings within 14 days
EXDIV_ALERT_DAYS     = 30     # show badge if ex-div within 30 days
```

Thresholds are intentionally hardcoded constants (no settings UI) but are easy to edit in one place.

---

## Backend

### New table

```sql
CREATE TABLE IF NOT EXISTS portfolio (
    ticker   TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    added_at TEXT DEFAULT (datetime('now'))
)
```

### New endpoints

```
GET    /portfolio              — list all portfolio items
POST   /portfolio              — add item {ticker, name}; reuses WatchlistItem validator
DELETE /portfolio/{ticker}     — remove item
GET    /screen/{ticker}        — return all screening data including current price (see response shape below)
```

### `/screen/{ticker}` response shape

```json
{
  "ticker": "AAPL",
  "current_price": 213.40,
  "short_interest_pct": 0.8,
  "avg_volume": 68200000,
  "insider_buys": 4,
  "insider_sells": 1,
  "insider_net": 3,
  "golden_cross": true,
  "ma_50": 209.14,
  "ma_200": 197.32,
  "earnings_date": "2026-07-30",
  "ex_dividend_date": "2026-08-09"
}
```

Fields that cannot be determined return `null`. The endpoint never 500s on missing fields — it catches per-field exceptions and returns `null` for that field.

---

## Frontend

### State additions (in root `App` component)

```js
const [portfolioList, setPortfolioList]   = useState([]);   // {ticker, name}[]
const [screenResults, setScreenResults]   = useState({});   // {[ticker]: data | "loading" | "error"}
```

`portfolioList` is fetched from `GET /portfolio` on mount (alongside the existing watchlist fetch).

### Tab activation behaviour

When the user switches to the Portfolio tab, for each ticker in `portfolioList`:
1. Set `screenResults[ticker] = "loading"`.
2. Fire `GET /screen/{ticker}` in parallel (no sequential waiting).
3. On success: set `screenResults[ticker] = data`.
4. On error: set `screenResults[ticker] = "error"`.

Rows render progressively — a row with status `"loading"` shows shimmer skeleton badges.

### `Portfolio` component (new, in `App.jsx`)

Self-contained component, ~150–200 lines, consistent with existing single-file pattern.

**Row (collapsed):**
```
[TICKER] [PRICE] [BADGE BADGE BADGE BADGE] [NEXT EVENT] [▸]
```

**Row (expanded — click to toggle):**
```
[TICKER] [PRICE] [BADGE BADGE BADGE BADGE] [NEXT EVENT] [▾]
─────────────────────────────────────────────────────────────
Short Interest  |  Avg Volume  |  Insider (90d)
Golden Cross    |  Earnings    |  Ex-Dividend
(raw values + threshold labels)
```

**Badge colours:**
- Green `#00ff88` — clear/bullish
- Red `#ef4444` — flag/warning
- Yellow `#f59e0b` — caution
- Gray `#94a3b8` — no data / neutral

**Error state:** Row shows single gray `DATA UNAVAILABLE` badge. Does not crash other rows.

---

## File Changes Summary

| File | Change |
|---|---|
| `stock-dashboard-backend/main.py` | Add `portfolio` table init; add `GET/POST/DELETE /portfolio`; add `GET /screen/{ticker}`; add threshold constants |
| `stock-dashboard-frontend/src/App.jsx` | Add `portfolioList` + `screenResults` state; add `Portfolio` component; add tab button |

No new files required.

---

## Out of Scope

- Configurable threshold UI (thresholds are constants, not user-editable in the app)
- Price/cost basis tracking (this is a screening tool, not a P&L tracker)
- Sorting/filtering the portfolio table
- Export to CSV
