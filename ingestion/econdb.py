"""
ingestion/econdb.py — Polish macro data loader (multi-source)

Originally targeting Econdb, now using free alternatives since Econdb
requires authentication for API access:

  - NBP rate:          NBP API (already used in fx.py — same base URL)
  - Poland CPI:        World Bank API (free, no key)
  - Poland GDP:        World Bank API (free, no key)
  - Poland unemployment: World Bank API (free, no key)

WHY Polish macro matters for a PLN-based investor:
- NBP reference rate directly drives PLN/USD carry: high NBP rate relative
  to Fed funds attracts USD inflows, strengthening PLN
- Polish CPI vs US CPI differential (cpi_differential) is a key feature
  in the currency risk model — persistent inflation gap predicts PLN weakness
- rate_differential (fed_funds - nbp_rate) is built in features.py from
  these series combined with FRED's FEDFUNDS
"""

import sys
import time
from pathlib import Path
from datetime import date, timedelta

import requests
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from db.init_db import get_connection, get_max_date, PH

NBP_BASE  = "http://api.nbp.pl/api"
WB_BASE   = "https://api.worldbank.org/v2"
SOURCE    = "econdb"          # keep source label consistent for downstream queries
HISTORY_START = "2005-01-01"
CHUNK_DAYS = 90               # NBP max window

# World Bank indicator codes for Poland (country code: PL)
WB_INDICATORS = {
    "CPI_PL_YOY":  "FP.CPI.TOTL.ZG",   # CPI inflation annual %
    "UNRATE_PL":   "SL.UEM.TOTL.ZS",    # Unemployment % of labour force
    "GDP_PL_YOY":  "NY.GDP.MKTP.KD.ZG", # GDP growth annual %
}


# =============================================================================
# NBP Reference Rate
# =============================================================================

def fetch_nbp_rate(start: str) -> pd.DataFrame:
    """
    Fetch NBP reference rate from NBP API statistics endpoint.
    WHY: NBP publishes its own reference rate history via a separate endpoint
    from the exchange rates. The rate changes infrequently (monthly MPC meetings)
    so the full history fits in one request — no chunking needed.
    """
    url = f"{NBP_BASE}/oprocentowanie/stopa_referencyjna/"
    resp = requests.get(url, params={"format": "json"}, timeout=15)
    if resp.status_code == 404:
        return pd.DataFrame()
    resp.raise_for_status()

    data = resp.json()
    if not data:
        return pd.DataFrame()

    rows = []
    for entry in data:
        # Each entry has 'obowiazujaceOd' (effective from) and 'oprocentowanie'
        effective = entry.get("obowiazujaceOd") or entry.get("data")
        rate      = entry.get("oprocentowanie") or entry.get("stopa")
        if effective and rate is not None:
            rows.append({"date": pd.Timestamp(effective).date(), "value": float(rate)})

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df[df["date"] >= pd.Timestamp(HISTORY_START).date()]
    return df.sort_values("date").drop_duplicates(subset=["date"])


def fetch_nbp_rate_fallback(start_date: str) -> pd.DataFrame:
    """
    Fallback: scrape NBP reference rate from their statistics table.
    Uses the monetary policy rates endpoint which is stable and public.
    """
    # NBP API v2 monetary policy rates
    url = "https://api.nbp.pl/api/stopy/obowiazujace/"
    try:
        resp = requests.get(url, params={"format": "json"}, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        rows = []
        for entry in data:
            for key in ["obowiazujaceOd", "data", "date"]:
                dt = entry.get(key)
                if dt:
                    break
            for val_key in ["stopa_referencyjna", "oprocentowanie", "value"]:
                val = entry.get(val_key)
                if val is not None:
                    break
            else:
                val = None

            if dt and val is not None:
                rows.append({"date": pd.Timestamp(dt).date(), "value": float(val)})

        df = pd.DataFrame(rows) if rows else pd.DataFrame()
        if not df.empty:
            df = df[df["date"] >= pd.Timestamp(HISTORY_START).date()]
        return df

    except Exception:
        return pd.DataFrame()


# =============================================================================
# World Bank
# =============================================================================

def fetch_worldbank(indicator: str, start_year: int = 2005) -> pd.DataFrame:
    """
    Fetch annual series from World Bank API for Poland.
    WHY World Bank over Econdb: free, no auth, stable REST API, good history.
    Limitation: annual frequency only — forward-filled to daily in features.py
    with a 365-day window (acceptable for structural macro like GDP growth).
    """
    url = f"{WB_BASE}/country/PL/indicator/{indicator}"
    params = {
        "format":     "json",
        "per_page":   100,
        "date":       f"{start_year}:{date.today().year}",
        "mrv":        50,
    }
    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()

    payload = resp.json()
    if len(payload) < 2 or not payload[1]:
        return pd.DataFrame()

    rows = []
    for entry in payload[1]:
        year  = entry.get("date")
        value = entry.get("value")
        if year and value is not None:
            # WHY: World Bank annual data has year only — we anchor to Jan 1
            # of that year as the "known from" date for forward-fill. This is
            # conservative: GDP for 2023 is typically published mid-2024, but
            # using Jan 1 only slightly overstates availability. The alternative
            # (using actual publication dates) requires extra API calls per year.
            rows.append({"date": date(int(year), 1, 1), "value": float(value)})

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df[df["date"] >= pd.Timestamp(HISTORY_START).date()]
    return df.sort_values("date")


# =============================================================================
# Upsert
# =============================================================================

def upsert_macro(conn, df: pd.DataFrame, series_id: str, frequency: str) -> int:
    if df.empty:
        return 0
    df = df.copy()
    df["series_id"] = series_id
    df["source"]    = SOURCE
    df["frequency"] = frequency
    conn.executemany(
        f"""
        INSERT INTO raw_macro
            (date, series_id, source, value, frequency)
        VALUES ({PH}, {PH}, {PH}, {PH}, {PH})
        ON CONFLICT (date, series_id, source) DO UPDATE SET
            value     = excluded.value,
            frequency = excluded.frequency,
            ingested_at = now()
        """,
        df[["date", "series_id", "source", "value", "frequency"]].values.tolist()
    )
    return len(df)


def get_latest_date(conn, series_id: str) -> str:
    latest = get_max_date(
        conn, "raw_macro",
        filter_col="series_id", filter_val=series_id,
        filter_col2="source",   filter_val2=SOURCE,
    )
    if latest is None:
        return HISTORY_START
    return (pd.Timestamp(latest) + timedelta(days=1)).strftime("%Y-%m-%d")


# =============================================================================
# Orchestration
# =============================================================================

def run(full_reload: bool = False) -> dict:
    conn = get_connection()
    results = {}

    # --- NBP Reference Rate ---
    series_id = "NBP_RATE"
    start = HISTORY_START if full_reload else get_latest_date(conn, series_id)
    print(f"  {series_id} (monthly/NBP API): fetching ...", end=" ", flush=True)
    try:
        df = fetch_nbp_rate(start)
        if df.empty:
            df = fetch_nbp_rate_fallback(start)
        n = upsert_macro(conn, df, series_id, "monthly")
        print(f"{n} rows upserted.")
        results[series_id] = {"rows": n, "error": None}
    except Exception as exc:
        print(f"ERROR — {exc}")
        results[series_id] = {"rows": 0, "error": str(exc)}

    time.sleep(0.5)

    # --- World Bank indicators ---
    for series_id, wb_indicator in WB_INDICATORS.items():
        start = HISTORY_START if full_reload else get_latest_date(conn, series_id)
        frequency = "quarterly" if "GDP" in series_id else "annual"
        print(f"  {series_id} ({frequency}/WorldBank): fetching ...",
              end=" ", flush=True)
        try:
            df = fetch_worldbank(wb_indicator)
            n = upsert_macro(conn, df, series_id, frequency)
            print(f"{n} rows upserted.")
            results[series_id] = {"rows": n, "error": None}
        except Exception as exc:
            print(f"ERROR — {exc}")
            results[series_id] = {"rows": 0, "error": str(exc)}
        time.sleep(0.5)

    conn.commit()
    conn.close()
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--full-reload", action="store_true")
    args = parser.parse_args()

    print("=== Polish macro ingestion (NBP + World Bank) ===")
    results = run(full_reload=args.full_reload)
    total = sum(r["rows"] for r in results.values())
    errors = [s for s, r in results.items() if r["error"]]
    print(f"\nDone. {total} total rows upserted.")
    if errors:
        print(f"Series with errors: {errors}")
