"""
ingestion/sentiment.py — Finnhub sentiment + economic calendar loader

Two distinct data types from Finnhub:
1. News sentiment scores for ACWI and SPY (stored in raw_sentiment)
2. Economic calendar events — FOMC, CPI, NFP releases (stored in raw_calendar_events)

WHY these are separate tables:
- Sentiment is a continuous signal (score per day per ticker)
- Calendar events are discrete scheduled events with importance + actual vs estimate
- Mixing them would force every sentiment query to filter by type — separating
  them gives each table a coherent schema and query contract

Finnhub free tier: 60 calls/minute. We stay well within this with sleep(1).
Set env var: FINNHUB_API_KEY (stored in .env)
"""

import os
import sys
import time
from pathlib import Path
from datetime import date, timedelta

import requests
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from db.init_db import get_connection, PH

# Load .env
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

FINNHUB_BASE = "https://finnhub.io/api/v1"
SOURCE_SENTIMENT = "finnhub"
SOURCE_CALENDAR  = "finnhub"

# Tickers to fetch sentiment for
# WHY: General news feed gives one market-wide sentiment score per day.
# We store it under ticker="MARKET" — one row per day is sufficient since
# the keyword-ratio method uses all headlines, not ticker-specific news.
SENTIMENT_TICKERS = ["MARKET"]

# WHY: We fetch 30-day windows for sentiment rather than full history because
# Finnhub free tier limits news sentiment history. The incremental approach
# (fetch from last stored date) keeps us within rate limits on daily runs
# while still building up history over time.
SENTIMENT_WINDOW_DAYS = 30

# Calendar lookback + lookahead window
CALENDAR_LOOKBACK_DAYS = 365
CALENDAR_LOOKAHEAD_DAYS = 90


def get_api_key() -> str:
    key = os.environ.get("FINNHUB_API_KEY", "")
    if not key:
        raise EnvironmentError("FINNHUB_API_KEY not set in .env")
    return key


# =============================================================================
# Sentiment
# =============================================================================

def get_sentiment_latest_date(conn, ticker: str) -> date:
    row = conn.execute(
        f"SELECT MAX(date) FROM raw_sentiment WHERE source = {PH} AND ticker = {PH}",
        [SOURCE_SENTIMENT, ticker]
    ).fetchone()
    latest = row[0] if row and row[0] else None
    if latest is None:
        return date.today() - timedelta(days=SENTIMENT_WINDOW_DAYS)
    return pd.Timestamp(latest).date() + timedelta(days=1)


BULLISH_WORDS = {"rally", "surge", "gain", "rise", "record", "high", "bull",
                 "growth", "recovery", "optimism", "upside", "beat"}
BEARISH_WORDS = {"crash", "drop", "fall", "decline", "recession", "fear",
                 "bear", "loss", "risk", "selloff", "correction", "miss"}


def fetch_sentiment(ticker: str, api_key: str) -> pd.DataFrame:
    # WHY: Finnhub's news-sentiment endpoint requires a paid plan. We instead
    # fetch the free general market news feed and compute a simple bullish ratio
    # from headline keyword counts. This is less sophisticated than Finnhub's
    # NLP score but fully transparent — we know exactly what drives the signal.
    # For regime classification the directional signal (more bullish vs bearish
    # headlines) matters more than the precise score magnitude.
    url = f"{FINNHUB_BASE}/news"
    params = {"category": "general", "token": api_key}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    articles = resp.json()

    if not articles:
        return pd.DataFrame()

    bullish_count = 0
    bearish_count = 0
    for article in articles:
        headline = (article.get("headline", "") + " " +
                    article.get("summary", "")).lower()
        bullish_count += sum(1 for w in BULLISH_WORDS if w in headline)
        bearish_count += sum(1 for w in BEARISH_WORDS if w in headline)

    total = bullish_count + bearish_count
    score = bullish_count / total if total > 0 else 0.5  # 0=bearish, 1=bullish

    row = {
        "date":    date.today(),
        "source":  SOURCE_SENTIMENT,
        "ticker":  ticker,
        "keyword": None,
        "score":   score,
        "buzz":    float(len(articles)),
        "metadata": {
            "bullish_count": bullish_count,
            "bearish_count": bearish_count,
            "total_articles": len(articles),
            "method": "keyword_ratio",
        },
    }
    return pd.DataFrame([row])


def upsert_sentiment(conn, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    import json
    rows = [
        (
            str(r.date), r.source, r.ticker, r.keyword,
            r.score, r.buzz,
            json.dumps(r.metadata) if isinstance(r.metadata, dict) else r.metadata
        )
        for r in df.itertuples(index=False)
    ]
    conn.executemany(
        f"""
        INSERT INTO raw_sentiment
            (date, source, ticker, keyword, score, buzz, metadata)
        VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH})
        """,
        rows
    )
    return len(rows)


# =============================================================================
# Economic calendar
# =============================================================================

def fetch_calendar(api_key: str) -> pd.DataFrame:
    start = (date.today() - timedelta(days=CALENDAR_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    end   = (date.today() + timedelta(days=CALENDAR_LOOKAHEAD_DAYS)).strftime("%Y-%m-%d")

    url = f"{FINNHUB_BASE}/calendar/economic"
    params = {"from": start, "to": end, "token": api_key}
    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()

    events = resp.json().get("economicCalendar", [])
    if not events:
        return pd.DataFrame()

    df = pd.DataFrame(events)

    # WHY: We store importance level ('high', 'medium', 'low') because FOMC
    # meeting weeks structurally elevate volatility regardless of the outcome.
    # Filtering to high-importance events in feature engineering isolates the
    # calendar effect — including low-importance events adds noise without
    # improving regime signal. Keeping all levels in raw storage preserves
    # optionality for future analysis.
    rename = {
        "time":     "date",
        "event":    "event_name",
        "country":  "country",
        "impact":   "importance",
        "actual":   "actual",
        "estimate": "estimate",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    for col in ["date", "event_name", "country", "importance", "actual", "estimate"]:
        if col not in df.columns:
            df[col] = None

    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df = df.dropna(subset=["date"])

    # Normalise importance labels
    impact_map = {"1": "low", "2": "medium", "3": "high",
                  1: "low",   2: "medium",   3: "high"}
    df["importance"] = df["importance"].map(impact_map).fillna(df["importance"])

    return df[["date", "event_name", "country", "importance", "actual", "estimate"]]


def upsert_calendar(conn, df: pd.DataFrame) -> int:
    if df.empty:
        return 0

    def _clean(v):
        import math
        if v is None:
            return None
        if isinstance(v, float) and math.isnan(v):
            return None
        return v

    rows = [
        (_clean(r.date), _clean(r.event_name), _clean(r.country),
         _clean(r.importance), _clean(r.actual), _clean(r.estimate))
        for r in df.itertuples(index=False)
    ]
    conn.executemany(
        f"""
        INSERT INTO raw_calendar_events
            (date, event_name, country, importance, actual, estimate)
        VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, {PH})
        """,
        rows
    )
    return len(rows)


# =============================================================================
# Orchestration
# =============================================================================

def run() -> dict:
    api_key = get_api_key()
    conn = get_connection()
    results = {}

    # Sentiment
    for ticker in SENTIMENT_TICKERS:
        print(f"  Sentiment {ticker}: fetching ...", end=" ", flush=True)
        try:
            df = fetch_sentiment(ticker, api_key)
            n = upsert_sentiment(conn, df)
            print(f"{n} rows upserted.")
            results[f"sentiment_{ticker}"] = {"rows": n, "error": None}
        except Exception as exc:
            print(f"ERROR — {exc}")
            results[f"sentiment_{ticker}"] = {"rows": 0, "error": str(exc)}
        time.sleep(1)

    # Economic calendar
    print(f"  Economic calendar: fetching ...", end=" ", flush=True)
    try:
        df = fetch_calendar(api_key)
        n = upsert_calendar(conn, df)
        print(f"{n} rows upserted.")
        results["calendar"] = {"rows": n, "error": None}
    except Exception as exc:
        print(f"ERROR — {exc}")
        results["calendar"] = {"rows": 0, "error": str(exc)}

    conn.commit()
    conn.close()
    return results


if __name__ == "__main__":
    print("=== Finnhub sentiment + calendar ingestion ===")
    results = run()
    total = sum(r["rows"] for r in results.values())
    errors = [k for k, r in results.items() if r["error"]]
    print(f"\nDone. {total} total rows upserted.")
    if errors:
        print(f"Sources with errors: {errors}")
