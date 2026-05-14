"""
backend/database.py — Database connection abstraction (DuckDB or PostgreSQL)

TEACHING NOTE — how database connections work:

  DuckDB:     embedded, file-based. One process opens the file.
              Like opening an Excel file — only one writer at a time.
              Fast for analytics, bad for concurrency.

  PostgreSQL: server-based. Runs as a separate process (like a service).
              Many clients connect simultaneously over a socket/port.
              Each gets its own connection. A "pool" keeps N connections
              open and reuses them across requests.

SWITCHING:
  Set DATABASE_URL environment variable to use PostgreSQL:
    DATABASE_URL=postgresql://user:password@localhost:5432/investor_intelligence
  If not set, falls back to DuckDB.

WHY the adapter wrapper:
  DuckDB connections expose conn.execute(sql) → result with .fetchall()/.fetchone()
  SQLAlchemy PostgreSQL connections need conn.execute(text(sql)) and return
  a different result object. Rather than changing every router, we wrap the
  PostgreSQL connection in a thin adapter that speaks the same API as DuckDB.
  All 18 FastAPI routes call conn.execute(sql) — none of them need to change.
"""

from pathlib import Path
from typing import Generator
import os
import threading

# Load .env explicitly so DATABASE_URL is available even when uvicorn
# doesn't inherit it from the shell environment
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

DB_URL = os.environ.get("DATABASE_URL", "")
_default_duck = Path(__file__).parent.parent / "data" / "investor_intelligence.duckdb"
DUCK_PATH = Path(os.environ.get("DB_PATH", str(_default_duck)))


# ─── PostgreSQL path ──────────────────────────────────────────────────────────
if DB_URL:
    import psycopg2
    import psycopg2.pool

    IS_POSTGRES = True

    # Pool is created lazily on first request so startup never blocks on DB.
    # This prevents Cloud Run container crash-before-listen if Cloud SQL socket
    # isn't ready at import time.
    _pool = None
    _pool_lock = threading.Lock()

    def _get_pool():
        global _pool
        if _pool is None:
            with _pool_lock:
                if _pool is None:
                    _pool = psycopg2.pool.ThreadedConnectionPool(1, 20, DB_URL)
        return _pool

    class _PgAdapter:
        """
        Wraps a psycopg2 connection to expose the same API as DuckDB.

        TEACHING NOTE — Adapter design pattern:
          DuckDB:     conn.execute(sql) returns a result with .fetchall()
          psycopg2:   conn.cursor().execute(sql); cursor.fetchall()
          This adapter makes psycopg2 look like DuckDB so all 18 routers
          work unchanged.

        WHY a new cursor per execute() call:
          A psycopg2 cursor holds the result of one query. If a router runs
          two queries on the same connection (e.g. portfolio router does
          SELECT positions then SELECT transactions), each needs its own
          cursor — otherwise the second query overwrites the first cursor's
          result buffer before fetchall() is called on it.
        """
        def __init__(self, raw_conn):
            self._conn = raw_conn
            self._last_cur = None

        def execute(self, sql: str, params=None):
            cur = self._conn.cursor()
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
            self._last_cur = cur
            return cur           # caller can call .fetchall() on the returned cursor

        def executemany(self, sql: str, params_list):
            cur = self._conn.cursor()
            cur.executemany(sql, params_list)
            self._last_cur = cur
            return cur

        # Convenience: conn.fetchall() delegates to the last cursor
        def fetchall(self):
            return self._last_cur.fetchall()

        def fetchone(self):
            return self._last_cur.fetchone()

        def commit(self):
            self._conn.commit()

        def close(self):
            if self._last_cur:
                try:
                    self._last_cur.close()
                except Exception:
                    pass
            _get_pool().putconn(self._conn)

    def get_db() -> Generator[_PgAdapter, None, None]:
        """FastAPI dependency — yields a PostgreSQL connection from the pool."""
        raw = _get_pool().getconn()
        conn = _PgAdapter(raw)
        try:
            yield conn
        except Exception:
            raw.rollback()
            raise
        finally:
            conn.close()

    def get_db_write() -> Generator[_PgAdapter, None, None]:
        """Write connection — commits on success, rolls back on exception."""
        raw = _get_pool().getconn()
        conn = _PgAdapter(raw)
        try:
            yield conn
            raw.commit()
        except Exception:
            raw.rollback()
            raise
        finally:
            conn.close()

    def run_migrations():
        """Create any missing tables. Safe to run on every startup (IF NOT EXISTS)."""
        raw = _get_pool().getconn()
        try:
            cur = raw.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id         SERIAL PRIMARY KEY,
                    user_id    VARCHAR(128) NOT NULL,
                    role       VARCHAR(16)  NOT NULL CHECK (role IN ('user', 'assistant')),
                    content    TEXT         NOT NULL,
                    created_at TIMESTAMPTZ  DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_chat_history_user_created
                ON chat_history (user_id, created_at DESC)
            """)
            raw.commit()
        finally:
            _get_pool().putconn(raw)


# ─── DuckDB path (default, no DATABASE_URL set) ───────────────────────────────
else:
    import duckdb

    IS_POSTGRES = False

    _read_conn: duckdb.DuckDBPyConnection | None = None
    _read_lock = threading.Lock()
    _write_lock = threading.Lock()

    def _get_read_conn() -> duckdb.DuckDBPyConnection:
        global _read_conn
        if _read_conn is None:
            _read_conn = duckdb.connect(str(DUCK_PATH), read_only=True)
        return _read_conn

    def get_db() -> Generator[duckdb.DuckDBPyConnection, None, None]:
        """FastAPI dependency — yields the shared DuckDB read connection."""
        with _read_lock:
            yield _get_read_conn()

    def get_db_write() -> Generator[duckdb.DuckDBPyConnection, None, None]:
        """Write connection — fresh DuckDB connection, holds write lock."""
        global _read_conn
        with _write_lock:
            conn = duckdb.connect(str(DUCK_PATH), read_only=False)
            try:
                yield conn
            finally:
                conn.close()
        with _read_lock:
            if _read_conn is not None:
                try:
                    _read_conn.close()
                except Exception:
                    pass
            _read_conn = duckdb.connect(str(DUCK_PATH), read_only=True)
