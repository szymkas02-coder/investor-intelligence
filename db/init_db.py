"""
db/init_db.py — Database initialisation and connection factory

Supports both DuckDB (local dev, no DATABASE_URL set) and PostgreSQL
(production, DATABASE_URL env var set).

TEACHING NOTE — the two connection models:

  DuckDB:  get_connection() opens the .duckdb file directly.
           Used by ingestion/, processing/, ml/ (pipeline scripts).
           Not suitable for concurrent access.

  PostgreSQL: get_connection() returns a psycopg2 connection to the server.
           Used when DATABASE_URL is set. Handles concurrent access natively.

The FastAPI backend uses backend/database.py (which has its own pooling).
The pipeline scripts use get_connection() from this file.
"""

import os
from pathlib import Path

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Placeholder character for parameterised queries.
# DuckDB uses ?  PostgreSQL uses %s
PH = "%s" if DATABASE_URL else "?"

# ─── DuckDB config (used when DATABASE_URL is not set) ───────────────────────
_db_path_env = os.environ.get("DB_PATH")
DB_PATH = Path(_db_path_env) if _db_path_env else \
          Path(__file__).parent.parent / "data" / "investor_intelligence.duckdb"

SCHEMA_DUCK = Path(__file__).parent / "schema.sql"
SCHEMA_PG   = Path(__file__).parent / "schema_pg.sql"


# =============================================================================
# get_connection() — returns the right connection type based on environment
# =============================================================================

def get_connection(db_path: Path = DB_PATH):
    """
    Returns a database connection.
    - If DATABASE_URL is set: returns a _PgAdapter-wrapped psycopg2 connection
    - Otherwise: returns a DuckDB connection to the local .duckdb file

    Both support .execute(sql, params) and .fetchall() identically.
    """
    if DATABASE_URL:
        import psycopg2

        class _PgAdapter:
            def __init__(self, conn):
                self._conn = conn
                self._last_cur = None

            def execute(self, sql, params=None):
                cur = self._conn.cursor()
                cur.execute(sql, params) if params else cur.execute(sql)
                self._last_cur = cur
                return cur

            def executemany(self, sql, params_list):
                cur = self._conn.cursor()
                cur.executemany(sql, params_list)
                self._last_cur = cur
                return cur

            def fetchall(self):
                return self._last_cur.fetchall()

            def fetchone(self):
                return self._last_cur.fetchone()

            def commit(self):
                self._conn.commit()

            def close(self):
                self._conn.close()

        return _PgAdapter(psycopg2.connect(DATABASE_URL))
    else:
        import duckdb
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return duckdb.connect(str(db_path))


# =============================================================================
# get_max_date() — safe MAX(date) that works on both databases
# =============================================================================

def get_max_date(conn, table: str, date_col: str = "date",
                 filter_col: str = None, filter_val: str = None,
                 filter_col2: str = None, filter_val2: str = None) -> str | None:
    """
    Get MAX(date_col) safely, handling empty result sets on both DB backends.

    TEACHING NOTE — why this helper exists:
      DuckDB 1.5.2 has a bug where MAX() over an empty partition crashes.
      PostgreSQL MAX() over empty set returns NULL (correct behaviour).
      We use COUNT-first to be safe on both.

    Parameter binding differs between databases:
      DuckDB:     uses ? placeholders
      PostgreSQL: uses %s placeholders
    This function handles both.
    """
    conditions = []
    params = []
    if filter_col and filter_val is not None:
        conditions.append(filter_col)
        params.append(filter_val)
    if filter_col2 and filter_val2 is not None:
        conditions.append(filter_col2)
        params.append(filter_val2)

    # Build WHERE clause and pick the right placeholder style
    placeholder = "%s" if DATABASE_URL else "?"
    where_parts = [f"{c} = {placeholder}" for c in conditions]
    where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

    count = conn.execute(
        f"SELECT COUNT(*) FROM {table} {where}", params
    ).fetchall()[0][0]

    if count == 0:
        return None

    rows = conn.execute(
        f"SELECT MAX({date_col}) FROM {table} {where}", params
    ).fetchall()
    return str(rows[0][0]) if rows and rows[0][0] else None


# =============================================================================
# Schema initialisation
# =============================================================================

def init_schema(conn) -> None:
    """Create all tables if they don't exist. Safe to re-run."""
    if DATABASE_URL:
        _init_pg(conn)
    else:
        _init_duck(conn)


def _init_pg(conn) -> None:
    sql = SCHEMA_PG.read_text(encoding="utf-8")
    cur = conn.cursor()
    # PostgreSQL can run the whole schema in one execute — no splitting needed
    cur.execute(sql)
    conn.commit()
    cur.close()


def _init_duck(conn) -> None:
    sql = SCHEMA_DUCK.read_text(encoding="utf-8")
    for stmt in _extract_create_statements(sql):
        conn.execute(stmt)
    conn.commit()


def _extract_create_statements(sql: str) -> list[str]:
    """Split DuckDB schema on CREATE TABLE boundaries (avoids semicolon-in-comment pitfall)."""
    statements = []
    current: list[str] = []
    for line in sql.splitlines():
        current.append(line)
        if line.rstrip().endswith(";") and any("CREATE TABLE" in l for l in current):
            statements.append("\n".join(current))
            current = []
    return statements


def verify_tables(conn) -> None:
    """Assert all expected tables exist — raises RuntimeError if any are missing."""
    expected = [
        "raw_prices", "raw_macro", "raw_fx", "raw_sentiment",
        "raw_fundamentals", "raw_crypto", "raw_calendar_events", "raw_qc_log",
        "daily_features", "regime_labels", "regime_predictions",
        "volatility_forecasts", "fx_forecasts", "model_eval_log",
        "users", "user_positions", "user_transactions", "ike_contributions",
        "user_preferences", "decision_log",
    ]
    if DATABASE_URL:
        cur = conn.cursor()
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public'"
        )
        existing = {row[0] for row in cur.fetchall()}
        cur.close()
    else:
        existing = {
            row[0] for row in conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main'"
            ).fetchall()
        }

    missing = [t for t in expected if t not in existing]
    if missing:
        raise RuntimeError(f"Schema incomplete — missing tables: {missing}")
    print(f"All {len(expected)} tables verified.")


if __name__ == "__main__":
    db_type = "PostgreSQL" if DATABASE_URL else f"DuckDB at {DB_PATH}"
    print(f"Initializing {db_type} ...")
    conn = get_connection()
    init_schema(conn)
    verify_tables(conn)
    conn.close()
    print("Done.")
