from dotenv import load_dotenv
load_dotenv()

import re
import os
from urllib.parse import unquote
import sqlite3
import logging
from datetime import datetime

from fastapi import FastAPI, HTTPException, Depends, Request, Path
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
import yfinance as yf
import requests as req_lib

from nhl_router import router as nhl_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Auth ─────────────────────────────────────────────────────────────────────

API_TOKEN = os.getenv("API_TOKEN", "")
_api_key_header = APIKeyHeader(name="X-API-Token", auto_error=False)


def verify_token(key: str | None = Depends(_api_key_header)):
    """Require X-API-Token header when API_TOKEN is set in the environment."""
    if API_TOKEN and key != API_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ─── Rate limiting ────────────────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])

# ─── Database ─────────────────────────────────────────────────────────────────

DB_PATH = os.getenv("MARKETLENS_DB", os.path.join(os.path.dirname(__file__), "watchlist.db"))


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                ticker  TEXT PRIMARY KEY,
                name    TEXT NOT NULL,
                added_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS portfolio (
                ticker  TEXT PRIMARY KEY,
                name    TEXT NOT NULL,
                added_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.commit()


init_db()

app = FastAPI(
    title="Stock Dashboard API",
    version="1.0.0",
    dependencies=[Depends(verify_token)],
)
app.include_router(nhl_router)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

TIMEFRAME_MAP = {
    "1d":  {"period": "1d",   "interval": "5m"},
    "5d":  {"period": "5d",   "interval": "30m"},
    "6m":  {"period": "6mo",  "interval": "1d"},
    "1y":  {"period": "1y",   "interval": "1d"},
}

_TICKER_PATTERN = re.compile(r'^[\^A-Za-z0-9.\-=]{1,20}$')


def _validate_ticker_param(ticker: str) -> str:
    """Raise 400 if the ticker path param contains unexpected characters."""
    ticker = unquote(ticker)
    if not _TICKER_PATTERN.match(ticker):
        raise HTTPException(status_code=400, detail="Invalid ticker symbol")
    return ticker.upper()


def fetch_stock_data(ticker: str, period: str, interval: str) -> list:
    """Fetch OHLCV data from yfinance and return as a list of dicts."""
    try:
        tk = yf.Ticker(ticker)
        df = tk.history(period=period, interval=interval)

        if df.empty:
            raise ValueError(f"No data returned for ticker '{ticker}'")

        df = df.reset_index()
        is_intraday = interval == "5m"
        date_col = "Datetime" if is_intraday else "Date"
        if is_intraday:
            df[date_col] = df[date_col].dt.strftime("%Y-%m-%dT%H:%M")
        else:
            df[date_col] = df[date_col].dt.strftime("%Y-%m-%d")

        records = []
        for _, row in df.iterrows():
            records.append({
                "date":   row[date_col],
                "open":   round(float(row["Open"]), 4),
                "high":   round(float(row["High"]), 4),
                "low":    round(float(row["Low"]), 4),
                "close":  round(float(row["Close"]), 4),
                "volume": int(row["Volume"]),
            })
        return records

    except Exception as e:
        logger.error(f"Error fetching {ticker}: {e}")
        raise


@app.get("/")
def root():
    return {"message": "Stock Dashboard API is running"}


@app.get("/search/{ticker}")
def search_ticker(ticker: str = Path(..., max_length=20)):
    """Return basic company info for a ticker symbol."""
    sym = _validate_ticker_param(ticker)
    try:
        tk = yf.Ticker(sym)

        try:
            fi = tk.fast_info
            name = getattr(fi, "display_name", None) or sym
            currency = getattr(fi, "currency", "USD") or "USD"
            exchange = getattr(fi, "exchange", "N/A") or "N/A"
            return {
                "ticker":   sym,
                "name":     name,
                "sector":   "N/A",
                "industry": "N/A",
                "currency": currency,
                "exchange": exchange,
            }
        except Exception:
            pass

        hist = tk.history(period="5d")
        if hist.empty:
            raise HTTPException(status_code=404, detail=f"Ticker '{sym}' not found")

        return {
            "ticker":   sym,
            "name":     sym,
            "sector":   "N/A",
            "industry": "N/A",
            "currency": "USD",
            "exchange": "N/A",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"/search/{sym}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch ticker info")


@app.get("/fundamentals/{ticker}")
def get_fundamentals(ticker: str = Path(..., max_length=20)):
    """Return PE ratios, dividend yield, rate, dates, and payment history."""
    sym = _validate_ticker_param(ticker)
    try:
        tk = yf.Ticker(sym)
        info = tk.info or {}

        trailing_pe    = info.get("trailingPE")
        forward_pe     = info.get("forwardPE")
        dividend_yield = info.get("dividendYield")
        dividend_rate  = info.get("dividendRate")
        ex_div_ts      = info.get("exDividendDate")
        last_div_value = info.get("lastDividendValue")
        last_div_ts    = info.get("lastDividendDate")

        def ts_to_date(ts):
            try: return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d")
            except Exception: return None

        div_history = []
        try:
            divs = tk.dividends
            if not divs.empty:
                for date, amount in divs.tail(12).items():
                    div_history.append({
                        "date":   date.strftime("%Y-%m-%d"),
                        "amount": round(float(amount), 4),
                    })
                div_history.reverse()
        except Exception:
            pass

        return {
            "ticker":             sym,
            "trailing_pe":        round(float(trailing_pe), 2)     if trailing_pe    else None,
            "forward_pe":         round(float(forward_pe), 2)      if forward_pe     else None,
            "dividend_yield":     round(float(dividend_yield) if float(dividend_yield) > 1 else float(dividend_yield)*100, 2) if dividend_yield else None,
            "dividend_rate":      round(float(dividend_rate), 4)   if dividend_rate  else None,
            "ex_dividend_date":   ts_to_date(ex_div_ts)            if ex_div_ts      else None,
            "last_dividend_value": round(float(last_div_value), 4) if last_div_value else None,
            "last_dividend_date": ts_to_date(last_div_ts)          if last_div_ts    else None,
            "dividend_history":   div_history,
        }
    except Exception as e:
        logger.error(f"/fundamentals/{sym}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch fundamentals")


@app.get("/chart/{ticker}/{timeframe}")
def get_chart_data(ticker: str = Path(..., max_length=20), timeframe: str = Path(..., max_length=10)):
    sym = _validate_ticker_param(ticker)
    tf = timeframe.lower()
    if tf not in TIMEFRAME_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid timeframe '{tf}'. Choose from: {list(TIMEFRAME_MAP.keys())}"
        )

    config = TIMEFRAME_MAP[tf]

    try:
        data = fetch_stock_data(sym, config["period"], config["interval"])
        return {
            "ticker":    sym,
            "timeframe": tf,
            "interval":  config["interval"],
            "count":     len(data),
            "data":      data,
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"/chart/{sym}/{tf}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch chart data")


@app.get("/suggest/{query}")
@limiter.limit("20/minute")
def suggest_tickers(request: Request, query: str = Path(..., max_length=100)):
    """Return ticker suggestions matching a search string."""
    try:
        url = "https://query1.finance.yahoo.com/v1/finance/search"
        params = {"q": query, "quotesCount": 8, "newsCount": 0, "listsCount": 0}
        headers = {"User-Agent": "Mozilla/5.0"}
        r = req_lib.get(url, params=params, headers=headers, timeout=5)
        r.raise_for_status()
        if len(r.content) > 1 * 1024 * 1024:
            raise ValueError("Response from Yahoo Finance was unexpectedly large")
        data = r.json()
        quotes = data.get("quotes", [])
        results = []
        for q in quotes:
            symbol = q.get("symbol", "")
            name = q.get("shortname") or q.get("longname") or symbol
            exch = q.get("exchDisp", "")
            type_ = q.get("typeDisp", "")
            if symbol:
                results.append({"ticker": symbol, "name": name, "exchange": exch, "type": type_})
        return {"results": results}
    except Exception as e:
        logger.error(f"Suggest error: {e}")
        raise HTTPException(status_code=500, detail="Autocomplete unavailable")


class WatchlistItem(BaseModel):
    ticker: str
    name: str

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, v: str) -> str:
        v = v.strip().upper()
        if not re.match(r'^[\^A-Za-z0-9.\-=]{1,20}$', v):
            raise ValueError("Invalid ticker symbol")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if len(v) > 200:
            raise ValueError("Name too long")
        return v


@app.get("/watchlist")
def get_watchlist():
    """Return all watchlist items ordered by when they were added."""
    with get_db() as conn:
        rows = conn.execute("SELECT ticker, name FROM watchlist ORDER BY added_at").fetchall()
    return {"items": [{"ticker": r["ticker"], "name": r["name"]} for r in rows]}


@app.post("/watchlist", status_code=201)
def add_to_watchlist(item: WatchlistItem):
    """Add a ticker to the watchlist. Silently ignores duplicates."""
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO watchlist (ticker, name) VALUES (?, ?)",
            (item.ticker, item.name),
        )
        conn.commit()
    return {"ticker": item.ticker, "name": item.name}


@app.delete("/watchlist/{ticker}", status_code=200)
def remove_from_watchlist(ticker: str = Path(..., max_length=20)):
    """Remove a ticker from the watchlist."""
    sym = _validate_ticker_param(ticker)
    with get_db() as conn:
        conn.execute("DELETE FROM watchlist WHERE ticker = ?", (sym,))
        conn.commit()
    return {"removed": sym}


@app.get("/portfolio")
def get_portfolio():
    """Return all portfolio items ordered by when they were added."""
    with get_db() as conn:
        rows = conn.execute("SELECT ticker, name FROM portfolio ORDER BY added_at").fetchall()
    return {"items": [{"ticker": r["ticker"], "name": r["name"]} for r in rows]}


@app.post("/portfolio", status_code=201)
def add_to_portfolio(item: WatchlistItem):
    """Add a ticker to the portfolio. Silently ignores duplicates."""
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO portfolio (ticker, name) VALUES (?, ?)",
            (item.ticker, item.name),
        )
        conn.commit()
    return {"ticker": item.ticker, "name": item.name}


@app.delete("/portfolio/{ticker}", status_code=200)
def remove_from_portfolio(ticker: str = Path(..., max_length=20)):
    """Remove a ticker from the portfolio."""
    sym = _validate_ticker_param(ticker)
    with get_db() as conn:
        conn.execute("DELETE FROM portfolio WHERE ticker = ?", (sym,))
        conn.commit()
    return {"removed": sym}


@app.get("/chart/{ticker}/all")
def get_all_timeframes(ticker: str = Path(..., max_length=20)):
    sym = _validate_ticker_param(ticker)
    results = {}
    for timeframe, config in TIMEFRAME_MAP.items():
        try:
            results[timeframe] = fetch_stock_data(sym, config["period"], config["interval"])
        except Exception as e:
            logger.error(f"/chart/{sym}/all [{timeframe}]: {e}")
            results[timeframe] = {"error": "Failed to fetch data"}

    return {"ticker": sym, "charts": results}
