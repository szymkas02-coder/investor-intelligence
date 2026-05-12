"""
ingestion/ecb.py — ECB Statistical Data Warehouse (SDW) API loader

Fetches European Central Bank macro data: EA inflation (HICP), ECB policy
rate, and euro area sovereign yield curve. No authentication required.

WHY ECB SDW over FRED for European data:
- FRED has some ECB series but with publication lag and inconsistent coverage
- ECB SDW is the primary source — data goes directly from ECB to the API
- EA yield curve and HICP are critical for a EUR-exposed Polish investor:
  ECB rate decisions directly drive EUR/PLN and affect VWCE.DE valuations
- ECB SDW uses SDMX format; we request JSON via the 'format=jsondata' param
"""

import sys
import time
from pathlib import Path
from datetime import date

import requests
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from db.init_db import get_connection, get_max_date, PH

ECB_BASE = "https://data-api.ecb.europa.eu/service/data"
SOURCE = "ecb"
HISTORY_START = "2005-01-01"

# WHY: Series keys follow ECB's SDMX dimension encoding.
# frequency prefix: M=monthly, B=business day, D=daily
# Each entry: (dataset, series_key, series_id, frequency, description)
SERIES = [
    (
        "ICP", "M.U2.N.000000.4.ANR",
        "HICP_EA_YOY", "monthly",
        "Euro Area HICP inflation YoY"
    ),
    (
        "FM", "B.U2.EUR.4F.KR.MRR_FR.LEV",
        "ECB_MAIN_RATE", "daily",
        "ECB Main Refinancing Rate"
    ),
    (
        "YC", "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y",
        "EA_YIELD_10Y", "daily",
        "Euro Area 10Y sovereign yield (ECB)"
    ),
    (
        "YC", "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y",
        "EA_YIELD_2Y", "daily",
        "Euro Area 2Y sovereign yield (ECB)"
    ),
]


def fetch_ecb_series(dataset: str, series_key: str) -> pd.DataFrame:
    url = f"{ECB_BASE}/{dataset}/{series_key}"
    params = {
        "startPeriod": HISTORY_START,
        "endPeriod": date.today().strftime("%Y-%m-%d"),
        "format": "jsondata",
    }
    resp = requests.get(url, params=params, timeout=30)

    # 404 = series not found or no data in range
    if resp.status_code == 404:
        return pd.DataFrame()
    resp.raise_for_status()

    data = resp.json()

    # WHY: ECB SDMX-JSON nests observations under a non-obvious path.
    # The structure is: dataSets[0].series -> {dimension_key: {observations}}
    # Each observation key is a period index into the time dimension array.
    # We extract time values from the structure dimensions, not from obs keys,
    # to avoid off-by-one errors when the series has gaps.
    try:
        dataset_obj = data["dataSets"][0]
        structure = data["structure"]

        # Time dimension values (observation periods)
        time_dim = next(
            d for d in structure["dimensions"]["observation"]
            if d["id"] in ("TIME_PERIOD", "TIME")
        )
        periods = [v["id"] for v in time_dim["values"]]

        # First (and only) series in this single-series request
        series_data = list(dataset_obj["series"].values())[0]
        observations = series_data["observations"]

        rows = []
        for idx_str, obs_values in observations.items():
            idx = int(idx_str)
            period = periods[idx]
            value = obs_values[0] if obs_values[0] is not None else float("nan")
            rows.append({"period": period, "value": value})

        df = pd.DataFrame(rows)
        if df.empty:
            return pd.DataFrame()

        # WHY: ECB period strings vary by frequency:
        #   daily/business: "2024-01-15"
        #   monthly:        "2024-01"
        # We parse both — monthly gets day=1 so it aligns with the first
        # trading day of that month in downstream forward-fill logic.
        df["date"] = pd.to_datetime(df["period"], format="mixed").dt.date
        df = df.drop(columns=["period"])
        return df

    except (KeyError, IndexError, StopIteration) as exc:
        raise ValueError(f"Unexpected ECB SDW response structure: {exc}") from exc


def get_latest_date(conn, series_id: str) -> str:
    latest = get_max_date(
        conn, "raw_macro",
        filter_col="series_id", filter_val=series_id,
        filter_col2="source",   filter_val2=SOURCE,
    )
    if latest is None:
        return HISTORY_START
    return (pd.Timestamp(latest) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")


def upsert_macro(conn, df: pd.DataFrame, series_id: str, frequency: str) -> int:
    if df.empty:
        return 0
    df = df.copy()
    df["series_id"] = series_id
    df["source"] = SOURCE
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


def run() -> dict:
    conn = get_connection()
    results = {}

    for dataset, series_key, series_id, frequency, description in SERIES:
        start = get_latest_date(conn, series_id)
        print(f"  {series_id} ({frequency}): fetching from {start} ...", end=" ", flush=True)
        try:
            df = fetch_ecb_series(dataset, series_key)
            # Filter to only new dates — ECB API always returns full history
            if not df.empty and start > HISTORY_START:
                df = df[df["date"] >= pd.Timestamp(start).date()]
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
    print("=== ECB SDW macro ingestion ===")
    results = run()
    total = sum(r["rows"] for r in results.values())
    errors = [s for s, r in results.items() if r["error"]]
    print(f"\nDone. {total} total rows upserted.")
    if errors:
        print(f"Series with errors: {errors}")
