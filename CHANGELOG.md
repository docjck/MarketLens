# MarketLens Changelog

---

## 2026-03-16

### Security Hardening (`adb0fbe`)
- Fixed CORS misconfiguration — removed `allow_credentials=True` (incompatible with wildcard origin)
- Added optional token auth via `API_TOKEN` env var — all endpoints require `X-API-Token` header when set
- Added rate limiting via slowapi: 120/min global default, 20/min on `/suggest`
- All ticker path params now validated against regex `^[A-Za-z0-9.\-]{1,20}$`
- `WatchlistItem` model now validates ticker format and caps name at 200 chars
- Replaced raw exception detail in 500 responses with generic messages (logged server-side)
- Fixed `ODDS_API_KEY` leaking into request logs — moved from f-string URL to params dict
- Odds API error messages no longer forwarded raw to the frontend
- Added 5MB response size guard on Odds API fetch
- Added `.env.example` files for backend (`API_TOKEN`, `ODDS_API_KEY`) and frontend (`VITE_API_TOKEN`)
- All frontend fetch calls now send `X-API-Token` via `apiHeaders()` helper

### NHL Backtest Feature (`ecc4974`)
- New `backtest_picks` SQLite table to persist backtest sessions
- `GET /nhl/backtest/games/{date}` — fetches historical standings + model predictions for any past date; games sorted by model confidence; no scores returned
- `POST /nhl/backtest/score` — scores user picks against actual NHL results and saves to DB
- `GET /nhl/backtest/history` — returns all sessions grouped by date with W/L totals
- New **BACKTEST** tab in NHL Predictor UI with two sub-tabs:
  - **Pick Games**: date picker (past 10 days), game cards with model prob bars and LEAN/STRONG LEAN badges, pick buttons for each team, **Reveal Results** button that scores picks and shows actual scores + WIN/LOSS
  - **Backtest History**: all past sessions collapsible by date, per-pick rows with matchup/score/model prob, running win rate
