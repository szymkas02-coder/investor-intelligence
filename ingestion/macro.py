"""
ingestion/macro.py — FRED API macro indicator loader

Fetches US and global macro series from the Federal Reserve Bank of St. Louis.
FRED is the gold standard for macro data: 800k+ series, reliable history,
clean revisions. Requires a free API key from fred.stlouisfed.org.

Set env var: FRED_API_KEY=your_key_here
"""

import os
import sys
from pathlib import Path
from datetime import date, timedelta

import requests
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from db.init_db import get_connection, PH

# Load .env from project root if present
_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
SOURCE = "fred"
HISTORY_START = "2005-01-01"

# WHY: Series are grouped by frequency so the ingestion loop can attach the
# correct frequency label to each row in raw_macro. Downstream feature
# engineering uses frequency to decide the forward-fill window:
#   daily   → no fill needed (gaps are weekends/holidays)
#   monthly → fill up to 31 days forward
#   quarterly → fill up to 92 days forward
# Mixing frequencies without labeling them would force every query to
# re-derive frequency from the data distribution — fragile and slow.

SERIES = {
    "daily": [
        "DGS10",        # 10-Year Treasury Yield
        "DGS2",         # 2-Year Treasury Yield
        "DGS3MO",       # 3-Month Treasury Yield
        "T10Y2Y",       # 10Y-2Y Yield Spread (yield curve)
        "T10Y3M",       # 10Y-3M Yield Spread (recession signal)
        "BAMLH0A0HYM2", # High Yield Spread (credit risk)
        "VIXCLS",       # VIX closing price (cross-check vs yfinance)
        "DTWEXBGS",     # USD trade-weighted index
    ],
    "monthly": [
        "CPIAUCSL",        # US CPI All Items
        "CPILFESL",        # US Core CPI (ex food & energy)
        "UNRATE",          # US Unemployment Rate
        "FEDFUNDS",        # Fed Funds Rate
        "UMCSENT",         # U Michigan Consumer Sentiment
        "IRSTCB01PLM156N", # Poland NBP Central Bank Rate (OECD via FRED)
        "SAHMREALTIME",    # Real-time Sahm Rule indicator (no look-ahead bias)
        "PERMIT",          # Housing permits — Conference Board LEI component
        "INDPRO",          # Industrial production index — LEI component
    ],
    "weekly": [
        "ICSA",            # Initial jobless claims — high-frequency leading indicator
    ],
    "quarterly": [
        "GDP",          # US GDP (level)
    ],
}


def get_api_key() -> str:
    key = os.environ.get("FRED_API_KEY", "")
    if not key:
        raise EnvironmentError(
            "FRED_API_KEY not set. Register at https://fred.stlouisfed.org "
            "and set: set FRED_API_KEY=your_key"
        )
    return key


def get_latest_date(conn, series_id: str) -> str:
    row = conn.execute(
        f"SELECT MAX(date) FROM raw_macro WHERE series_id = {PH} AND source = {PH}",
        [series_id, SOURCE]
    ).fetchone()
    latest = row[0] if row and row[0] else None
    if latest is None:
        return HISTORY_START
    return (pd.Timestamp(latest) + timedelta(days=1)).strftime("%Y-%m-%d")


def fetch_series(series_id: str, start: str, api_key: str) -> pd.DataFrame:
    params = {
        "series_id": series_id,
        "observation_start": start,
        "observation_end": date.today().strftime("%Y-%m-%d"),
        "api_key": api_key,
        "file_type": "json",
    }
    resp = requests.get(FRED_BASE, params=params, timeout=20)
    resp.raise_for_status()
    observations = resp.json().get("observations", [])
    if not observations:
        return pd.DataFrame()

    df = pd.DataFrame(observations)[["date", "value"]]
    # WHY: FRED uses "." to represent missing values (e.g. preliminary data
    # not yet released). We coerce these to NaN rather than raising a parse
    # error — downstream QC will flag gaps, and forward-fill in features.py
    # will handle them. Auto-dropping them here would silently shrink the
    # date index and break rolling window calculations that expect continuity.
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["series_id"] = series_id
    df["source"] = SOURCE
    return df[["date", "series_id", "source", "value"]]


def upsert_macro(conn, df: pd.DataFrame, frequency: str) -> int:
    if df.empty:
        return 0
    df = df.copy()
    df["frequency"] = frequency
    conn.executemany(
        f"""
        INSERT INTO raw_macro
            (date, series_id, source, value, frequency)
        VALUES ({PH}, {PH}, {PH}, {PH}, {PH})
        ON CONFLICT (date, series_id, source) DO UPDATE SET
            value = excluded.value,
            frequency = excluded.frequency,
            ingested_at = now()
        """,
        df[["date", "series_id", "source", "value", "frequency"]].values.tolist()
    )
    return len(df)


def run(full_reload: bool = False) -> dict:
    api_key = get_api_key()
    conn = get_connection()
    results = {}

    for frequency, series_list in SERIES.items():
        for series_id in series_list:
            start = HISTORY_START if full_reload else get_latest_date(conn, series_id)
            print(f"  {series_id} ({frequency}): fetching from {start} ...", end=" ", flush=True)
            try:
                df = fetch_series(series_id, start, api_key)
                n = upsert_macro(conn, df, frequency)
                print(f"{n} rows upserted.")
                results[series_id] = {"rows": n, "error": None}
            except Exception as exc:
                print(f"ERROR — {exc}")
                results[series_id] = {"rows": 0, "error": str(exc)}

    conn.commit()
    conn.close()
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--full-reload", action="store_true")
    args = parser.parse_args()

    print("=== FRED macro ingestion ===")
    results = run(full_reload=args.full_reload)
    total = sum(r["rows"] for r in results.values())
    errors = [s for s, r in results.items() if r["error"]]
    print(f"\nDone. {total} total rows upserted.")
    if errors:
        print(f"Series with errors: {errors}")
