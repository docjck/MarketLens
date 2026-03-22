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
