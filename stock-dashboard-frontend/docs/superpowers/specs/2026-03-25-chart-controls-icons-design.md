# Chart Controls — SVG Icon Buttons Design

**Date:** 2026-03-25
**Status:** Approved

## Problem

The chart header control row is crowded. Three separate button groups (LINE/CANDLE + 5 timeframes + DRAW/CLEAR) sit in a single flex row, causing horizontal overflow at normal widths and making the header feel visually noisy.

## Goal

Reduce horizontal space consumed by the chart type toggle by replacing the `LINE` / `CANDLE` text buttons with compact inline SVG icon buttons, freeing room for the timeframe group and keeping everything on one row cleanly.

## What Changes

### Chart type toggle (`LINE` / `CANDLE` buttons)

Replace the two text `tf-btn` buttons with icon-only buttons. Each button renders an inline SVG:

**Line chart icon** (`chartType === "line"` active state):
```svg
<svg width="20" height="16" viewBox="0 0 20 16" fill="none">
  <polyline points="1,13 5,8 9,10 13,4 19,6"
    stroke="currentColor" stroke-width="1.5"
    stroke-linejoin="round" stroke-linecap="round"/>
</svg>
```

**Candlestick icon** (`chartType === "candle"` active state) — two candles with identical proportions (3px top wick, 6px body, 4px bottom wick) at slightly different vertical positions to suggest two price levels:
```svg
<svg width="20" height="16" viewBox="0 0 20 16" fill="none">
  <line x1="5" y1="1" x2="5" y2="4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
  <rect x="3" y="4" width="4" height="6" rx="0.5" fill="currentColor" opacity="0.7"/>
  <line x1="5" y1="10" x2="5" y2="14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
  <line x1="15" y1="2" x2="15" y2="5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
  <rect x="13" y="5" width="4" height="6" rx="0.5" fill="none" stroke="currentColor" stroke-width="1"/>
  <line x1="15" y1="11" x2="15" y2="15" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
</svg>
```

Both buttons use `currentColor` so the existing `.tf-btn` and `.tf-btn.active` CSS classes drive the color automatically — no new CSS needed.

Each button gets a `title` attribute for hover tooltip: `"Line chart"` and `"Candlestick"`.

Button padding is overridden via an inline `style={{ padding: "5px 10px" }}` prop on each icon button (not a CSS class change), keeping the hit target reasonable without excess whitespace. The shared `.tf-btn` padding rule (`5px 14px`) is not modified.

### Everything else — unchanged

- Timeframe buttons (`1D` / `5D` / `6M` / `1Y` / `5Y`) — unchanged
- `DRAW` button — stays as text, unchanged
- `CLEAR` button — unchanged
- Draw toolbar row (LINE / HLINE / CHANNEL / FIB + color dots) — unchanged
- Active state styling (green tint + `#00ff88` color) — driven by existing `.tf-btn.active` class, works automatically via `currentColor`
- Disabled state when no ticker loaded — unchanged
- Legend row — unchanged

## Implementation Scope

Single file: `src/App.jsx`, lines ~1157–1159 (the two chart type `tf-btn` buttons inside the `tf-group` div with `marginRight: 8`).

No CSS changes required. No backend changes required.
