"""
ingestion/stooq.py — STOOQ historical market data loader

STOOQ is more reliable than yfinance for Polish and European tickers.
It provides clean CSV downloads with no authentication and no observed
rate limiting. Data is sourced directly from exchange feeds.

WHY STOOQ over yfinance for Polish tickers:
- yfinance ^WIG is delisted/broken; STOOQ wig and wig20 work reliably
- STOOQ provides consistent OHLCV without the MultiIndex column issues
  that yfinance introduced in newer versions for non-US tickers
- STOOQ now requires a free API key (captcha-gated at stooq.com/q/d/?s=wig20&get_apikey)
- Key is stored in .env as STOOQ_API_KEY
"""

import os
import sys
import time
from pathlib import Path
from datetime import date, timedelta

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from db.init_db import get_connection, PH

# Load .env from project root
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

SOURCE = "stooq"
HISTORY_START = "2005-01-01"

# WHY: We store STOOQ tickers separately from yfinance tickers in raw_prices
# using source='stooq'. This lets QC cross-validate USDPLN from STOOQ against
# USDPLN=X from yfinance and NBP rates — three independent sources for the
# same rate is a strong consistency check for a PLN-exposed portfolio.
TICKERS = {
    "wig20":  "WIG20",    # WIG20 blue-chip index — most liquid Polish equities
    "wig":    "WIG",      # WIG broad market — all WSE listed companies
    "^dax":   "DAX",      # German DAX — European benchmark (STOOQ symbol: ^dax)
    "usdpln": "USDPLN",   # USD/PLN spot (cross-check vs NBP + yfinance)
    "eurpln": "EURPLN",   # EUR/PLN spot
}


def fetch_stooq(stooq_symbol: str) -> pd.DataFrame:
    # WHY: STOOQ serves historical data as plain CSV via a stable URL pattern.
    # We request interval=d (daily) with no date range — STOOQ returns full
    # history by default. Filtering to HISTORY_START happens after download
    # because STOOQ doesn't support a start_date query parameter reliably.
    api_key = os.environ.get("STOOQ_API_KEY", "")
    if not api_key:
        raise EnvironmentError("STOOQ_API_KEY not set in .env")
    url = f"https://stooq.com/q/d/l/?s={stooq_symbol}&i=d&apikey={api_key}"
    resp = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()

    from io import StringIO
    df = pd.read_csv(StringIO(resp.text))

    if df.empty or "Date" not in df.columns:
        return pd.DataFrame()

    df.columns = [c.lower() for c in df.columns]
    df = df.rename(columns={"adj close": "adj_close"})
    df["date"] = pd.to_datetime(df["date"]).dt.date

    # Filter to project history start
    df = df[df["date"] >= pd.Timestamp(HISTORY_START).date()]

    # STOOQ doesn't always provide adj_close — use close as fallback
    if "adj_close" not in df.columns:
        df["adj_close"] = df["close"]

    for col in ["open", "high", "low", "close", "adj_close", "volume"]:
        if col not in df.columns:
            df[col] = None

    # WHY: Index tickers like ^dax have no volume — STOOQ returns NaN.
    # DuckDB raw_prices.volume is BIGINT so we must convert NaN → None
    # (Python None maps to SQL NULL) before inserting, otherwise DuckDB
    # raises a cast error trying to fit float('nan') into INT64.
    # Convert NaN volume to None — index tickers (^dax) have no volume data
    # for recent dates before official close. Using pd.NA + object dtype keeps
    # None as Python None when iterating rows, avoiding numpy's NaN→float trap.
    df["volume"] = df["volume"].where(df["volume"].notna(), other=pd.NA)
    df["volume"] = df["volume"].astype(object)

    return df[["date", "open", "high", "low", "close", "adj_close", "volume"]]


def upsert_prices(conn, df: pd.DataFrame, ticker: str) -> int:
    if df.empty:
        return 0
    df = df.copy()
    df["ticker"] = ticker
    df["source"] = SOURCE
    import math

    def _clean(v):
        if v is None:
            return None
        if isinstance(v, float) and math.isnan(v):
            return None
        return v

    rows = [
        [_clean(v) for v in row]
        for row in df[["date", "ticker", "source", "open", "high", "low",
                        "close", "adj_close", "volume"]].itertuples(index=False)
    ]
    conn.executemany(
        f"""
        INSERT INTO raw_prices
            (date, ticker, source, open, high, low, close, adj_close, volume)
        VALUES ({PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH}, {PH})
        ON CONFLICT (date, ticker, source) DO UPDATE SET
            open      = excluded.open,
            high      = excluded.high,
            low       = excluded.low,
            close     = excluded.close,
            adj_close = excluded.adj_close,
            volume    = excluded.volume,
            ingested_at = now()
        """,
        rows
    )
    return len(df)


def get_latest_date(conn, ticker: str) -> str | None:
    """Return latest stored date for this ticker, or None if no data."""
    count = conn.execute(
        f"SELECT COUNT(*) FROM raw_prices WHERE ticker = {PH} AND source = {PH}",
        [ticker, SOURCE]
    ).fetchall()[0][0]
    if count == 0:
        return None
    rows = conn.execute(
        f"SELECT MAX(date) FROM raw_prices WHERE ticker = {PH} AND source = {PH}",
        [ticker, SOURCE]
    ).fetchall()
    return str(rows[0][0]) if rows and rows[0][0] else None


def run(tickers: dict = TICKERS) -> dict:
    conn = get_connection()
    results = {}

    for stooq_symbol, internal_ticker in tickers.items():
        latest = get_latest_date(conn, internal_ticker)
        print(f"  {internal_ticker} (stooq:{stooq_symbol}): fetching ...", end=" ", flush=True)
        try:
            df = fetch_stooq(stooq_symbol)
            # WHY: STOOQ returns full history CSV — filter to only new rows
            # to avoid re-upserting thousands of rows on every daily run.
            # ON CONFLICT DO UPDATE would handle duplicates correctly but
            # wastes time serialising and parsing unchanged data.
            if latest and not df.empty:
                df = df[df["date"] > pd.Timestamp(latest).date()]
            n = upsert_prices(conn, df, internal_ticker)
            print(f"{n} rows upserted.")
            results[internal_ticker] = {"rows": n, "error": None}
        except Exception as exc:
            print(f"ERROR — {exc}")
            results[internal_ticker] = {"rows": 0, "error": str(exc)}
        time.sleep(0.5)

    conn.commit()
    conn.close()
    return results


if __name__ == "__main__":
    print("=== STOOQ market data ingestion ===")
    results = run()
    total = sum(r["rows"] for r in results.values())
    errors = [t for t, r in results.items() if r["error"]]
    print(f"\nDone. {total} total rows upserted.")
    if errors:
        print(f"Tickers with errors: {errors}")
