"""
ingestion/fx.py — NBP API exchange rate loader

Fetches official PLN exchange rates from the National Bank of Poland (NBP).
NBP is the authoritative source for PLN rates — used for portfolio P&L,
IKE contribution valuation, and PLN-adjusted return calculations.

NBP API docs: http://api.nbp.pl/
"""

import sys
import time
from pathlib import Path
from datetime import date, timedelta

import requests
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from db.init_db import get_connection, PH

NBP_BASE = "http://api.nbp.pl/api/exchangerates/rates/a"
SOURCE = "nbp"

# WHY: NBP API enforces a maximum 93-day window per request. Requesting a
# longer range returns HTTP 400. We loop in ~90-day chunks to stay safely
# within the limit while covering multi-year historical loads.
CHUNK_DAYS = 90

# Currencies to fetch — NBP Table A contains mid rates vs PLN
CURRENCIES = ["USD", "EUR", "GBP", "CHF"]

HISTORY_START = date(2005, 1, 1)


def get_latest_date(conn, base: str, quote: str = "PLN") -> date:
    row = conn.execute(
        f"""SELECT MAX(date) FROM raw_fx
           WHERE base_currency = {PH} AND quote_currency = {PH} AND source = {PH}""",
        [base, quote, SOURCE]
    ).fetchone()
    latest = row[0] if row and row[0] else None
    if latest is None:
        return HISTORY_START
    return pd.Timestamp(latest).date() + timedelta(days=1)


def fetch_nbp_range(currency: str, start: date, end: date) -> pd.DataFrame:
    url = f"{NBP_BASE}/{currency.lower()}/{start}/{end}/?format=json"
    resp = requests.get(url, timeout=15)

    # 404 means no data for this range (e.g. future dates or pre-history)
    if resp.status_code == 404:
        return pd.DataFrame()
    resp.raise_for_status()

    rates = resp.json().get("rates", [])
    if not rates:
        return pd.DataFrame()

    df = pd.DataFrame(rates)
    df = df.rename(columns={"effectiveDate": "date", "mid": "rate"})
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["base_currency"] = currency.upper()
    df["quote_currency"] = "PLN"
    df["source"] = SOURCE

    return df[["date", "base_currency", "quote_currency", "rate", "source"]]


def fetch_currency_full(currency: str, start: date) -> pd.DataFrame:
    # WHY: We iterate in CHUNK_DAYS windows rather than fetching the full
    # date range at once because the NBP API returns HTTP 400 for windows
    # longer than 93 days. The loop accumulates chunks into one DataFrame
    # so callers get a single consistent result regardless of date range.
    today = date.today()
    chunks = []
    chunk_start = start

    while chunk_start <= today:
        chunk_end = min(chunk_start + timedelta(days=CHUNK_DAYS - 1), today)
        df = fetch_nbp_range(currency, chunk_start, chunk_end)
        if not df.empty:
            chunks.append(df)
        chunk_start = chunk_end + timedelta(days=1)
        time.sleep(0.3)  # polite rate limiting — NBP has no stated limit but is a govt server

    return pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()


def upsert_fx(conn, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    # WHY: Same upsert logic as raw_prices — idempotent ingestion handles
    # re-runs and NBP occasionally revises rates after initial publication.
    conn.executemany(
        f"""
        INSERT INTO raw_fx
            (date, base_currency, quote_currency, rate, source)
        VALUES ({PH}, {PH}, {PH}, {PH}, {PH})
        ON CONFLICT (date, base_currency, quote_currency, source) DO UPDATE SET
            rate = excluded.rate,
            ingested_at = now()
        """,
        df[["date", "base_currency", "quote_currency", "rate", "source"]].values.tolist()
    )
    return len(df)


def run(currencies: list[str] = CURRENCIES, full_reload: bool = False) -> dict:
    conn = get_connection()
    results = {}

    for currency in currencies:
        start = HISTORY_START if full_reload else get_latest_date(conn, currency)
        if isinstance(start, date) and start > date.today():
            print(f"  {currency}/PLN: already up to date.")
            results[currency] = {"rows": 0, "error": None}
            continue

        print(f"  {currency}/PLN: fetching from {start} ...", end=" ", flush=True)
        try:
            df = fetch_currency_full(currency, start if isinstance(start, date) else HISTORY_START)
            n = upsert_fx(conn, df)
            print(f"{n} rows upserted.")
            results[currency] = {"rows": n, "error": None}
        except Exception as exc:
            print(f"ERROR — {exc}")
            results[currency] = {"rows": 0, "error": str(exc)}

    conn.commit()
    conn.close()
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--full-reload", action="store_true")
    args = parser.parse_args()

    print("=== NBP FX ingestion ===")
    results = run(full_reload=args.full_reload)
    total = sum(r["rows"] for r in results.values())
    errors = [c for c, r in results.items() if r["error"]]
    print(f"\nDone. {total} total rows upserted.")
    if errors:
        print(f"Currencies with errors: {errors}")
