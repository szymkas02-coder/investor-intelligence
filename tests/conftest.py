"""
tests/conftest.py — Shared pytest fixtures for all test modules

Provides an in-memory DuckDB connection seeded with the full schema and
a minimal set of synthetic fixture rows. Every test gets a fresh connection
via the `db` fixture so tests are fully isolated from each other and from
the real data/investor_intelligence.duckdb file.

WHY in-memory DuckDB rather than mocking:
- The processing modules express all logic as SQL executed against DuckDB.
  Mocking the connection would test nothing meaningful. An in-memory DB
  lets us run the actual SQL, verify actual outputs, and catch real bugs
  (wrong JOIN keys, NULL propagation, ON CONFLICT semantics) that mocks
  would silently pass.
- In-memory means no teardown — the DB disappears when the fixture goes
  out of scope. No test pollution, no leftover files.
"""

import sys
from pathlib import Path
from datetime import date

import duckdb
import pytest

# Make project root importable
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _apply_schema(conn: duckdb.DuckDBPyConnection) -> None:
    import re
    schema_sql = (ROOT / "db" / "schema.sql").read_text()
    # Strip -- comments (they may contain semicolons that break naive splitting)
    schema_no_comments = re.sub(r"--[^\n]*", "", schema_sql)
    for stmt in schema_no_comments.split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)


def _seed_prices(conn: duckdb.DuckDBPyConnection) -> None:
    """
    Insert 70 daily rows for VWCE.DE, CSPX.L, ^VIX, WIG20 so that rolling
    windows (21d vol, 63d return) have enough history to produce non-NULL
    values for the last row.  Prices grow monotonically so log returns are
    small positive values — no division-by-zero or NULL from LAG.
    """
    rows = []
    base_prices = {
        ("VWCE.DE",  "yfinance"): 100.0,
        ("CSPX.L",   "yfinance"): 500.0,
        ("^VIX",     "yfinance"):  18.0,
        ("WIG20",    "stooq"):   1800.0,
        ("IGLN.L",   "yfinance"):  25.0,
        ("IDTL.L",   "yfinance"):   8.0,
        ("DX-Y.NYB", "yfinance"): 103.0,
    }
    from datetime import timedelta
    start = date(2024, 1, 2)
    for i in range(70):
        d = start + timedelta(days=i)
        if d.weekday() >= 5:          # skip weekends
            continue
        for (ticker, source), base in base_prices.items():
            price = base * (1 + 0.001 * i)   # 0.1% daily drift
            rows.append((d.isoformat(), ticker, source,
                         price, price, price, price, price, 1_000_000))

    conn.executemany(
        """INSERT INTO raw_prices
           (date, ticker, source, open, high, low, close, adj_close, volume)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT DO NOTHING""",
        rows,
    )


def _seed_fx(conn: duckdb.DuckDBPyConnection) -> None:
    from datetime import timedelta
    start = date(2024, 1, 2)
    rows = []
    for i in range(70):
        d = start + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        rows.append((d.isoformat(), "USD", "PLN", 4.0 + 0.001 * i, "nbp"))
        rows.append((d.isoformat(), "EUR", "PLN", 4.3 + 0.001 * i, "nbp"))
    conn.executemany(
        """INSERT INTO raw_fx (date, base_currency, quote_currency, rate, source)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT DO NOTHING""",
        rows,
    )


def _seed_macro(conn: duckdb.DuckDBPyConnection) -> None:
    macro_rows = [
        # FRED daily yields — one row per month is enough because features.py ffills
        ("2024-01-02", "DGS10",  "fred", 4.2,  "daily"),
        ("2024-02-01", "DGS10",  "fred", 4.3,  "daily"),
        ("2024-03-01", "DGS10",  "fred", 4.25, "daily"),
        ("2024-01-02", "DGS2",   "fred", 4.5,  "daily"),
        ("2024-02-01", "DGS2",   "fred", 4.6,  "daily"),
        ("2024-03-01", "DGS2",   "fred", 4.55, "daily"),
        ("2024-01-02", "DGS3MO", "fred", 5.2,  "daily"),
        ("2024-02-01", "DGS3MO", "fred", 5.3,  "daily"),
        ("2024-03-01", "DGS3MO", "fred", 5.25, "daily"),
        # FRED monthly
        ("2023-12-01", "CPIAUCSL",  "fred", 307.0, "monthly"),
        ("2024-01-01", "CPIAUCSL",  "fred", 308.4, "monthly"),
        ("2024-02-01", "CPIAUCSL",  "fred", 309.7, "monthly"),
        ("2024-03-01", "CPIAUCSL",  "fred", 310.5, "monthly"),
        ("2023-01-01", "CPIAUCSL",  "fred", 299.2, "monthly"),
        ("2023-02-01", "CPIAUCSL",  "fred", 300.8, "monthly"),
        ("2023-03-01", "CPIAUCSL",  "fred", 301.8, "monthly"),
        ("2023-12-01", "FEDFUNDS",  "fred", 5.33, "monthly"),
        ("2024-01-01", "FEDFUNDS",  "fred", 5.33, "monthly"),
        ("2024-02-01", "FEDFUNDS",  "fred", 5.33, "monthly"),
        ("2023-12-01", "IRSTCB01PLM156N", "fred", 5.75, "monthly"),
        ("2024-01-01", "IRSTCB01PLM156N", "fred", 5.75, "monthly"),
        ("2024-02-01", "IRSTCB01PLM156N", "fred", 5.75, "monthly"),
        ("2023-12-01", "UNRATE",    "fred", 3.7,  "monthly"),
        ("2024-01-01", "UNRATE",    "fred", 3.7,  "monthly"),
        # ECB
        ("2024-01-02", "EA_YIELD_10Y", "ecb", 2.5, "daily"),
        ("2024-02-01", "EA_YIELD_10Y", "ecb", 2.6, "daily"),
        ("2023-12-01", "HICP_EA_YOY",  "ecb", 2.9, "monthly"),
        ("2024-01-01", "HICP_EA_YOY",  "ecb", 2.8, "monthly"),
        # Econdb / WorldBank
        ("2022-01-01", "CPI_PL_YOY", "econdb", 5.1, "annual"),
        ("2023-01-01", "CPI_PL_YOY", "econdb", 6.8, "annual"),
        ("2023-12-01", "ECB_MAIN_RATE", "ecb", 4.5, "daily"),
        ("2024-01-02", "ECB_MAIN_RATE", "ecb", 4.5, "daily"),
        ("2023-10-01", "BAMLH0A0HYM2", "fred", 3.8, "daily"),
        ("2024-01-02", "BAMLH0A0HYM2", "fred", 3.9, "daily"),
    ]
    conn.executemany(
        """INSERT INTO raw_macro (date, series_id, source, value, frequency)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT DO NOTHING""",
        macro_rows,
    )


@pytest.fixture
def db() -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB connection with schema + synthetic fixture data."""
    conn = duckdb.connect(":memory:")
    _apply_schema(conn)
    _seed_prices(conn)
    _seed_fx(conn)
    _seed_macro(conn)
    yield conn
    conn.close()
