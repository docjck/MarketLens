# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project: MarketLens Stock Dashboard

A personal stock research dashboard. React frontend with a FastAPI backend that fetches OHLCV data and company info from yfinance.

**Root:** `C:\Users\Jeremy\chartproject\`

## Structure

```
chartproject/
├── start.bat                    # Launches backend + frontend in one click
├── stock-dashboard-frontend/    # React + Vite + Recharts UI
│   ├── src/
│   │   ├── App.jsx              # Main app (all components live here)
│   │   └── main.jsx             # React entry point
│   ├── index.html
│   └── vite.config.js
└── stock-dashboard-backend/     # FastAPI + yfinance API
    └── main.py                  # All backend logic in one file
```

## Commands

```bash
# Start everything locally (double-click or run from terminal)
start.bat

# Start with remote access via Cloudflare Tunnel
start.bat --tunnel

# Install backend deps
pip install -r requirements.txt

# Install frontend deps
npm install
```

## Architecture

**Backend** (`stock-dashboard-backend/main.py`):
- `GET /search/{ticker}` — returns company name, exchange, currency via `yf.Ticker.fast_info`
- `GET /suggest/{query}` — live autocomplete via Yahoo Finance search API; supports company names (e.g. "Apple" → AAPL)
- `GET /chart/{ticker}/{timeframe}` — returns OHLCV array; timeframes: `1d` (5m bars), `6m` (1d bars), `5y` (1wk bars), `10y` (1mo bars)
- `GET /chart/{ticker}/all` — all timeframes in one call
- `GET /watchlist` / `POST /watchlist` / `DELETE /watchlist/{ticker}` — SQLite-backed persistent watchlist (`watchlist.db`)
- CORS is open (`allow_origins=["*"]`) — dev only

**Frontend** (`stock-dashboard-frontend/src/App.jsx`):
- Single-file React app; all components are in `App.jsx`
- API base: `/api` (proxied through Vite → `localhost:8000`; enables single-port tunnel access)
- Watchlist loaded from backend on mount; add/remove synced to API; `localStorage` (`marketlens_watchlist`) kept as offline fallback
- Chart data cached in component state by `{ ticker: { timeframe: data[] } }`
- All CSS is inline or in a `<style>` tag in JSX — no external stylesheet

## Key Components

| Component | Purpose |
|---|---|
| `ChartPanel` | Recharts `ComposedChart` with Area (close price) + Bar (volume overlay) |
| `VolumeAtPrice` | 80-bucket horizontal VAP histogram, plain divs, right of chart |
| `Watchlist` | Sidebar list with click-to-load and remove |
| `InfoCardSkeleton` / `ChartSkeleton` | Shimmer loading states |
| `CustomTooltip` | Dark tooltip showing date, close, volume |
| `ErrorBanner` | Dismissable red error strip |

## Design Conventions

- **Fonts**: `IBM Plex Mono` (data/labels), `Syne` (headings/buttons)
- **Colors**: background `#050810`, accent green `#00ff88`, blue `rgba(59,130,246,x)`, muted `#475569`/`#334155`
- **Chart height**: 320px fixed
- **VAP panel**: 88px wide, 80 price buckets, 2px bars, aligned right of chart
- All Recharts axes: `axisLine={false} tickLine={false}`

## Dependencies

**Backend**: fastapi 0.111, uvicorn, yfinance 0.2.38, pandas >=2.1, requests 2.31, sqlite3 (stdlib)

**Frontend**: react 18, react-dom 18, recharts 2.12, vite 5.2, @vitejs/plugin-react 4.2

## Remote Access

`start.bat --tunnel` launches a Cloudflare quick tunnel (no account needed). It outputs a public `https://xxxxx.trycloudflare.com` URL that works from any device. The Vite proxy routes `/api/*` to the backend so only one port (5173) needs tunnelling. The URL changes each session — close the tunnel window to stop sharing.

**Requires**: `cloudflared` (installed via `winget install Cloudflare.cloudflared`)

## Compact Instructions

When compacting, preserve: current task state, recent code changes, active file paths, and any errors being debugged. Drop: old search results, completed task details, and exploratory reads that didn't lead to changes.

## Future Ideas

1. **More data sources / markets** — look beyond yfinance: Alpha Vantage, Polygon.io, Twelve Data, EODHD, or Interactive Brokers API.
2. **Technical indicators** — RSI (14), MACD (12/26/9), MAs (20/50/200). Calculate on the frontend from existing OHLCV data; render as toggleable sub-panels below the price chart.
3. **Cloud deployment** — move from Cloudflare quick tunnel to always-on hosting (Render, Railway, VPS) for a fixed URL.
4. **Chart annotations** — trendlines, support/resistance, fib retracements via canvas/SVG overlay; persist to the SQLite backend.
