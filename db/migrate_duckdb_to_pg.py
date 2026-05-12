"""
db/migrate_duckdb_to_pg.py — One-time migration from DuckDB to PostgreSQL

Reads every table from the local DuckDB file and bulk-inserts into PostgreSQL.
Safe to re-run — uses ON CONFLICT DO NOTHING so existing rows are skipped.

TEACHING NOTE — how bulk insert works:
  psycopg2's executemany() sends rows one at a time — slow for large tables.
  execute_values() from psycopg2.extras sends many rows in one SQL statement:
    INSERT INTO table (col1, col2) VALUES (r1c1, r1c2), (r2c1, r2c2), ...
  For 90,000 price rows this is ~100x faster than executemany().
"""

import os
import sys
from pathlib import Path
from datetime import datetime

import duckdb
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent.parent
DUCK_PATH = Path(os.environ.get("DB_PATH", str(ROOT / "data" / "investor_intelligence.duckdb")))
PG_URL = os.environ.get("DATABASE_URL", "")

if not PG_URL:
    print("ERROR: DATABASE_URL not set in .env")
    sys.exit(1)


def migrate_table(duck, pg_cur, table: str, pk_cols: list[str]) -> int:
    """Copy all rows from DuckDB table to PostgreSQL. Returns rows inserted."""
    # Get column names from DuckDB
    cols_info = duck.execute(f"PRAGMA table_info({table})").fetchall()
    if not cols_info:
        print(f"  {table}: no columns found, skipping")
        return 0

    col_names = [r[1] for r in cols_info]
    rows = duck.execute(f"SELECT * FROM {table}").fetchall()

    if not rows:
        print(f"  {table}: 0 rows (empty)")
        return 0

    cols_sql = ", ".join(col_names)
    placeholders = "(" + ", ".join(["%s"] * len(col_names)) + ")"

    # ON CONFLICT DO NOTHING — safe to re-run
    conflict = f"ON CONFLICT ({', '.join(pk_cols)}) DO NOTHING" if pk_cols else ""

    execute_values(
        pg_cur,
        f"INSERT INTO {table} ({cols_sql}) VALUES %s {conflict}",
        rows,
        template=placeholders,
        page_size=1000,
    )
    return len(rows)


# Tables with their primary key columns (needed for ON CONFLICT)
TABLES = [
    ("raw_prices",          ["date", "ticker", "source"]),
    ("raw_macro",           ["date", "series_id", "source"]),
    ("raw_fx",              ["date", "base_currency", "quote_currency", "source"]),
    ("raw_sentiment",       []),   # no PK — append only
    ("raw_fundamentals",    ["date", "ticker", "metric"]),
    ("raw_crypto",          ["date", "coin_id"]),
    ("raw_calendar_events", []),   # no PK
    ("raw_qc_log",          []),   # no PK
    ("daily_features",      ["date"]),
    ("regime_labels",       ["date"]),
    ("regime_predictions",  ["date", "model_version"]),
    ("volatility_forecasts",["date", "model_version", "ticker", "horizon_days"]),
    ("fx_forecasts",        ["date", "model_version", "pair", "horizon_days"]),
    ("cape_forecasts",      ["date", "model_version"]),
    ("hmm_predictions",     ["date", "model_version"]),
    ("recession_predictions",["date", "model_version"]),
    ("model_eval_log",      ["eval_date", "model_name", "metric"]),
    ("users",               ["user_id"]),
    ("user_positions",      ["user_id", "ticker", "account_type"]),
    ("user_transactions",   ["transaction_id"]),
    ("ike_contributions",   ["user_id", "year"]),
    ("user_preferences",    ["user_id"]),
    ("decision_log",        ["decision_id"]),
]


def main():
    print(f"Connecting to DuckDB: {DUCK_PATH}")
    duck = duckdb.connect(str(DUCK_PATH), read_only=True)

    print(f"Connecting to PostgreSQL ...")
    pg = psycopg2.connect(PG_URL)
    pg_cur = pg.cursor()

    total_rows = 0
    start = datetime.now()

    for table, pk_cols in TABLES:
        try:
            n = migrate_table(duck, pg_cur, table, pk_cols)
            print(f"  {table:<30} {n:>7} rows")
            total_rows += n
        except Exception as e:
            print(f"  {table:<30} ERROR: {e}")
            pg.rollback()
            continue

    pg.commit()
    pg_cur.close()
    duck.close()
    pg.close()

    elapsed = (datetime.now() - start).seconds
    print(f"\nDone. {total_rows:,} rows migrated in {elapsed}s.")


if __name__ == "__main__":
    main()
