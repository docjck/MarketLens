# test_nhl_pl.py
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from nhl_router import ml_to_units

def test_favorite_win():
    result = ml_to_units(-140, "WIN")
    assert abs(result - round(100 / 140, 4)) < 0.0001

def test_underdog_win():
    result = ml_to_units(120, "WIN")
    assert abs(result - round(120 / 100, 4)) < 0.0001

def test_loss():
    assert ml_to_units(-140, "LOSS") == -1.0
    assert ml_to_units(120,  "LOSS") == -1.0

def test_pending():
    assert ml_to_units(-140, "PENDING") is None
    assert ml_to_units(None, "WIN")    is None

def test_fallback_model_prob():
    result = ml_to_units(None, "WIN", model_prob=0.60)
    assert abs(result - round(0.40 / 0.60, 4)) < 0.0001

def test_fallback_loss():
    result = ml_to_units(None, "LOSS", model_prob=0.60)
    assert result == -1.0

def test_invalid_ml_zero():
    assert ml_to_units(0, "WIN") is None

def test_unknown_result():
    assert ml_to_units(-140, "UNKNOWN") is None
    assert ml_to_units(-140, "") is None

def test_model_prob_clamped_high():
    # model_prob=0.90 exceeds 0.80 ceiling; should clamp to 0.80
    result = ml_to_units(None, "WIN", model_prob=0.90)
    assert abs(result - round(0.20 / 0.80, 4)) < 0.0001

def test_model_prob_clamped_low():
    # model_prob=0.10 is below 0.20 floor; should clamp to 0.20
    result = ml_to_units(None, "WIN", model_prob=0.10)
    assert abs(result - round(0.80 / 0.20, 4)) < 0.0001


def test_backtest_table_has_ml_columns(monkeypatch):
    import sqlite3
    import tempfile
    import os

    tmp = tempfile.mktemp(suffix=".db")

    # Import the module
    import nhl_router

    # Patch the DB_PATH before calling init
    monkeypatch.setattr(nhl_router, "DB_PATH", tmp)

    # Directly call the init function with the patched DB_PATH
    nhl_router.init_backtest_table()

    # Check the table
    conn = sqlite3.connect(tmp)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(backtest_picks)").fetchall()]
    conn.close()

    assert "home_ml" in cols, f"home_ml not in columns: {cols}"
    assert "away_ml" in cols, f"away_ml not in columns: {cols}"

    # Try to delete, with retry on Windows
    try:
        os.unlink(tmp)
    except PermissionError:
        import gc
        gc.collect()
        os.unlink(tmp)


def test_backtest_table_migration_adds_ml_columns(monkeypatch, tmp_path):
    """ALTER TABLE migration path: existing DB without ML columns gets them added."""
    import sqlite3
    tmp = str(tmp_path / "test_migrate.db")
    # Pre-populate with old schema (no home_ml/away_ml)
    with sqlite3.connect(tmp) as conn:
        conn.execute("""
            CREATE TABLE backtest_picks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_date TEXT NOT NULL,
                game_id INTEGER NOT NULL,
                result TEXT NOT NULL DEFAULT 'PENDING',
                UNIQUE(session_date, game_id)
            )
        """)
    import nhl_router
    monkeypatch.setattr(nhl_router, "DB_PATH", tmp)
    nhl_router.init_backtest_table()
    with sqlite3.connect(tmp) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(backtest_picks)").fetchall()]
    assert "home_ml" in cols
    assert "away_ml" in cols


def test_parse_historical_odds_lookup():
    mock_data = [{
        "home_team": "Colorado Avalanche",
        "away_team": "Dallas Stars",
        "bookmakers": [{"markets": [{"key": "h2h", "outcomes": [
            {"name": "Colorado Avalanche", "price": -150},
            {"name": "Dallas Stars", "price": 130},
        ]}]}]
    }]
    lookup = {}
    for event in mock_data:
        e_home, e_away = event["home_team"], event["away_team"]
        key = f"{e_home}|{e_away}"
        for book in event["bookmakers"]:
            for market in book["markets"]:
                if market["key"] == "h2h":
                    mls = {o["name"]: o["price"] for o in market["outcomes"]}
                    lookup[key] = {"home_ml": mls.get(e_home), "away_ml": mls.get(e_away)}
    assert lookup["Colorado Avalanche|Dallas Stars"]["home_ml"] == -150
    assert lookup["Colorado Avalanche|Dallas Stars"]["away_ml"] == 130


def test_backtest_pick_accepts_ml_fields():
    from nhl_router import BacktestPick
    pick = BacktestPick(
        game_id=1, picked_team="home",
        home_name="Colorado Avalanche", away_name="Dallas Stars",
        home_abbrev="COL", away_abbrev="DAL",
        model_home_prob=0.62, model_away_prob=0.38,
        home_ml=-155, away_ml=130,
    )
    assert pick.home_ml == -155
    assert pick.away_ml == 130


def test_backtest_pick_ml_optional():
    from nhl_router import BacktestPick
    pick = BacktestPick(
        game_id=1, picked_team="home",
        home_name="Colorado Avalanche", away_name="Dallas Stars",
        home_abbrev="COL", away_abbrev="DAL",
        model_home_prob=0.62, model_away_prob=0.38,
    )
    assert pick.home_ml is None
    assert pick.away_ml is None


def test_edge_history_unit_calc():
    from nhl_router import ml_to_units
    picks = [
        {"result": "WIN",  "edge_team": "home", "home_ml": -140, "away_ml": 110, "model_prob": 0.60},
        {"result": "LOSS", "edge_team": "away", "home_ml": -160, "away_ml": 135, "model_prob": 0.40},
        {"result": "WIN",  "edge_team": "home", "home_ml": None, "away_ml": None, "model_prob": 0.65},
    ]
    unit_results = []
    for p in picks:
        edge_ml = p["home_ml"] if p["edge_team"] == "home" else p["away_ml"]
        ur = ml_to_units(edge_ml, p["result"], model_prob=p["model_prob"])
        unit_results.append(ur)

    assert abs(unit_results[0] - round(100/140, 4)) < 0.0001
    assert unit_results[1] == -1.0
    assert abs(unit_results[2] - round(0.35/0.65, 4)) < 0.0001  # NOTE: model_prob=0.65 is within [0.20,0.80] so no clamping

    running = 0.0
    cumulative = []
    for u in [u for u in unit_results if u is not None]:
        running = round(running + u, 4)
        cumulative.append(running)
    assert len(cumulative) == 3
    assert cumulative[1] < cumulative[0]
