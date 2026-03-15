from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yfinance as yf
import logging
import requests as req_lib
import sqlite3
import os
from datetime import datetime
from nhl_router import router as nhl_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Database ─────────────────────────────────────────────────────────────────

DB_PATH = os.path.join(os.path.dirname(__file__), "watchlist.db")


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
        conn.commit()


init_db()

app = FastAPI(title="Stock Dashboard API", version="1.0.0")
app.include_router(nhl_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TIMEFRAME_MAP = {
    "1d":  {"period": "1d",   "interval": "5m"},
    "6m":  {"period": "6mo",  "interval": "1d"},
    "5y":  {"period": "5y",   "interval": "1wk"},
    "10y": {"period": "10y",  "interval": "1mo"},
}


def fetch_stock_data(ticker: str, period: str, interval: str) -> list:
    """Fetch OHLCV data from yfinance and return as a list of dicts."""
    try:
        tk = yf.Ticker(ticker)
        df = tk.history(period=period, interval=interval)

        if df.empty:
            raise ValueError(f"No data returned for ticker '{ticker}'")

        df = df.reset_index()
        is_intraday = interval == "5m"  # only true intraday interval we use
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
def search_ticker(ticker: str):
    """Return basic company info for a ticker symbol."""
    sym = ticker.upper()
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
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/fundamentals/{ticker}")
def get_fundamentals(ticker: str):
    """Return PE ratios, dividend yield, rate, dates, and payment history."""
    sym = ticker.upper()
    try:
        tk = yf.Ticker(sym)
        info = tk.info or {}

        trailing_pe    = info.get("trailingPE")
        forward_pe     = info.get("forwardPE")
        dividend_yield = info.get("dividendYield")   # decimal, e.g. 0.0245
        dividend_rate  = info.get("dividendRate")    # annual $ per share
        ex_div_ts      = info.get("exDividendDate")  # unix timestamp
        last_div_value = info.get("lastDividendValue")
        last_div_ts    = info.get("lastDividendDate")

        def ts_to_date(ts):
            try: return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d")
            except Exception: return None

        # Historical dividends — last 12 payments, most recent first
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
            # yfinance inconsistently returns yield as decimal (0.0264) or pct (2.64)
            # If value > 1 it's already a percentage; otherwise multiply by 100
            "dividend_yield":     round(float(dividend_yield) if float(dividend_yield) > 1 else float(dividend_yield)*100, 2) if dividend_yield else None,
            "dividend_rate":      round(float(dividend_rate), 4)   if dividend_rate  else None,
            "ex_dividend_date":   ts_to_date(ex_div_ts)            if ex_div_ts      else None,
            "last_dividend_value": round(float(last_div_value), 4) if last_div_value else None,
            "last_dividend_date": ts_to_date(last_div_ts)          if last_div_ts    else None,
            "dividend_history":   div_history,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/chart/{ticker}/{timeframe}")
def get_chart_data(ticker: str, timeframe: str):
    timeframe = timeframe.lower()
    if timeframe not in TIMEFRAME_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid timeframe '{timeframe}'. Choose from: {list(TIMEFRAME_MAP.keys())}"
        )

    config = TIMEFRAME_MAP[timeframe]

    try:
        data = fetch_stock_data(ticker.upper(), config["period"], config["interval"])
        return {
            "ticker":    ticker.upper(),
            "timeframe": timeframe,
            "interval":  config["interval"],
            "count":     len(data),
            "data":      data,
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/suggest/{query}")
def suggest_tickers(query: str):
    """Return ticker suggestions matching a search string."""
    try:
        url = "https://query1.finance.yahoo.com/v1/finance/search"
        params = {"q": query, "quotesCount": 8, "newsCount": 0, "listsCount": 0}
        headers = {"User-Agent": "Mozilla/5.0"}
        r = req_lib.get(url, params=params, headers=headers, timeout=5)
        r.raise_for_status()
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
        raise HTTPException(status_code=500, detail=str(e))


class WatchlistItem(BaseModel):
    ticker: str
    name: str


@app.get("/watchlist")
def get_watchlist():
    """Return all watchlist items ordered by when they were added."""
    with get_db() as conn:
        rows = conn.execute("SELECT ticker, name FROM watchlist ORDER BY added_at").fetchall()
    return {"items": [{"ticker": r["ticker"], "name": r["name"]} for r in rows]}


@app.post("/watchlist", status_code=201)
def add_to_watchlist(item: WatchlistItem):
    """Add a ticker to the watchlist. Silently ignores duplicates."""
    ticker = item.ticker.upper()
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO watchlist (ticker, name) VALUES (?, ?)",
            (ticker, item.name),
        )
        conn.commit()
    return {"ticker": ticker, "name": item.name}


@app.delete("/watchlist/{ticker}", status_code=200)
def remove_from_watchlist(ticker: str):
    """Remove a ticker from the watchlist."""
    sym = ticker.upper()
    with get_db() as conn:
        conn.execute("DELETE FROM watchlist WHERE ticker = ?", (sym,))
        conn.commit()
    return {"removed": sym}


@app.get("/chart/{ticker}/all")
def get_all_timeframes(ticker: str):
    results = {}
    for timeframe, config in TIMEFRAME_MAP.items():
        try:
            results[timeframe] = fetch_stock_data(
                ticker.upper(), config["period"], config["interval"]
            )
        except Exception as e:
            results[timeframe] = {"error": str(e)}

    return {"ticker": ticker.upper(), "charts": results}
