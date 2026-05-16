"""
nhl_daily.py — Updated for both regular season and playoffs

Runs independently of the FastAPI server. Intended to be scheduled via
Windows Task Scheduler so picks and results are tracked even when the
dashboard app is not open.

What it does each run:
  1. Detects if we're in regular season (gameType 2) or playoffs (gameType 3)
  2. Fetches today's schedule + standings + odds for that season type
  3. Saves any flagged edge picks to the edge_picks table
  4. Resolves PENDING picks from previous days using the NHL score API
  5. Logs a summary to nhl_daily.log

Schedule with Task Scheduler:
  schtasks /create /tn "NHLDailyTracker" /tr "python C:\\Users\\Jeremy\\ChartProject\\stock-dashboard-backend\\nhl_daily.py" /sc DAILY /st 08:00 /f
  Then in Task Scheduler GUI: Settings tab -> enable "Run task as soon as possible after a scheduled start is missed"
"""

import asyncio
import logging
import math
import os
import sqlite3
from datetime import datetime, timezone, timedelta

import httpx
from dotenv import load_dotenv

load_dotenv()

# ─── Config ───────────────────────────────────────────────────────────────────

DB_PATH      = os.path.join(os.path.dirname(__file__), "watchlist.db")
LOG_PATH     = os.path.join(os.path.dirname(__file__), "nhl_daily.log")
NHL_BASE     = "https://api-web.nhle.com/v1"
ODDS_BASE    = "https://api.the-odds-api.com/v4"
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
EDGE_FLAG    = 0.05
EDGE_STRONG  = 0.10
HOME_ADV     = 0.04

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ─── Database ─────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
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
        # Add ou_line column for O/U picks (edge_team = 'over' or 'under').
        # O/U picks are stored with game_id = -(real_game_id) so H2H and O/U
        # picks for the same game can coexist without PRIMARY KEY conflicts.
        try:
            conn.execute("ALTER TABLE edge_picks ADD COLUMN ou_line REAL")
        except sqlite3.OperationalError:
            pass  # column already exists
        conn.commit()

# ─── Model helpers ────────────────────────────────────────────────────────────

def moneyline_to_prob(ml: int) -> float:
    if ml > 0:
        return 100 / (ml + 100)
    return abs(ml) / (abs(ml) + 100)


def poisson_pmf(k: int, lam: float) -> float:
    if k < 0 or lam <= 0:
        return 0.0
    return (lam ** k) * math.exp(-lam) / math.factorial(k)


def model_over_prob(expected_total: float, line: float) -> float:
    """P(total goals > line) using Poisson. Line is typically X.5."""
    threshold = int(line) + 1
    p_under = sum(poisson_pmf(k, expected_total) for k in range(threshold))
    return round(max(0.01, min(0.99, 1 - p_under)), 4)


def model_home_prob(home: dict, away: dict, series_state: dict = None) -> float:
    """
    Predict home win probability.

    Base model: season win%, GF/GA differential, last-10 form, home ice.
    For playoffs: apply series context (momentum) if provided.

    Returns estimated home win probability clamped to [0.20, 0.80].
    """
    hw = home.get("wins", 0)
    hl = home.get("losses", 0) + home.get("otLosses", 0)
    aw = away.get("wins", 0)
    al = away.get("losses", 0) + away.get("otLosses", 0)

    h_pct  = hw / (hw + hl) if (hw + hl) > 0 else 0.5
    a_pct  = aw / (aw + al) if (aw + al) > 0 else 0.5
    total  = h_pct + a_pct
    h_prob = (h_pct / total) if total > 0 else 0.5

    hgp = max(home.get("gamesPlayed", 1), 1)
    agp = max(away.get("gamesPlayed", 1), 1)
    h_gf = home.get("goalFor", 0) / hgp
    h_ga = home.get("goalAgainst", 0) / hgp
    a_gf = away.get("goalFor", 0) / agp
    a_ga = away.get("goalAgainst", 0) / agp
    h_prob += ((h_gf - a_ga) - (a_gf - h_ga)) * 0.02

    h_l10  = home.get("l10Wins", 0)
    a_l10  = away.get("l10Wins", 0)
    h_prob += (h_l10 - a_l10) / 10 * 0.04
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
    Detect if games in the schedule are regular season (gameType 2) or playoffs (gameType 3).
    Returns 'regular', 'playoff', or 'mixed'.
    """
    game_types = set()
    for week in schedule_data.get("gameWeek", []):
        for g in week.get("games", []):
            game_types.add(g.get("gameType"))

    if game_types == {2}:
        return "regular"
    elif game_types == {3}:
        return "playoff"
    else:
        return "mixed"


def get_playoff_series_state(game: dict) -> dict | None:
    """
    Extract playoff series state from game data if available.
    Returns dict with home_wins, away_wins, or None.
    """
    series = game.get("seriesStatus")
    if not series:
        return None

    # seriesStatus format: "Series Name LEADING 2-0" or similar
    # Parse to extract win counts
    try:
        parts = str(series).split()
        # Look for pattern like "2-0" or "1-1"
        for part in parts:
            if "-" in part and len(part) == 3:
                h_w, a_w = map(int, part.split("-"))
                return {"home_wins": h_w, "away_wins": a_w}
    except:
        pass

    return None

# ─── Main logic ───────────────────────────────────────────────────────────────

async def save_todays_picks(client: httpx.AsyncClient, today: str) -> int:
    """Fetch today's games, compute edges, save flagged picks. Returns count saved.

    Checks both today's AND tomorrow's UTC schedule so that late Western Conference
    games (e.g. 10 pm PT = 5 am UTC next day) are captured while pre-game odds
    are still available.
    """

    # Standings
    try:
        resp = await client.get(f"{NHL_BASE}/standings/now")
        resp.raise_for_status()
        standings_raw = resp.json().get("standings", [])
    except Exception as e:
        log.error(f"Standings fetch failed: {e}")
        return 0

    team_stats = {}
    for t in standings_raw:
        abbrev = t.get("teamAbbrev", {}).get("default", "")
        if abbrev:
            team_stats[abbrev] = t

    # Schedule — fetch today AND tomorrow UTC to catch late Western games whose
    # startTimeUTC rolls into the next calendar day.
    # Also accept tomorrow-UTC games found in today's response: the NHL API
    # groups midnight-UTC games (e.g. 8 PM EDT) under today's schedule but
    # stamps them with tomorrow's UTC date, so they'd otherwise be missed.
    tomorrow = (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    games_raw = []
    seen_ids: set = set()
    season_type = None

    for fetch_date in (today, tomorrow):
        try:
            resp = await client.get(f"{NHL_BASE}/schedule/{fetch_date}")
            resp.raise_for_status()
            schedule = resp.json()
        except Exception as e:
            log.warning(f"Schedule fetch failed for {fetch_date}: {e}")
            continue

        detected = detect_season_type(schedule)
        if detected and detected != "mixed":
            season_type = detected  # last non-mixed wins (today takes priority)

        # Accept games starting on today or tomorrow regardless of which
        # schedule endpoint returned them — avoids midnight-UTC games falling
        # through when the NHL API stamps them with the next UTC date but only
        # surfaces them in the current day's schedule response.
        for week in schedule.get("gameWeek", []):
            for g in week.get("games", []):
                gid = g.get("id")
                start = g.get("startTimeUTC", "")
                if (
                    g.get("gameType") in (2, 3)
                    and (start.startswith(today) or start.startswith(tomorrow))
                    and gid not in seen_ids
                ):
                    games_raw.append(g)
                    seen_ids.add(gid)

    if not season_type:
        log.info(f"No NHL games found for {today}")
        return 0

    if season_type == "mixed":
        log.warning(f"Mixed game types found around {today}, skipping")
        return 0

    game_type_filter = 3 if season_type == "playoff" else 2
    games_raw = [g for g in games_raw if g.get("gameType") == game_type_filter]
    log.info(f"Detected {season_type.upper()} season (gameType {game_type_filter})")

    if not games_raw:
        log.info(f"No {season_type} games found for {today}")
        return 0

    log.info(f"Found {len(games_raw)} {season_type} game(s) for {today} (incl. late Western games)")

    # H2H odds lookup
    odds_lookup: dict = {}
    ou_lookup: dict = {}
    if ODDS_API_KEY:
        try:
            resp = await client.get(
                f"{ODDS_BASE}/sports/icehockey_nhl/odds/",
                params={
                    "apiKey": ODDS_API_KEY,
                    "regions": "us",
                    "markets": "h2h,totals",
                    "oddsFormat": "american",
                }
            )
            resp.raise_for_status()
            events = resp.json() if isinstance(resp.json(), list) else resp.json().get("data", [])
            for event in events:
                e_home = event.get("home_team", "")
                e_away = event.get("away_team", "")
                key = f"{e_home}|{e_away}"
                for book in event.get("bookmakers", [])[:1]:
                    for market in book.get("markets", []):
                        if market["key"] == "h2h":
                            mls = {o["name"]: o["price"] for o in market["outcomes"]}
                            odds_lookup[key] = {
                                "home_ml": mls.get(e_home),
                                "away_ml": mls.get(e_away),
                            }
                        elif market["key"] == "totals":
                            over  = next((o for o in market["outcomes"] if o["name"] == "Over"),  None)
                            under = next((o for o in market["outcomes"] if o["name"] == "Under"), None)
                            if over:
                                ou_lookup[key] = {
                                    "line":      over.get("point"),
                                    "over_ml":   over.get("price"),
                                    "under_ml":  under.get("price") if under else None,
                                }
        except Exception as e:
            log.warning(f"Odds API fetch failed: {e}")

    # Process games
    saved = 0
    with get_db() as conn:
        for g in games_raw:
            h_abbrev = g.get("homeTeam", {}).get("abbrev", "")
            a_abbrev = g.get("awayTeam", {}).get("abbrev", "")
            h_place = g.get("homeTeam", {}).get("placeName", {}).get("default", "")
            a_place = g.get("awayTeam", {}).get("placeName", {}).get("default", "")
            h_common = g.get("homeTeam", {}).get("commonName", {}).get("default", "")
            a_common = g.get("awayTeam", {}).get("commonName", {}).get("default", "")
            h_name = f"{h_place} {h_common}".strip() or h_abbrev
            a_name = f"{a_place} {a_common}".strip() or a_abbrev

            h_stats = team_stats.get(h_abbrev, {})
            a_stats = team_stats.get(a_abbrev, {})
            series_state = get_playoff_series_state(g)
            game_date = g.get("startTimeUTC", today)[:10] or today

            model_h = model_home_prob(h_stats, a_stats, series_state)
            model_a = round(1 - model_h, 4)

            hgp = max(h_stats.get("gamesPlayed", 1), 1)
            agp = max(a_stats.get("gamesPlayed", 1), 1)

            # Match odds by team place name substring
            home_ml = away_ml = None
            ou_line = over_ml = under_ml = None
            for key, od in odds_lookup.items():
                if h_place.lower() in key.lower() and a_place.lower() in key.lower():
                    home_ml = od.get("home_ml")
                    away_ml = od.get("away_ml")
                    break
            for key, od in ou_lookup.items():
                if h_place.lower() in key.lower() and a_place.lower() in key.lower():
                    ou_line   = od.get("line")
                    over_ml   = od.get("over_ml")
                    under_ml  = od.get("under_ml")
                    break

            implied_h = moneyline_to_prob(home_ml) if home_ml else None

            # ── H2H edge ──────────────────────────────────────────────────────
            edge_team = None
            edge_value = 0
            strong = False

            if implied_h and abs(model_h - implied_h) >= EDGE_FLAG:
                if model_h > implied_h:
                    edge_team = "home"
                    edge_value = round(model_h - implied_h, 4)
                else:
                    edge_team = "away"
                    edge_value = round(implied_h - model_h, 4)
                strong = edge_value >= EDGE_STRONG

            # ── O/U edge ──────────────────────────────────────────────────────
            ou_edge_team = None
            ou_edge_value = 0
            ou_strong = False
            ou_model_p = ou_implied_p = None

            if ou_line is not None and over_ml is not None:
                h_gf = h_stats.get("goalFor", 0) / hgp
                a_gf = a_stats.get("goalFor", 0) / agp
                expected_total = h_gf + a_gf
                ou_model_p = model_over_prob(expected_total, ou_line)
                raw_over  = moneyline_to_prob(int(over_ml))
                raw_under = moneyline_to_prob(int(under_ml)) if under_ml else raw_over
                vig_ou = raw_over + raw_under
                ou_implied_p = round(raw_over / vig_ou, 4) if vig_ou else None
                if ou_implied_p is not None:
                    ou_diff = ou_model_p - ou_implied_p
                    if abs(ou_diff) >= EDGE_FLAG:
                        ou_edge_team  = "over" if ou_diff > 0 else "under"
                        ou_edge_value = round(abs(ou_diff), 4)
                        ou_strong     = ou_edge_value >= EDGE_STRONG

            series_note = f" [{series_state}]" if series_state else ""

            # ── Save H2H pick ─────────────────────────────────────────────────
            if edge_team:
                conn.execute("""
                    INSERT OR IGNORE INTO edge_picks
                        (game_id, date, season_type, home_abbrev, away_abbrev, home_name, away_name,
                         edge_team, edge_value, strong_flag, model_prob, implied_prob,
                         home_ml, away_ml, start_utc)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    g["id"], game_date, season_type, h_abbrev, a_abbrev, h_name, a_name,
                    edge_team, edge_value, 1 if strong else 0,
                    model_h, implied_h, home_ml, away_ml,
                    g.get("startTimeUTC", ""),
                ))
                if conn.total_changes > saved:
                    tag = "STRONG " if strong else ""
                    log.info(f"  Saved {tag}H2H EDGE: {a_name} @ {h_name} — {edge_team.upper()} +{edge_value*100:.1f}%{series_note}")
                    saved += 1

            # ── Save O/U pick ─────────────────────────────────────────────────
            # Stored with negative game_id so H2H and O/U picks for the same
            # game can coexist without PRIMARY KEY conflicts.
            if ou_edge_team:
                ou_game_id = -(g["id"])
                conn.execute("""
                    INSERT OR IGNORE INTO edge_picks
                        (game_id, date, season_type, home_abbrev, away_abbrev, home_name, away_name,
                         edge_team, edge_value, strong_flag, model_prob, implied_prob,
                         home_ml, away_ml, ou_line, start_utc)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ou_game_id, game_date, season_type, h_abbrev, a_abbrev, h_name, a_name,
                    ou_edge_team, ou_edge_value, 1 if ou_strong else 0,
                    ou_model_p, ou_implied_p,
                    over_ml, under_ml, ou_line,
                    g.get("startTimeUTC", ""),
                ))
                if conn.total_changes > saved:
                    tag = "STRONG " if ou_strong else ""
                    log.info(f"  Saved {tag}O/U EDGE: {a_name} @ {h_name} — {ou_edge_team.upper()} (line {ou_line}) +{ou_edge_value*100:.1f}%{series_note}")
                    saved += 1

        conn.commit()

    return saved


async def resolve_pending(client: httpx.AsyncClient, today: str) -> int:
    """Check NHL score API for any PENDING picks from prior dates. Returns count resolved."""

    with get_db() as conn:
        rows = conn.execute(
            "SELECT game_id, date, edge_team, home_name, away_name FROM edge_picks "
            "WHERE result = 'PENDING' AND date < ?", (today,)
        ).fetchall()

    pending = [dict(r) for r in rows]
    if not pending:
        log.info("No pending picks to resolve.")
        return 0

    log.info(f"Resolving {len(pending)} pending pick(s) from previous days...")
    dates = list({p["date"] for p in pending})
    resolved = 0

    for date in dates:
        try:
            resp = await client.get(f"{NHL_BASE}/score/{date}")
            if resp.status_code != 200:
                log.warning(f"  Score API returned {resp.status_code} for {date}")
                continue
            score_games = resp.json().get("games", [])
        except Exception as e:
            log.warning(f"  Score fetch failed for {date}: {e}")
            continue

        with get_db() as conn:
            for sg in score_games:
                if sg.get("gameState") not in ("OFF", "FINAL"):
                    continue
                gid     = sg.get("id")
                h_score = sg.get("homeTeam", {}).get("score") or 0
                a_score = sg.get("awayTeam", {}).get("score") or 0
                total   = h_score + a_score

                # ── Resolve H2H pick (positive game_id) ───────────────────────
                if h_score != a_score:
                    actual_winner = "home" if h_score > a_score else "away"
                    existing = conn.execute(
                        "SELECT game_id, edge_team, home_name, away_name FROM edge_picks "
                        "WHERE game_id = ? AND result = 'PENDING'", (gid,)
                    ).fetchone()
                    if existing:
                        result = "WIN" if existing["edge_team"] == actual_winner else "LOSS"
                        conn.execute(
                            "UPDATE edge_picks SET actual_winner = ?, result = ? WHERE game_id = ?",
                            (actual_winner, result, gid)
                        )
                        log.info(
                            f"  Resolved H2H [{result}]: {existing['away_name']} @ {existing['home_name']} "
                            f"— picked {existing['edge_team'].upper()}, actual {actual_winner.upper()} "
                            f"({a_score}-{h_score})"
                        )
                        resolved += 1

                # ── Resolve O/U pick (negative game_id = -gid) ────────────────
                ou_pick = conn.execute(
                    "SELECT game_id, edge_team, home_name, away_name, ou_line FROM edge_picks "
                    "WHERE game_id = ? AND result = 'PENDING'", (-gid,)
                ).fetchone()
                if ou_pick and ou_pick["ou_line"] is not None:
                    line = ou_pick["ou_line"]
                    actual_ou = "over" if total > line else "under"
                    result = "WIN" if ou_pick["edge_team"] == actual_ou else "LOSS"
                    conn.execute(
                        "UPDATE edge_picks SET actual_winner = ?, result = ? WHERE game_id = ?",
                        (actual_ou, result, -gid)
                    )
                    log.info(
                        f"  Resolved O/U [{result}]: {ou_pick['away_name']} @ {ou_pick['home_name']} "
                        f"— picked {ou_pick['edge_team'].upper()} (line {line}), actual total {total}"
                    )
                    resolved += 1

            conn.commit()

    return resolved


async def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log.info(f"{'─'*60}")
    log.info(f"NHL Daily Tracker  —  {today}")
    log.info(f"{'─'*60}")

    init_db()

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        saved   = await save_todays_picks(client, today)
        resolved = await resolve_pending(client, today)

    log.info(f"Done — {saved} new pick(s) saved, {resolved} result(s) resolved.")


if __name__ == "__main__":
    asyncio.run(main())
