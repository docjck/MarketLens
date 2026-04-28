# nhl_router.py — NHL predictions vs odds divergence (Updated for Playoffs)

import math
import os
import sqlite3
from collections import defaultdict
from datetime import datetime, date as date_type, timezone, timedelta
from typing import List

import httpx
from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, field_validator

router = APIRouter(prefix="/nhl", tags=["nhl"])

NHL_BASE = "https://api-web.nhle.com/v1"
ODDS_BASE = "https://api.the-odds-api.com/v4"
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")

EDGE_FLAG   = 0.05   # flag if model vs market diverges by 5%+
EDGE_STRONG = 0.10   # strong flag at 10%+
HOME_ADV    = 0.04   # home ice advantage

DB_PATH = os.path.join(os.path.dirname(__file__), "watchlist.db")


# ─── Database ─────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_edge_picks():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS edge_picks (
                game_id       INTEGER PRIMARY KEY,
                date          TEXT NOT NULL,
                season_type   TEXT NOT NULL DEFAULT 'regular',
                home_abbrev   TEXT NOT NULL,
                away_abbrev   TEXT NOT NULL,
                home_name     TEXT NOT NULL,
                away_name     TEXT NOT NULL,
                edge_team     TEXT NOT NULL,
                edge_value    REAL NOT NULL,
                strong_flag   INTEGER NOT NULL DEFAULT 0,
                model_prob    REAL,
                implied_prob  REAL,
                home_ml       INTEGER,
                away_ml       INTEGER,
                start_utc     TEXT,
                actual_winner TEXT,
                result        TEXT NOT NULL DEFAULT 'PENDING',
                saved_at      TEXT DEFAULT (datetime('now'))
            )
        """)
        # Add season_type column if missing
        try:
            conn.execute("ALTER TABLE edge_picks ADD COLUMN season_type TEXT NOT NULL DEFAULT 'regular'")
        except sqlite3.OperationalError:
            pass  # Column already exists
        conn.commit()


def init_backtest_table():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS backtest_picks (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                session_date  TEXT NOT NULL,
                game_id       INTEGER NOT NULL,
                home_name     TEXT NOT NULL,
                away_name     TEXT NOT NULL,
                home_abbrev   TEXT NOT NULL,
                away_abbrev   TEXT NOT NULL,
                picked_team   TEXT NOT NULL,
                model_h_prob  REAL,
                model_a_prob  REAL,
                actual_winner TEXT,
                home_score    INTEGER,
                away_score    INTEGER,
                home_ml       INTEGER,
                away_ml       INTEGER,
                result        TEXT NOT NULL DEFAULT 'PENDING',
                saved_at      TEXT DEFAULT (datetime('now')),
                UNIQUE(session_date, game_id)
            )
        """)
        for col in ("home_ml", "away_ml"):
            try:
                conn.execute(f"ALTER TABLE backtest_picks ADD COLUMN {col} INTEGER")
            except sqlite3.OperationalError:
                pass
        conn.commit()


init_edge_picks()
init_backtest_table()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def poisson_pmf(k: int, lam: float) -> float:
    """Poisson probability mass function P(X=k) for λ=lam."""
    if k < 0 or lam <= 0:
        return 0.0
    return (lam ** k) * math.exp(-lam) / math.factorial(k)


def model_over_prob(expected_total: float, line: float) -> float:
    """
    P(total goals > line) using a Poisson model.
    Line is typically X.5 so threshold = floor(line) + 1.
    """
    threshold = int(line) + 1
    p_under = sum(poisson_pmf(k, expected_total) for k in range(threshold))
    return round(max(0.01, min(0.99, 1 - p_under)), 4)


def moneyline_to_prob(ml: int) -> float:
    """Convert American moneyline to raw implied probability."""
    if ml > 0:
        return 100 / (ml + 100)
    return abs(ml) / (abs(ml) + 100)


def get_playoff_series_state(game: dict) -> dict | None:
    """Extract playoff series state from game data if available."""
    series = game.get("seriesStatus")
    if not series:
        return None
    try:
        parts = str(series).split()
        for part in parts:
            if "-" in part and len(part) == 3:
                h_w, a_w = map(int, part.split("-"))
                return {"home_wins": h_w, "away_wins": a_w}
    except:
        pass
    return None


def model_home_prob(home: dict, away: dict, series_state: dict = None) -> float:
    """
    Simple model: season win%, GF/GA differential, last-10 form, home ice.
    For playoffs: also considers series state (momentum).
    Returns estimated home win probability clamped to [0.20, 0.80].
    """
    hw = home.get("wins", 0)
    hl = home.get("losses", 0) + home.get("otLosses", 0)
    aw = away.get("wins", 0)
    al = away.get("losses", 0) + away.get("otLosses", 0)

    h_pct = hw / (hw + hl) if (hw + hl) > 0 else 0.5
    a_pct = aw / (aw + al) if (aw + al) > 0 else 0.5
    total = h_pct + a_pct
    h_prob = (h_pct / total) if total > 0 else 0.5

    # GF/GA per game differential
    hgp = max(home.get("gamesPlayed", 1), 1)
    agp = max(away.get("gamesPlayed", 1), 1)
    h_gf = home.get("goalFor", 0) / hgp
    h_ga = home.get("goalAgainst", 0) / hgp
    a_gf = away.get("goalFor", 0) / agp
    a_ga = away.get("goalAgainst", 0) / agp
    h_prob += ((h_gf - a_ga) - (a_gf - h_ga)) * 0.02

    # Last-10 form
    h_l10 = home.get("l10Wins", 0)
    a_l10 = away.get("l10Wins", 0)
    h_prob += (h_l10 - a_l10) / 10 * 0.04

    # Home ice
    h_prob += HOME_ADV

    # Playoff series context: if series_state provided, adjust for series momentum
    if series_state:
        h_wins = series_state.get("home_wins", 0)
        a_wins = series_state.get("away_wins", 0)
        # Team leading in series gets +3% confidence, trailing team gets -3%
        if h_wins > a_wins:
            h_prob += 0.03
        elif a_wins > h_wins:
            h_prob -= 0.03

    return round(max(0.20, min(0.80, h_prob)), 4)


def detect_season_type(schedule_data: dict) -> str:
    """
    Detect if games are regular season (gameType 2) or playoffs (gameType 3).
    Returns 'regular', 'playoff', or None.
    """
    game_types = set()
    for week in schedule_data.get("gameWeek", []):
        for g in week.get("games", []):
            game_types.add(g.get("gameType"))

    if game_types == {2}:
        return "regular"
    elif game_types == {3}:
        return "playoff"
    return None


def ml_to_units(ml: int | None, result: str, model_prob: float | None = None) -> float | None:
    """
    Calculate unit P&L for one pick.
    WIN  with real ML  -> payout based on moneyline
    WIN  without ML    -> fair-value payout from model_prob (fallback)
    LOSS               -> -1.0
    PENDING or no data -> None
    """
    if result == "PENDING":
        return None
    if result == "LOSS":
        return -1.0
    if result != "WIN":
        return None
    if ml is not None:
        if ml == 0:
            return None
        if ml > 0:
            return round(ml / 100, 4)
        else:
            return round(100 / abs(ml), 4)
    if model_prob is not None and 0 < model_prob < 1:
        model_prob = max(0.20, min(0.80, model_prob))
        return round((1 - model_prob) / model_prob, 4)
    return None


# ─── Pydantic Models ──────────────────────────────────────────────────────────

class BacktestPick(BaseModel):
    game_id: int
    picked_team: str
    home_name: str
    away_name: str
    home_abbrev: str
    away_abbrev: str
    model_home_prob: float
    model_away_prob: float
    home_ml: int | None = None
    away_ml: int | None = None

    @field_validator("picked_team")
    @classmethod
    def validate_picked_team(cls, v: str) -> str:
        if v not in ("home", "away"):
            raise ValueError("picked_team must be 'home' or 'away'")
        return v


class BacktestScoreRequest(BaseModel):
    date: str
    picks: List[BacktestPick]

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        try:
            date_type.fromisoformat(v)
        except ValueError:
            raise ValueError("Invalid date format, expected YYYY-MM-DD")
        return v


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/predictions")
async def get_todays_predictions():
    """Return model predictions + live odds for today's NHL games (regular season and playoffs)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        # Standings
        try:
            resp = await client.get(f"{NHL_BASE}/standings/now")
            resp.raise_for_status()
            standings_raw = resp.json().get("standings", [])
        except Exception as e:
            return {"error": f"Standings fetch failed: {e}", "games": [], "game_count": 0,
                    "odds_available": False, "ou_available": False}

        team_stats: dict = {}
        for t in standings_raw:
            abbrev = t.get("teamAbbrev", {}).get("default", "")
            if abbrev:
                team_stats[abbrev] = t

        # Schedule
        try:
            resp = await client.get(f"{NHL_BASE}/schedule/{today}")
            resp.raise_for_status()
            schedule = resp.json()
        except Exception as e:
            return {"error": f"Schedule fetch failed: {e}", "games": [], "game_count": 0,
                    "odds_available": False, "ou_available": False}

        season_type = detect_season_type(schedule)
        games_raw = []
        for week in schedule.get("gameWeek", []):
            for g in week.get("games", []):
                if g.get("gameType") in (2, 3) and g.get("startTimeUTC", "").startswith(today):
                    games_raw.append(g)

        # Live H2H odds
        odds_lookup: dict = {}
        odds_available = False
        odds_error = None
        if ODDS_API_KEY:
            try:
                odds_resp = await client.get(
                    f"{ODDS_BASE}/sports/icehockey_nhl/odds/",
                    params={"apiKey": ODDS_API_KEY, "regions": "us", "markets": "h2h", "oddsFormat": "american"},
                )
                if odds_resp.status_code == 200:
                    for event in odds_resp.json():
                        e_home = event.get("home_team", "")
                        e_away = event.get("away_team", "")
                        for book in event.get("bookmakers", [])[:1]:
                            for market in book.get("markets", []):
                                if market["key"] == "h2h":
                                    mls = {o["name"]: o["price"] for o in market["outcomes"]}
                                    odds_lookup[f"{e_home}|{e_away}"] = {
                                        "home_team": e_home, "away_team": e_away,
                                        "home_ml": mls.get(e_home), "away_ml": mls.get(e_away),
                                    }
                    odds_available = len(odds_lookup) > 0
                else:
                    odds_error = f"Odds API returned {odds_resp.status_code}"
            except Exception as e:
                odds_error = str(e)

        # Live O/U odds
        ou_lookup: dict = {}
        ou_available = False
        if ODDS_API_KEY:
            try:
                ou_resp = await client.get(
                    f"{ODDS_BASE}/sports/icehockey_nhl/odds/",
                    params={"apiKey": ODDS_API_KEY, "regions": "us", "markets": "totals", "oddsFormat": "american"},
                )
                if ou_resp.status_code == 200:
                    for event in ou_resp.json():
                        e_home = event.get("home_team", "")
                        e_away = event.get("away_team", "")
                        for book in event.get("bookmakers", [])[:1]:
                            for market in book.get("markets", []):
                                if market["key"] == "totals":
                                    over  = next((o for o in market["outcomes"] if o["name"] == "Over"),  None)
                                    under = next((o for o in market["outcomes"] if o["name"] == "Under"), None)
                                    if over:
                                        ou_lookup[f"{e_home}|{e_away}"] = {
                                            "line":      over.get("point"),
                                            "over_ml":   over.get("price"),
                                            "under_ml":  under.get("price") if under else None,
                                        }
                    ou_available = len(ou_lookup) > 0
            except Exception:
                pass

        # Build results
        results = []
        for g in games_raw:
            h_abbrev = g.get("homeTeam", {}).get("abbrev", "")
            a_abbrev = g.get("awayTeam", {}).get("abbrev", "")
            h_place  = g.get("homeTeam", {}).get("placeName", {}).get("default", h_abbrev)
            a_place  = g.get("awayTeam", {}).get("placeName", {}).get("default", a_abbrev)
            h_common = g.get("homeTeam", {}).get("commonName", {}).get("default", "")
            a_common = g.get("awayTeam", {}).get("commonName", {}).get("default", "")

            h_stats = team_stats.get(h_abbrev, {})
            a_stats = team_stats.get(a_abbrev, {})

            series_state = get_playoff_series_state(g) if g.get("gameType") == 3 else None
            model_h = model_home_prob(h_stats, a_stats, series_state)
            model_a = round(1 - model_h, 4)

            hgp = max(h_stats.get("gamesPlayed", 1), 1)
            agp = max(a_stats.get("gamesPlayed", 1), 1)

            # H2H odds match
            home_ml = away_ml = implied_h = implied_a = None
            for key, od in odds_lookup.items():
                if h_place.lower() in od["home_team"].lower() and a_place.lower() in od["away_team"].lower():
                    home_ml = od["home_ml"]
                    away_ml = od["away_ml"]
                    break
            if home_ml is not None and away_ml is not None:
                raw_h = moneyline_to_prob(int(home_ml))
                raw_a = moneyline_to_prob(int(away_ml))
                vig = raw_h + raw_a
                if vig:
                    implied_h = round(raw_h / vig, 4)
                    implied_a = round(raw_a / vig, 4)

            home_edge = round(model_h - implied_h, 4) if implied_h is not None else None
            away_edge = round(model_a - implied_a, 4) if implied_a is not None else None
            flagged   = home_edge is not None and abs(home_edge) >= EDGE_FLAG
            strong    = home_edge is not None and abs(home_edge) >= EDGE_STRONG

            # O/U odds match
            ou_line = over_ml = under_ml = model_expected = model_over_p = implied_over_p = ou_edge = None
            ou_flagged = ou_strong = False
            for key, od in ou_lookup.items():
                if h_place.lower() in key.lower() and a_place.lower() in key.lower():
                    ou_line   = od["line"]
                    over_ml   = od["over_ml"]
                    under_ml  = od["under_ml"]
                    break
            if ou_line is not None:
                h_gf = h_stats.get("goalFor", 0) / hgp
                a_gf = a_stats.get("goalFor", 0) / agp
                model_expected = round((h_gf + a_gf), 2)
                model_over_p   = model_over_prob(model_expected, ou_line)
                if over_ml is not None:
                    raw_over  = moneyline_to_prob(int(over_ml))
                    raw_under = moneyline_to_prob(int(under_ml)) if under_ml is not None else None
                    vig_ou = (raw_over + raw_under) if raw_under is not None else raw_over * 2
                    implied_over_p = round(raw_over / vig_ou, 4) if vig_ou else None
                if implied_over_p is not None:
                    ou_edge   = round(model_over_p - implied_over_p, 4)
                    ou_flagged = abs(ou_edge) >= EDGE_FLAG
                    ou_strong  = abs(ou_edge) >= EDGE_STRONG

            results.append({
                "game_id":           g.get("id"),
                "start_utc":         g.get("startTimeUTC", ""),
                "season_type":       "playoff" if g.get("gameType") == 3 else "regular",
                "series_state":      series_state,
                "home_abbrev":       h_abbrev,
                "away_abbrev":       a_abbrev,
                "home_name":         f"{h_place} {h_common}".strip(),
                "away_name":         f"{a_place} {a_common}".strip(),
                "home_record":       f"{h_stats.get('wins','?')}-{h_stats.get('losses','?')}-{h_stats.get('otLosses','?')}",
                "away_record":       f"{a_stats.get('wins','?')}-{a_stats.get('losses','?')}-{a_stats.get('otLosses','?')}",
                "home_l10":          h_stats.get("l10Wins"),
                "away_l10":          a_stats.get("l10Wins"),
                "home_gf_pg":        round(h_stats.get("goalFor", 0) / hgp, 2),
                "away_gf_pg":        round(a_stats.get("goalFor", 0) / agp, 2),
                "model_home_prob":   model_h,
                "model_away_prob":   model_a,
                "implied_home_prob": implied_h,
                "implied_away_prob": implied_a,
                "home_ml":           home_ml,
                "away_ml":           away_ml,
                "home_edge":         home_edge,
                "away_edge":         away_edge,
                "flagged":           flagged,
                "strong_flag":       strong,
                "ou_line":           ou_line,
                "over_ml":           over_ml,
                "under_ml":          under_ml,
                "model_expected":    model_expected,
                "model_over_prob":   model_over_p,
                "implied_over_prob": implied_over_p,
                "ou_edge":           ou_edge,
                "ou_flagged":        ou_flagged,
                "ou_strong":         ou_strong,
            })

        results.sort(key=lambda x: (
            x["strong_flag"] or x["ou_strong"],
            x["flagged"] or x["ou_flagged"],
        ), reverse=True)

        return {
            "date":            today,
            "season_type":     season_type,
            "game_count":      len(results),
            "games":           results,
            "odds_available":  odds_available,
            "ou_available":    ou_available,
            "odds_error":      odds_error,
        }


@router.get("/backtest/games/{date}")
async def get_backtest_games(date: str = Path(..., pattern=r"^\d{4}-\d{2}-\d{2}$")):
    """Return model predictions for a past date — both regular season and playoff games."""
    try:
        req_dt = date_type.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date")

    today = datetime.now(timezone.utc).date()
    if req_dt >= today:
        raise HTTPException(status_code=400, detail="Date must be in the past")

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        # Standings
        try:
            resp = await client.get(f"{NHL_BASE}/standings/{date}")
            resp.raise_for_status()
            if len(resp.content) > 2 * 1024 * 1024:
                return {"error": "Standings response too large", "games": []}
            standings_raw = resp.json().get("standings", [])
        except Exception as e:
            return {"error": f"Standings fetch failed: {e}", "games": []}

        team_stats: dict = {}
        for t in standings_raw:
            abbrev = t.get("teamAbbrev", {}).get("default", "")
            if abbrev:
                team_stats[abbrev] = t

        # Schedule
        try:
            resp = await client.get(f"{NHL_BASE}/schedule/{date}")
            resp.raise_for_status()
            schedule = resp.json()
        except Exception as e:
            return {"error": f"Schedule fetch failed: {e}", "games": []}

        # Auto-detect season type (regular or playoff)
        season_type = detect_season_type(schedule)
        if not season_type:
            return {"error": "Could not detect season type (no RS or playoff games found)", "games": []}

        game_type_filter = 3 if season_type == "playoff" else 2

        games_raw = []
        for week in schedule.get("gameWeek", []):
            for g in week.get("games", []):
                if g.get("gameType") == game_type_filter and g.get("startTimeUTC", "").startswith(date):
                    games_raw.append(g)

        # Historical odds (optional)
        hist_odds_lookup: dict = {}
        if ODDS_API_KEY:
            try:
                odds_resp = await client.get(
                    f"{ODDS_BASE}/historical/sports/icehockey_nhl/odds/",
                    params={
                        "apiKey": ODDS_API_KEY,
                        "regions": "us",
                        "markets": "h2h",
                        "oddsFormat": "american",
                        "date": f"{date}T12:00:00Z",
                    },
                )
                if odds_resp.status_code == 200:
                    for event in odds_resp.json().get("data", []):
                        e_home = event.get("home_team", "")
                        e_away = event.get("away_team", "")
                        key = f"{e_home}|{e_away}"
                        for book in event.get("bookmakers", []):
                            matched = False
                            for market in book.get("markets", []):
                                if market["key"] == "h2h":
                                    mls = {o["name"]: o["price"] for o in market["outcomes"]}
                                    hist_odds_lookup[key] = {
                                        "home_team": e_home, "away_team": e_away,
                                        "home_ml": mls.get(e_home),
                                        "away_ml": mls.get(e_away),
                                    }
                                    matched = True
                                    break
                            if matched:
                                break
            except Exception:
                pass

        results = []
        for g in games_raw:
            h_abbrev = g.get("homeTeam", {}).get("abbrev", "")
            a_abbrev = g.get("awayTeam", {}).get("abbrev", "")
            h_place  = g.get("homeTeam", {}).get("placeName", {}).get("default", h_abbrev)
            a_place  = g.get("awayTeam", {}).get("placeName", {}).get("default", a_abbrev)
            h_common = g.get("homeTeam", {}).get("commonName", {}).get("default", "")
            a_common = g.get("awayTeam", {}).get("commonName", {}).get("default", "")

            h_stats = team_stats.get(h_abbrev, {})
            a_stats = team_stats.get(a_abbrev, {})

            # Get playoff series state if available
            series_state = get_playoff_series_state(g)

            model_h    = model_home_prob(h_stats, a_stats, series_state)
            model_a    = round(1 - model_h, 4)
            confidence = round(abs(model_h - 0.5), 4)

            # Match odds
            bt_home_ml = bt_away_ml = None
            for key, od in hist_odds_lookup.items():
                if h_place.lower() in od["home_team"].lower() and a_place.lower() in od["away_team"].lower():
                    bt_home_ml = od["home_ml"]
                    bt_away_ml = od["away_ml"]
                    break

            results.append({
                "game_id":         g.get("id"),
                "start_utc":       g.get("startTimeUTC", ""),
                "home_abbrev":     h_abbrev,
                "away_abbrev":     a_abbrev,
                "home_name":       f"{h_place} {h_common}".strip(),
                "away_name":       f"{a_place} {a_common}".strip(),
                "home_record":     f"{h_stats.get('wins','?')}-{h_stats.get('losses','?')}-{h_stats.get('otLosses','?')}",
                "away_record":     f"{a_stats.get('wins','?')}-{a_stats.get('losses','?')}-{a_stats.get('otLosses','?')}",
                "model_home_prob": model_h,
                "model_away_prob": model_a,
                "confidence":      confidence,
                "home_ml":         bt_home_ml,
                "away_ml":         bt_away_ml,
                "series_state":    series_state,
            })

        results.sort(key=lambda x: x["confidence"], reverse=True)

        return {"date": date, "season_type": season_type, "game_count": len(results), "games": results}


@router.post("/backtest/score")
async def score_backtest(req: BacktestScoreRequest):
    """Score a backtest session. Works for both regular season and playoff games."""
    try:
        req_dt = date_type.fromisoformat(req.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

    if not req.picks:
        raise HTTPException(status_code=400, detail="No picks to score")

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        try:
            resp = await client.get(f"{NHL_BASE}/schedule/{req.date}")
            resp.raise_for_status()
            schedule = resp.json()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch schedule: {e}")

        games_by_id = {}
        for week in schedule.get("gameWeek", []):
            for g in week.get("games", []):
                if g.get("gameType") in (2, 3):  # Regular season or playoff
                    games_by_id[g.get("id")] = {
                        "home_score": g.get("homeTeam", {}).get("score", 0),
                        "away_score": g.get("awayTeam", {}).get("score", 0),
                    }

    scored = []
    with get_db() as conn:
        for pick in req.picks:
            game_id = pick.game_id
            if game_id not in games_by_id:
                continue

            game = games_by_id[game_id]
            home_score = game["home_score"]
            away_score = game["away_score"]

            if home_score > away_score:
                actual_winner = "home"
            elif away_score > home_score:
                actual_winner = "away"
            else:
                actual_winner = None

            if actual_winner is None:
                result = "PENDING"
            elif actual_winner == pick.picked_team:
                result = "WIN"
            else:
                result = "LOSS"

            picked_ml = pick.home_ml if pick.picked_team == "home" else pick.away_ml
            model_prob = pick.model_home_prob if pick.picked_team == "home" else pick.model_away_prob
            unit_result = ml_to_units(picked_ml, result, model_prob=model_prob)

            conn.execute("""
                INSERT OR REPLACE INTO backtest_picks
                    (session_date, game_id, home_name, away_name, home_abbrev, away_abbrev,
                     picked_team, model_h_prob, model_a_prob, actual_winner,
                     home_score, away_score, home_ml, away_ml, result)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                req.date, pick.game_id, pick.home_name, pick.away_name,
                pick.home_abbrev, pick.away_abbrev,
                pick.picked_team, pick.model_home_prob, pick.model_away_prob,
                actual_winner, home_score, away_score,
                pick.home_ml, pick.away_ml, result,
            ))

            scored.append({
                "game_id":       pick.game_id,
                "home_name":     pick.home_name,
                "away_name":     pick.away_name,
                "picked_team":   pick.picked_team,
                "model_prob":    model_prob,
                "actual_winner": actual_winner,
                "home_score":    home_score,
                "away_score":    away_score,
                "result":        result,
                "home_ml":       pick.home_ml,
                "away_ml":       pick.away_ml,
                "unit_result":   unit_result,
            })

        conn.commit()

    return {
        "date": req.date,
        "picks_scored": len(scored),
        "scored": scored,
    }


@router.get("/edge-history")
async def get_edge_history():
    """Return all saved edge picks (regular season and playoff) grouped by date, with unit P&L."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Resolve pending picks from prior dates
    with get_db() as conn:
        pending_rows = conn.execute(
            "SELECT game_id, date, edge_team, home_name, away_name FROM edge_picks "
            "WHERE result = 'PENDING' AND date < ?", (today,)
        ).fetchall()

    pending = [dict(r) for r in pending_rows]
    if pending:
        dates = list({p["date"] for p in pending})
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            for d in dates:
                try:
                    resp = await client.get(f"{NHL_BASE}/score/{d}")
                    if resp.status_code != 200:
                        continue
                    score_games = resp.json().get("games", [])
                except Exception:
                    continue

                with get_db() as conn:
                    for sg in score_games:
                        if sg.get("gameState") not in ("OFF", "FINAL"):
                            continue
                        gid = sg.get("id")
                        h_score = sg.get("homeTeam", {}).get("score") or 0
                        a_score = sg.get("awayTeam", {}).get("score") or 0
                        if h_score == a_score:
                            continue
                        actual_winner = "home" if h_score > a_score else "away"
                        existing = conn.execute(
                            "SELECT game_id, edge_team FROM edge_picks "
                            "WHERE game_id = ? AND result = 'PENDING'", (gid,)
                        ).fetchone()
                        if existing:
                            result = "WIN" if existing["edge_team"] == actual_winner else "LOSS"
                            conn.execute(
                                "UPDATE edge_picks SET actual_winner = ?, result = ? WHERE game_id = ?",
                                (actual_winner, result, gid)
                            )
                    conn.commit()

    # Reload all picks
    with get_db() as conn:
        rows = conn.execute(
            "SELECT game_id, date, season_type, home_abbrev, away_abbrev, home_name, away_name, "
            "edge_team, edge_value, strong_flag, model_prob, implied_prob, "
            "home_ml, away_ml, start_utc, actual_winner, result "
            "FROM edge_picks ORDER BY date DESC, start_utc ASC"
        ).fetchall()

    picks = [dict(r) for r in rows]

    # Summary totals
    total_wins    = sum(1 for p in picks if p["result"] == "WIN")
    total_losses  = sum(1 for p in picks if p["result"] == "LOSS")
    total_pending = sum(1 for p in picks if p["result"] == "PENDING")
    total         = len(picks)
    win_rate      = round(total_wins / (total_wins + total_losses), 4) if (total_wins + total_losses) > 0 else None

    # Group by date with season type
    by_date: dict = {}
    for p in picks:
        d = p["date"]
        if d not in by_date:
            by_date[d] = []
        by_date[d].append(p)

    picks_by_date = [
        {
            "date":    d,
            "season_type": by_date[d][0].get("season_type", "regular") if by_date[d] else "regular",
            "picks":   by_date[d],
            "wins":    sum(1 for p in by_date[d] if p["result"] == "WIN"),
            "losses":  sum(1 for p in by_date[d] if p["result"] == "LOSS"),
            "pending": sum(1 for p in by_date[d] if p["result"] == "PENDING"),
        }
        for d in sorted(by_date.keys(), reverse=True)
    ]

    # Unit P&L
    all_unit_results = []
    for day in picks_by_date:
        day_units = 0.0
        for p in day["picks"]:
            edge_ml = p["home_ml"] if p["edge_team"] == "home" else p["away_ml"]
            ur = ml_to_units(edge_ml, p["result"], model_prob=p.get("model_prob"))
            p["unit_result"] = ur
            if ur is not None:
                day_units = round(day_units + ur, 4)
                all_unit_results.append({"date": p["date"], "units": ur})
        day["net_units"] = day_units

    all_unit_results.sort(key=lambda x: x["date"])
    cumulative_units = []
    running = 0.0
    for entry in all_unit_results:
        running = round(running + entry["units"], 4)
        cumulative_units.append({"date": entry["date"], "cumulative": running})

    total_units = round(sum(
        p["unit_result"] for p in picks if p.get("unit_result") is not None
    ), 4)
    total_units_risked = sum(1 for p in picks if p["result"] in ("WIN", "LOSS"))

    return {
        "picks_by_date":    picks_by_date,
        "cumulative_units": cumulative_units,
        "totals": {
            "total":        total,
            "wins":         total_wins,
            "losses":       total_losses,
            "pending":      total_pending,
            "win_rate":     win_rate,
            "units_risked": total_units_risked,
            "net_units":    total_units,
        },
    }


@router.get("/backtest/history")
async def get_backtest_history():
    """Return all saved backtest picks grouped by session date."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT session_date, game_id, home_abbrev, away_abbrev, home_name, away_name, "
            "picked_team, model_h_prob, model_a_prob, actual_winner, result, "
            "home_score, away_score, home_ml, away_ml "
            "FROM backtest_picks ORDER BY session_date DESC"
        ).fetchall()

    picks = [dict(r) for r in rows]

    total_wins    = sum(1 for p in picks if p["result"] == "WIN")
    total_losses  = sum(1 for p in picks if p["result"] == "LOSS")
    total_pending = sum(1 for p in picks if p["result"] == "PENDING")
    total         = len(picks)
    win_rate      = round(total_wins / (total_wins + total_losses), 4) if (total_wins + total_losses) > 0 else None

    by_date: dict = {}
    for p in picks:
        d = p["session_date"]
        if d not in by_date:
            by_date[d] = []
        by_date[d].append(p)

    sessions = [
        {
            "session_date": d,
            "picks":        by_date[d],
            "wins":         sum(1 for p in by_date[d] if p["result"] == "WIN"),
            "losses":       sum(1 for p in by_date[d] if p["result"] == "LOSS"),
            "pending":      sum(1 for p in by_date[d] if p["result"] == "PENDING"),
        }
        for d in sorted(by_date.keys(), reverse=True)
    ]

    all_unit_results = []
    for session in sessions:
        sess_units = 0.0
        for p in session["picks"]:
            picked_ml = p["home_ml"] if p["picked_team"] == "home" else p["away_ml"]
            model_prob = p["model_h_prob"] if p["picked_team"] == "home" else p["model_a_prob"]
            ur = ml_to_units(picked_ml, p["result"], model_prob=model_prob)
            p["unit_result"] = ur
            if ur is not None:
                sess_units = round(sess_units + ur, 4)
                all_unit_results.append({"date": p["session_date"], "units": ur})
        session["net_units"] = sess_units

    all_unit_results.sort(key=lambda x: x["date"])
    cumulative_units = []
    running = 0.0
    for entry in all_unit_results:
        running = round(running + entry["units"], 4)
        cumulative_units.append({"date": entry["date"], "cumulative": running})

    total_units = round(sum(
        p["unit_result"]
        for sess in sessions for p in sess["picks"]
        if p.get("unit_result") is not None
    ), 4)
    total_units_risked = sum(1 for p in picks if p["result"] in ("WIN", "LOSS"))

    return {
        "sessions":         sessions,
        "cumulative_units": cumulative_units,
        "totals": {
            "total":        total,
            "wins":         total_wins,
            "losses":       total_losses,
            "pending":      total_pending,
            "win_rate":     win_rate,
            "units_risked": total_units_risked,
            "net_units":    total_units,
        },
    }


@router.get("/backtest/date-range/{start_date}/{end_date}")
async def backtest_date_range(
    start_date: str = Path(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str = Path(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
):
    """Backtest model predictions on all games in a date range."""
    try:
        start_dt = date_type.fromisoformat(start_date)
        end_dt = date_type.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format (YYYY-MM-DD)")

    today = datetime.now(timezone.utc).date()
    if end_dt > today:
        raise HTTPException(status_code=400, detail="End date cannot be in the future")
    if start_dt > end_dt:
        raise HTTPException(status_code=400, detail="Start date must be before end date")

    date_range = (end_dt - start_dt).days
    if date_range > 90:
        raise HTTPException(status_code=400, detail="Date range too large (max 90 days)")

    all_games = []
    current_date = start_dt

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        while current_date <= end_dt:
            date_str = current_date.isoformat()

            try:
                # Standings
                standings_resp = await client.get(f"{NHL_BASE}/standings/{date_str}")
                standings_resp.raise_for_status()
                standings = standings_resp.json().get("standings", [])

                # Schedule
                schedule_resp = await client.get(f"{NHL_BASE}/schedule/{date_str}")
                schedule_resp.raise_for_status()
                schedule = schedule_resp.json()

                # Score
                score_resp = await client.get(f"{NHL_BASE}/score/{date_str}")
                score_resp.raise_for_status()
                scores = score_resp.json().get("games", [])

                # Parse standings
                team_stats = {}
                for t in standings:
                    abbrev = t.get("teamAbbrev", {}).get("default", "")
                    if abbrev:
                        team_stats[abbrev] = t

                # Detect season type
                season_type = detect_season_type(schedule)
                if not season_type:
                    current_date += timedelta(days=1)
                    continue

                game_type_filter = 3 if season_type == "playoff" else 2
                scores_by_id = {g.get("id"): g for g in scores if g.get("gameType") == game_type_filter}

                # Parse games with scores
                for week in schedule.get("gameWeek", []):
                    for g in week.get("games", []):
                        if g.get("gameType") != game_type_filter:
                            continue

                        game_id = g.get("id")
                        score_data = scores_by_id.get(game_id)
                        if not score_data:
                            continue

                        h_abbrev = g.get("homeTeam", {}).get("abbrev", "")
                        a_abbrev = g.get("awayTeam", {}).get("abbrev", "")
                        h_place = g.get("homeTeam", {}).get("placeName", {}).get("default", "")
                        a_place = g.get("awayTeam", {}).get("placeName", {}).get("default", "")
                        h_common = g.get("homeTeam", {}).get("commonName", {}).get("default", "")
                        a_common = g.get("awayTeam", {}).get("commonName", {}).get("default", "")

                        h_stats = team_stats.get(h_abbrev, {})
                        a_stats = team_stats.get(a_abbrev, {})

                        series_state = get_playoff_series_state(g) if g.get("gameType") == 3 else None
                        model_h = model_home_prob(h_stats, a_stats, series_state)
                        model_a = round(1 - model_h, 4)

                        h_score = score_data.get("homeTeam", {}).get("score", 0)
                        a_score = score_data.get("awayTeam", {}).get("score", 0)

                        if h_score == a_score:
                            actual_winner = None
                        else:
                            actual_winner = "home" if h_score > a_score else "away"

                        all_games.append({
                            "date": date_str,
                            "game_id": game_id,
                            "home_abbrev": h_abbrev,
                            "away_abbrev": a_abbrev,
                            "home_name": f"{h_place} {h_common}".strip(),
                            "away_name": f"{a_place} {a_common}".strip(),
                            "model_home_prob": model_h,
                            "model_away_prob": model_a,
                            "home_score": h_score,
                            "away_score": a_score,
                            "actual_winner": actual_winner,
                            "season_type": season_type,
                        })

            except Exception:
                pass

            current_date += timedelta(days=1)

    # Score picks: model predicts the team with higher probability
    picks = []
    wins = 0
    losses = 0
    pending = 0
    unit_results = []

    for game in all_games:
        if game["actual_winner"] is None:
            result = "PENDING"
            pending += 1
        else:
            if game["model_home_prob"] > game["model_away_prob"]:
                picked_team = "home"
                model_prob = game["model_home_prob"]
            else:
                picked_team = "away"
                model_prob = game["model_away_prob"]

            if picked_team == game["actual_winner"]:
                result = "WIN"
                wins += 1
            else:
                result = "LOSS"
                losses += 1

            if model_prob > 0 and model_prob < 1:
                model_prob = max(0.20, min(0.80, model_prob))
                unit_result = round((1 - model_prob) / model_prob, 4)
            else:
                unit_result = None

            if unit_result is not None:
                unit_results.append(unit_result)

        picks.append({
            "date": game["date"],
            "game_id": game["game_id"],
            "home_name": game["home_name"],
            "away_name": game["away_name"],
            "home_score": game["home_score"],
            "away_score": game["away_score"],
            "model_home_prob": game["model_home_prob"],
            "model_away_prob": game["model_away_prob"],
            "picked_team": "home" if game["model_home_prob"] > game["model_away_prob"] else "away",
            "model_prob": max(game["model_home_prob"], game["model_away_prob"]),
            "actual_winner": game["actual_winner"],
            "result": result,
            "unit_result": unit_results[-1] if unit_results and len(unit_results) > 0 and result != "PENDING" else None,
            "season_type": game["season_type"],
        })

    total = wins + losses
    win_rate = round(wins / total, 4) if total > 0 else None
    total_units = round(sum(u for u in unit_results if u is not None), 4) if unit_results else 0.0

    return {
        "date_range": {
            "start": start_date,
            "end": end_date,
            "days": date_range,
        },
        "picks": picks,
        "totals": {
            "total_games": total + pending,
            "wins": wins,
            "losses": losses,
            "pending": pending,
            "win_rate": win_rate,
            "total_units": total_units,
            "units_per_game": round(total_units / total, 4) if total > 0 else None,
        },
        "summary": f"Model: {wins}W-{losses}L ({win_rate*100 if win_rate else 0:.1f}%) | {total_units:+.2f} units over {total} resolved games"
    }


@router.get("/backtest/last-{days}-days")
async def backtest_last_days(days: int = Path(..., ge=1, le=90)):
    """Quick backtest of the last N days."""
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=days)
    return await backtest_date_range(start_date.isoformat(), end_date.isoformat())
