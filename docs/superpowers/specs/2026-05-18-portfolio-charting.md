# Portfolio Charting — Design Spec

**Date:** 2026-05-18
**Status:** Approved

---

## Overview

Add inline price charting to the Portfolio tab. Each portfolio row expands to reveal a full price chart (reusing `ChartPanel`) with: a persisted entry price line, the complete drawing toolkit (LINE, HLINE, CHANNEL, FIB, TEXT, ERASE), and the existing signals grid below. Entry price is stored in SQLite; drawing annotations are stored in `localStorage` shared with the STOCKS tab.

---

## Section 1: Architecture & Data

### Backend

**Schema migration** — add `entry_price` column to the existing `portfolio` table:

```sql
ALTER TABLE portfolio ADD COLUMN entry_price REAL
```

Guarded with a `try/except` so it is safe to run against an already-migrated DB.

**`GET /portfolio`** — include `entry_price` (nullable float) in each returned item.

**`PATCH /portfolio/{ticker}`** — new endpoint. Accepts `{ "entry_price": 195.00 }` or `{ "entry_price": null }` to clear. Returns the updated item. Reuses `_validate_ticker_param`. Uses a new Pydantic model `PortfolioEntryPrice` with `entry_price: float | None`.

### Frontend state (inside `Portfolio` component)

| State | Type | Purpose |
|---|---|---|
| `chartCache` | `{ [ticker]: { [tf]: data[] } }` | Per-ticker chart data; fetched on expand, cached so reopening avoids re-fetch |
| `chartLoading` | `{ [ticker]: bool }` | Per-ticker loading flag |
| `chartError` | `{ [ticker]: string \| null }` | Per-ticker error message |
| `activeTimeframe` | `{ [ticker]: string }` | Default `"6m"` per ticker |
| `drawMode` | `bool` | Resets when switching to a different row |
| `drawTool` | `string` | One of `"line"`, `"hline"`, `"channel"`, `"fib"`, `"text"`, `"erase"` |
| `drawColor` | `string` | Hex color string |
| `activeRow` | `string \| null` | Single-expand: the currently open ticker, or null |

`activeRow` replaces the existing `expanded: Set` — only one row open at a time.

### Annotations

Shared with the STOCKS tab via the same `marketlens_annotations` localStorage key, keyed as `${ticker}_${timeframe}`. Lines drawn on AAPL in the Portfolio chart appear when viewing AAPL in the STOCKS tab and vice versa.

All annotation objects get a unique `id` field (`Date.now() + "_" + Math.random()`) added at creation time in `onAddLine`. This enables individual deletion by ID.

---

## Section 2: Entry Price & Chart Rendering

### Entry price line on chart

Entry price is price-space aware and must stay pinned to that dollar level regardless of timeframe. It is rendered as a Recharts `ReferenceLine` inside `ChartPanel` — not in the pixel-space SVG overlay — so it automatically repositions as the Y axis domain changes.

`ChartPanel` receives one new prop: `entryPrice: number | null`. When non-null, renders:

```jsx
<ReferenceLine
  y={entryPrice}
  stroke="#f59e0b"
  strokeDasharray="4 3"
  strokeWidth={1.5}
  label={{
    value: `ENTRY $${entryPrice.toFixed(2)}`,
    position: "insideTopLeft",
    fill: "#f59e0b",
    fontSize: 9,
    fontFamily: "'IBM Plex Mono', monospace",
  }}
/>
```

### Entry price input bar

Rendered below the chart, above the signals grid:

```
ENTRY PRICE  [ $195.00 ]   ↑ +$18.40  +9.41%   [CLEAR]
```

- Typing and pressing Enter or blurring calls `PATCH /portfolio/{ticker}` and updates local `portfolioList` state
- P&L computed from `chartCache[ticker][tf][last].close` vs `entryPrice`; displayed green (gain) or red (loss)
- CLEAR button sets entry_price to null
- If no entry price is set: placeholder text `set a price…`

---

## Section 3: Drawing Tools

### Tool palette (shown when DRAW is active)

```
[LINE] [HLINE] [CHANNEL] [FIB] [TEXT] [ERASE]   ● ● ● ● ● ●
```

The first four tools are unchanged from the STOCKS tab. Two new tools:

### ERASE tool

When ERASE is the active draw tool, `mouseDown` on the chart finds the nearest annotation within a 10px threshold and removes it by `id`.

Distance calculation per annotation type:

| Type | Distance metric |
|---|---|
| `hline` | `Math.abs(clickY - ann.y)` |
| `text` | Euclidean distance to `(ann.x, ann.y)` |
| `line` | Perpendicular distance to segment `(x1,y1)→(x2,y2)` |
| `channel` | Min of distances to both boundary lines |
| `fib` | Min distance across all rendered fib level lines |

If no annotation is within the 10px threshold, the click is a no-op. Cursor: `crosshair` (same as other draw tools).

### TEXT tool

1. User clicks anywhere on chart while TEXT tool is active
2. A small `<input>` appears absolutely positioned over the SVG at the click coordinates
3. User types a label; Enter or blur confirms
4. Empty text discards the note
5. Stored as `{ id, type: "text", x, y, text, color }`

Rendered in the SVG overlay:

```jsx
<g key={i}>
  <rect
    x={ann.x - 2} y={ann.y - 13}
    width={ann.text.length * 7 + 8} height={16}
    fill="rgba(5,8,16,0.82)" rx={2}
  />
  <text
    x={ann.x + 2} y={ann.y}
    fill={ann.color} fontSize={11}
    fontFamily="'IBM Plex Mono', monospace"
  >
    {ann.text}
  </text>
</g>
```

---

## Section 4: Expanded Row Layout

### Collapsed row (unchanged)

```
[TICKER] [PRICE] [5D CHG] [BADGES] [NEXT EVENT] [▸]
```

### Expanded row (single row open at a time)

```
[TICKER] [PRICE] [5D CHG] [BADGES] [NEXT EVENT] [▾]
──────────────────────────────────────────────────────
[1D][5D][6M][1Y][5Y]  [line|candle]  [DRAW][CLEAR]
┌──────────────────── ChartPanel ─────────────────┐
│  · · · · · entry $195.00 · · · · · · · · · · ·  │  ← ReferenceLine
└──────────────────────────────────────────────────┘
ENTRY PRICE [ $195.00 ]  ↑ +$18.40 (+9.41%)  [CLEAR]
──────────────────────────────────────────────────────
Short Int  │  Avg Vol  │  Insider (recent 20)
Golden     │  Earnings │  Ex-Dividend
                                        [REMOVE]
```

Draw toolbar shown below timeframe row when DRAW is active:

```
[LINE][HLINE][CHANNEL][FIB][TEXT][ERASE]   ● ● ● ● ● ●
```

CLEAR button (clears all annotations for `ticker_timeframe`) is shown only when there are existing annotations.

---

## File Changes

| File | Change |
|---|---|
| `stock-dashboard-backend/main.py` | Add `entry_price` column migration (guarded); include `entry_price` in `GET /portfolio`; add `PATCH /portfolio/{ticker}` with `PortfolioEntryPrice` model |
| `stock-dashboard-frontend/src/App.jsx` | `ChartPanel`: add `entryPrice` prop + `ReferenceLine`; add `id` to annotations on creation in `handleAddLine`; add TEXT rendering + ERASE distance logic to SVG overlay; `Portfolio` component: single-expand, internal chart state, timeframe/type selectors, draw toolbar, entry price bar |

No new files required.

---

## Out of Scope

- Cost basis tracking with multiple lots / average-down entries
- P&L in dollar-absolute terms beyond the single entry price
- Export of annotations or entry prices
- Syncing drawing annotations to the backend (localStorage is sufficient)
- Configurable distance threshold for ERASE tool
