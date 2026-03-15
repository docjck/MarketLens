# nhl_router.py — NHL predictions vs odds divergence

import os
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/nhl", tags=["nhl"])

NHL_BASE = "https://api-web.nhle.com/v1"
ODDS_BASE = "https://api.the-odds-api.com/v4"
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")

EDGE_FLAG   = 0.05   # flag if model vs market diverges by 5%+
EDGE_STRONG = 0.10   # strong flag at 10%+
HOME_ADV    = 0.04   # home ice advantage


# ─── Helpers ──────────────────────────────────────────────────────────────────

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


# ─── Main endpoint ────────────────────────────────────────────────────────────

@router.get("/predictions")
async def get_predictions():
    """
    Return model predictions vs market odds for NHL games today.
    Flags games where the model diverges from implied odds by >5%.
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
        odds_lookup = {}   # "HOME_ABBREV|AWAY_ABBREV" -> {"home_ml": int, "away_ml": int}
        if ODDS_API_KEY:
            try:
                resp = await client.get(
                    f"{ODDS_BASE}/sports/icehockey_nhl/odds/",
                    params={
                        "apiKey": ODDS_API_KEY,
                        "regions": "us",
                        "markets": "h2h",
                        "oddsFormat": "american",
                    },
                )
                if resp.status_code == 200:
                    for event in resp.json():
                        e_home = event.get("home_team", "")
                        e_away = event.get("away_team", "")
                        for book in event.get("bookmakers", [])[:1]:
                            for market in book.get("markets", []):
                                if market["key"] == "h2h":
                                    mls = {o["name"]: o["price"] for o in market["outcomes"]}
                                    odds_lookup[f"{e_home}|{e_away}"] = {
                                        "home_team": e_home,
                                        "away_team": e_away,
                                        "home_ml": mls.get(e_home),
                                        "away_ml": mls.get(e_away),
                                    }
            except Exception:
                pass  # odds are optional — don't fail the whole response

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

            results.append({
                "game_id":          g.get("id"),
                "start_utc":        g.get("startTimeUTC", ""),
                "home_abbrev":      h_abbrev,
                "away_abbrev":      a_abbrev,
                "home_name":        f"{h_place} {h_common}".strip(),
                "away_name":        f"{a_place} {a_common}".strip(),
                "home_record":      f"{h_stats.get('wins','?')}-{h_stats.get('losses','?')}-{h_stats.get('otLosses','?')}",
                "away_record":      f"{a_stats.get('wins','?')}-{a_stats.get('losses','?')}-{a_stats.get('otLosses','?')}",
                "home_l10":         h_stats.get("l10Wins"),
                "away_l10":         a_stats.get("l10Wins"),
                "home_gf_pg":       round(h_stats.get("goalFor", 0) / max(h_stats.get("gamesPlayed", 1), 1), 2),
                "away_gf_pg":       round(a_stats.get("goalFor", 0) / max(a_stats.get("gamesPlayed", 1), 1), 2),
                "model_home_prob":  model_h,
                "model_away_prob":  model_a,
                "implied_home_prob": implied_h,
                "implied_away_prob": implied_a,
                "home_ml":          home_ml,
                "away_ml":          away_ml,
                "home_edge":        home_edge,
                "away_edge":        away_edge,
                "flagged":          flagged,
                "strong_flag":      strong,
            })

        # Sort: flagged first, then by start time
        results.sort(key=lambda x: (not x["flagged"], x["start_utc"]))

        return {
            "date":           today,
            "game_count":     len(results),
            "odds_available": bool(ODDS_API_KEY and odds_lookup),
            "games":          results,
        }
