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


init_edge_picks()


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


# ─── Predictions endpoint ─────────────────────────────────────────────────────

@router.get("/predictions")
async def get_predictions():
    """
    Return model predictions vs market odds for NHL games today.
    Flags games where the model diverges from implied odds by >5%.
    Automatically saves flagged games to edge_picks for result tracking.
    """
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:

        # 1. Standings — used for team stats
        try:
            resp = await client.get(f"{NHL_BASE}/standings/now")
            resp.raise_for_status()
            standings_raw = resp.json().get("standings", [])
        except Exception as e:
            return {"error": f"Standings fetch failed: {e}", "games": []}

        team_stats = {}
        for t in standings_raw:
            abbrev = t.get("teamAbbrev", {}).get("default", "")
            if abbrev:
                team_stats[abbrev] = t

        # 2. Today's schedule
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            resp = await client.get(f"{NHL_BASE}/schedule/{today}")
            resp.raise_for_status()
            schedule = resp.json()
        except Exception as e:
            return {"error": f"Schedule fetch failed: {e}", "games": []}

        games_raw = []
        for week in schedule.get("gameWeek", []):
            for g in week.get("games", []):
                if g.get("gameType") == 2:   # regular season only
                    games_raw.append(g)

        # 3. Odds (optional — only if ODDS_API_KEY is set)
        odds_lookup = {}   # key -> {"home_ml", "away_ml", "home_team", "away_team"}
        ou_lookup   = {}   # key -> {"line", "over_ml", "under_ml"}
        odds_error  = None
        if ODDS_API_KEY:
            try:
                resp = await client.get(
                    f"{ODDS_BASE}/sports/icehockey_nhl/odds/",
                    params={"apiKey": ODDS_API_KEY, "regions": "us", "markets": "h2h,totals", "oddsFormat": "american"},
                )
                if resp.status_code == 200:
                    if len(resp.content) > 5 * 1024 * 1024:
                        odds_error = "Odds API response was unexpectedly large"
                    else:
                        for event in resp.json():
                            e_home = event.get("home_team", "")
                            e_away = event.get("away_team", "")
                            key    = f"{e_home}|{e_away}"
                            # Search all bookmakers for each market — the first bookmaker
                            # may offer h2h but not totals (or vice versa)
                            h2h_done = totals_done = False
                            for book in event.get("bookmakers", []):
                                if h2h_done and totals_done:
                                    break
                                for market in book.get("markets", []):
                                    if not h2h_done and market["key"] == "h2h":
                                        mls = {o["name"]: o["price"] for o in market["outcomes"]}
                                        odds_lookup[key] = {
                                            "home_team": e_home,
                                            "away_team": e_away,
                                            "home_ml":   mls.get(e_home),
                                            "away_ml":   mls.get(e_away),
                                        }
                                        h2h_done = True
                                    elif not totals_done and market["key"] == "totals":
                                        pts = {o["name"]: o for o in market["outcomes"]}
                                        over  = pts.get("Over", {})
                                        under = pts.get("Under", {})
                                        if over.get("point") is not None:
                                            ou_lookup[key] = {
                                                "home_team": e_home,
                                                "away_team": e_away,
                                                "line":      over["point"],
                                                "over_ml":   over.get("price"),
                                                "under_ml":  under.get("price"),
                                            }
                                            totals_done = True
                else:
                    odds_error = f"Odds API returned status {resp.status_code}"
            except Exception as e:
                odds_error = "Failed to fetch odds data"

        # 4. Build predictions per game
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

            model_h = model_home_prob(h_stats, a_stats)
            model_a = round(1 - model_h, 4)

            # Odds matching: find event whose home/away team name contains the place name
            implied_h = None
            implied_a = None
            home_ml   = None
            away_ml   = None
            for key, od in odds_lookup.items():
                if h_place.lower() in od["home_team"].lower() and a_place.lower() in od["away_team"].lower():
                    home_ml = od["home_ml"]
                    away_ml = od["away_ml"]
                    break

            if home_ml is not None and away_ml is not None:
                raw_h = moneyline_to_prob(int(home_ml))
                raw_a = moneyline_to_prob(int(away_ml))
                vig   = raw_h + raw_a                         # remove vig
                implied_h = round(raw_h / vig, 4) if vig else None
                implied_a = round(raw_a / vig, 4) if vig else None

            home_edge  = round(model_h - implied_h, 4) if implied_h is not None else None
            away_edge  = round(model_a - implied_a, 4) if implied_a is not None else None
            flagged    = bool(home_edge is not None and abs(home_edge) >= EDGE_FLAG)
            strong     = bool(home_edge is not None and abs(home_edge) >= EDGE_STRONG)

            # Over/Under
            ou_line = over_ml = under_ml = None
            model_expected = model_over = implied_over = ou_edge = None
            ou_flagged = ou_strong = False

            for key, od in ou_lookup.items():
                if h_place.lower() in od["home_team"].lower() and a_place.lower() in od["away_team"].lower():
                    ou_line   = od.get("line")
                    over_ml   = od.get("over_ml")
                    under_ml  = od.get("under_ml")
                    break

            if ou_line is not None:
                model_expected = round(
                    h_stats.get("goalFor", 0) / max(h_stats.get("gamesPlayed", 1), 1) +
                    a_stats.get("goalFor", 0) / max(a_stats.get("gamesPlayed", 1), 1),
                    2,
                )
                model_over = model_over_prob(model_expected, ou_line)

                if over_ml is not None and under_ml is not None:
                    raw_o = moneyline_to_prob(int(over_ml))
                    raw_u = moneyline_to_prob(int(under_ml))
                    vig   = raw_o + raw_u
                    implied_over = round(raw_o / vig, 4) if vig else None

                if implied_over is not None:
                    ou_edge    = round(model_over - implied_over, 4)
                    ou_flagged = abs(ou_edge) >= EDGE_FLAG
                    ou_strong  = abs(ou_edge) >= EDGE_STRONG

            results.append({
                "game_id":           g.get("id"),
                "start_utc":         g.get("startTimeUTC", ""),
                "home_abbrev":       h_abbrev,
                "away_abbrev":       a_abbrev,
                "home_name":         f"{h_place} {h_common}".strip(),
                "away_name":         f"{a_place} {a_common}".strip(),
                "home_record":       f"{h_stats.get('wins','?')}-{h_stats.get('losses','?')}-{h_stats.get('otLosses','?')}",
                "away_record":       f"{a_stats.get('wins','?')}-{a_stats.get('losses','?')}-{a_stats.get('otLosses','?')}",
                "home_l10":          h_stats.get("l10Wins"),
                "away_l10":          a_stats.get("l10Wins"),
                "home_gf_pg":        round(h_stats.get("goalFor", 0) / max(h_stats.get("gamesPlayed", 1), 1), 2),
                "away_gf_pg":        round(a_stats.get("goalFor", 0) / max(a_stats.get("gamesPlayed", 1), 1), 2),
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
                # Over/Under
                "ou_line":           ou_line,
                "over_ml":           over_ml,
                "under_ml":          under_ml,
                "model_expected":    model_expected,
                "model_over_prob":   model_over,
                "implied_over_prob": implied_over,
                "ou_edge":           ou_edge,
                "ou_flagged":        ou_flagged,
                "ou_strong":         ou_strong,
            })

        # Sort: any edge flagged first, then by start time
        results.sort(key=lambda x: (not (x["flagged"] or x["ou_flagged"]), x["start_utc"]))

        # 5. Persist flagged games to edge_picks (INSERT OR IGNORE — safe to call on refresh)
        flagged_games = [g for g in results if g["flagged"] and g["game_id"] is not None]
        if flagged_games:
            with get_db() as conn:
                for g in flagged_games:
                    edge_team  = "home" if g["home_edge"] > 0 else "away"
                    edge_value = abs(g["home_edge"])
                    model_prob   = g["model_home_prob"]  if edge_team == "home" else g["model_away_prob"]
                    implied_prob = g["implied_home_prob"] if edge_team == "home" else g["implied_away_prob"]
                    conn.execute("""
                        INSERT OR IGNORE INTO edge_picks
                            (game_id, date, home_abbrev, away_abbrev, home_name, away_name,
                             edge_team, edge_value, strong_flag, model_prob, implied_prob,
                             home_ml, away_ml, start_utc)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        g["game_id"], today,
                        g["home_abbrev"], g["away_abbrev"],
                        g["home_name"],   g["away_name"],
                        edge_team, edge_value,
                        1 if g["strong_flag"] else 0,
                        model_prob, implied_prob,
                        g["home_ml"], g["away_ml"],
                        g["start_utc"],
                    ))
                conn.commit()

        return {
            "date":           today,
            "game_count":     len(results),
            "odds_available": bool(ODDS_API_KEY and odds_lookup),
            "ou_available":   bool(ODDS_API_KEY and ou_lookup),
            "odds_error":     odds_error,
            "games":          results,
        }


# ─── Edge history endpoint ────────────────────────────────────────────────────

@router.get("/edge-history")
async def get_edge_history():
    """
    Return all stored edge picks grouped by date with W/L results.
    Automatically resolves any PENDING picks from past dates using NHL score API.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Load all picks
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM edge_picks ORDER BY date DESC, start_utc"
        ).fetchall()
    picks = [dict(r) for r in rows]

    if not picks:
        return {
            "picks_by_date": [],
            "totals": {"total": 0, "wins": 0, "losses": 0, "pending": 0, "win_rate": None},
        }

    # Resolve PENDING picks for dates before today
    pending_past = [p for p in picks if p["result"] == "PENDING" and p["date"] < today]
    if pending_past:
        dates_to_check = list({p["date"] for p in pending_past})
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            for date in dates_to_check:
                try:
                    resp = await client.get(f"{NHL_BASE}/score/{date}")
                    if resp.status_code != 200:
                        continue
                    score_games = resp.json().get("games", [])
                    with get_db() as conn:
                        for sg in score_games:
                            state = sg.get("gameState", "")
                            if state not in ("OFF", "FINAL"):
                                continue
                            gid     = sg.get("id")
                            h_score = sg.get("homeTeam", {}).get("score") or 0
                            a_score = sg.get("awayTeam", {}).get("score") or 0
                            if h_score == a_score:
                                continue  # shouldn't happen for final games
                            actual_winner = "home" if h_score > a_score else "away"
                            existing = conn.execute(
                                "SELECT game_id, edge_team FROM edge_picks WHERE game_id = ? AND result = 'PENDING'",
                                (gid,)
                            ).fetchone()
                            if existing:
                                result = "WIN" if existing["edge_team"] == actual_winner else "LOSS"
                                conn.execute(
                                    "UPDATE edge_picks SET actual_winner = ?, result = ? WHERE game_id = ?",
                                    (actual_winner, result, gid)
                                )
                        conn.commit()
                except Exception:
                    pass

        # Reload after updates
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM edge_picks ORDER BY date DESC, start_utc"
            ).fetchall()
        picks = [dict(r) for r in rows]

    # Group by date
    by_date: dict = defaultdict(list)
    for p in picks:
        by_date[p["date"]].append(p)

    picks_by_date = []
    for date in sorted(by_date.keys(), reverse=True):
        day_picks = by_date[date]
        wins    = sum(1 for p in day_picks if p["result"] == "WIN")
        losses  = sum(1 for p in day_picks if p["result"] == "LOSS")
        pending = sum(1 for p in day_picks if p["result"] == "PENDING")
        picks_by_date.append({
            "date":    date,
            "picks":   day_picks,
            "wins":    wins,
            "losses":  losses,
            "pending": pending,
        })

    # Running totals
    total_wins    = sum(1 for p in picks if p["result"] == "WIN")
    total_losses  = sum(1 for p in picks if p["result"] == "LOSS")
    total_pending = sum(1 for p in picks if p["result"] == "PENDING")
    total_resolved = total_wins + total_losses
    win_rate = round(total_wins / total_resolved, 4) if total_resolved > 0 else None

    return {
        "picks_by_date": picks_by_date,
        "totals": {
            "total":   len(picks),
            "wins":    total_wins,
            "losses":  total_losses,
            "pending": total_pending,
            "win_rate": win_rate,
        },
    }


# ─── Backtest ─────────────────────────────────────────────────────────────────

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
                result        TEXT NOT NULL DEFAULT 'PENDING',
                saved_at      TEXT DEFAULT (datetime('now')),
                UNIQUE(session_date, game_id)
            )
        """)
        conn.commit()


init_backtest_table()


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
            })

        # Sort strongest model lean first
        results.sort(key=lambda x: x["confidence"], reverse=True)

        return {"date": date, "game_count": len(results), "games": results}


@router.post("/backtest/score")
async def score_backtest(req: BacktestScoreRequest):
    """Score a set of user picks against actual NHL results and persist to DB."""
    try:
        req_dt = date_type.fromisoformat(req.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date")

    today = datetime.now(timezone.utc).date()
    if req_dt >= today:
        raise HTTPException(status_code=400, detail="Date must be in the past")

    if not req.picks:
        raise HTTPException(status_code=400, detail="No picks provided")

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        try:
            resp = await client.get(f"{NHL_BASE}/score/{req.date}")
            resp.raise_for_status()
            score_games = resp.json().get("games", [])
        except Exception:
            raise HTTPException(status_code=500, detail="Failed to fetch game scores")

    score_lookup: dict = {}
    for sg in score_games:
        if sg.get("gameState") in ("OFF", "FINAL"):
            gid     = sg.get("id")
            h_score = sg.get("homeTeam", {}).get("score") or 0
            a_score = sg.get("awayTeam", {}).get("score") or 0
            if h_score != a_score:
                score_lookup[gid] = {
                    "home_score":    h_score,
                    "away_score":    a_score,
                    "actual_winner": "home" if h_score > a_score else "away",
                }

    scored = []
    with get_db() as conn:
        for pick in req.picks:
            score = score_lookup.get(pick.game_id)
            if score:
                actual_winner = score["actual_winner"]
                result        = "WIN" if pick.picked_team == actual_winner else "LOSS"
                home_score    = score["home_score"]
                away_score    = score["away_score"]
            else:
                actual_winner = None
                result        = "PENDING"
                home_score    = None
                away_score    = None

            conn.execute("""
                INSERT OR REPLACE INTO backtest_picks
                    (session_date, game_id, home_name, away_name, home_abbrev, away_abbrev,
                     picked_team, model_h_prob, model_a_prob, actual_winner,
                     home_score, away_score, result)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                req.date, pick.game_id, pick.home_name, pick.away_name,
                pick.home_abbrev, pick.away_abbrev,
                pick.picked_team, pick.model_home_prob, pick.model_away_prob,
                actual_winner, home_score, away_score, result,
            ))

            scored.append({
                "game_id":       pick.game_id,
                "home_name":     pick.home_name,
                "away_name":     pick.away_name,
                "picked_team":   pick.picked_team,
                "model_prob":    pick.model_home_prob if pick.picked_team == "home" else pick.model_away_prob,
                "actual_winner": actual_winner,
                "home_score":    home_score,
                "away_score":    away_score,
                "result":        result,
            })
        conn.commit()

    wins    = sum(1 for s in scored if s["result"] == "WIN")
    losses  = sum(1 for s in scored if s["result"] == "LOSS")
    pending = sum(1 for s in scored if s["result"] == "PENDING")

    return {
        "date":    req.date,
        "scored":  scored,
        "summary": {"total": len(scored), "wins": wins, "losses": losses, "pending": pending},
    }


@router.get("/backtest/history")
async def get_backtest_history():
    """Return all backtest sessions grouped by date with win/loss totals."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM backtest_picks ORDER BY session_date DESC, saved_at"
        ).fetchall()

    picks = [dict(r) for r in rows]

    if not picks:
        return {
            "sessions": [],
            "totals": {"total": 0, "wins": 0, "losses": 0, "pending": 0, "win_rate": None},
        }

    by_date: dict = defaultdict(list)
    for p in picks:
        by_date[p["session_date"]].append(p)

    sessions = []
    for d in sorted(by_date.keys(), reverse=True):
        day_picks = by_date[d]
        wins    = sum(1 for p in day_picks if p["result"] == "WIN")
        losses  = sum(1 for p in day_picks if p["result"] == "LOSS")
        pending = sum(1 for p in day_picks if p["result"] == "PENDING")
        sessions.append({"date": d, "picks": day_picks, "wins": wins, "losses": losses, "pending": pending})

    total_wins     = sum(1 for p in picks if p["result"] == "WIN")
    total_losses   = sum(1 for p in picks if p["result"] == "LOSS")
    total_pending  = sum(1 for p in picks if p["result"] == "PENDING")
    total_resolved = total_wins + total_losses
    win_rate       = round(total_wins / total_resolved, 4) if total_resolved > 0 else None

    return {
        "sessions": sessions,
        "totals": {
            "total":    len(picks),
            "wins":     total_wins,
            "losses":   total_losses,
            "pending":  total_pending,
            "win_rate": win_rate,
        },
    }
