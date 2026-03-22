# nhl_router.py — NHL predictions vs odds divergence

import math
import os
import sqlite3
from collections import defaultdict
from datetime import datetime, date as date_type, timezone
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


def model_home_prob(home: dict, away: dict) -> float:
    """
    Simple model: season win%, GF/GA differential, last-10 form, home ice.
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

    return round(max(0.20, min(0.80, h_prob)), 4)


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
    # Only process WIN result; unknown results return None
    if result != "WIN":
        return None
    # WIN result with moneyline payout
    if ml is not None:
        # Guard against zero moneyline
        if ml == 0:
            return None
        if ml > 0:
            return round(ml / 100, 4)
        else:
            return round(100 / abs(ml), 4)
    # Fallback: fair-value payout from model probability
    # Clamp model_prob to [0.20, 0.80] to avoid extreme payouts
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

@router.get("/backtest/games/{date}")
async def get_backtest_games(date: str = Path(..., pattern=r"^\d{4}-\d{2}-\d{2}$")):
    """Return model predictions for a past date — no actual scores included."""
    try:
        req_dt = date_type.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date")

    today = datetime.now(timezone.utc).date()
    if req_dt >= today:
        raise HTTPException(status_code=400, detail="Date must be in the past")

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        # Historical standings for that date
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

        # Schedule for that date
        try:
            resp = await client.get(f"{NHL_BASE}/schedule/{date}")
            resp.raise_for_status()
            schedule = resp.json()
        except Exception as e:
            return {"error": f"Schedule fetch failed: {e}", "games": []}

        games_raw = []
        for week in schedule.get("gameWeek", []):
            for g in week.get("games", []):
                if g.get("gameType") == 2:
                    games_raw.append(g)

        # Historical odds (optional — paid Odds API tier required)
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
                pass  # odds unavailable — caller uses model prob fallback

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

            model_h    = model_home_prob(h_stats, a_stats)
            model_a    = round(1 - model_h, 4)
            confidence = round(abs(model_h - 0.5), 4)

            # Match odds by place name (same pattern as /predictions)
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
            })

        # Sort strongest model lean first
        results.sort(key=lambda x: x["confidence"], reverse=True)

        return {"date": date, "game_count": len(results), "games": results}
