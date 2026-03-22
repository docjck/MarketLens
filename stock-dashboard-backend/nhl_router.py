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

