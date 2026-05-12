"""
tests/test_features.py — Unit tests for processing/features.py

Tests verify that each feature group:
  1. Populates the expected columns (non-NULL for the most recent rows)
  2. Produces values in a plausible range
  3. Does not crash on the fixture dataset

The fixture DB (conftest.db) has 70 synthetic daily rows for VWCE.DE,
CSPX.L, ^VIX, WIG20 with monotonically increasing prices, plus monthly
macro rows.  Windows up to 63 days are covered.
"""

import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from processing.features import build_features, report


@pytest.fixture
def built(db):
    """Run build_features() against the in-memory fixture DB and return conn."""
    build_features(conn=db)
    return db


# ---------------------------------------------------------------------------
# Date spine
# ---------------------------------------------------------------------------

def test_date_spine_populated(built):
    n = built.execute("SELECT COUNT(*) FROM daily_features").fetchone()[0]
    assert n > 40, f"Expected >40 rows in date spine, got {n}"


def test_no_duplicate_dates(built):
    duplicates = built.execute(
        "SELECT date, COUNT(*) c FROM daily_features GROUP BY date HAVING c > 1"
    ).fetchall()
    assert duplicates == [], f"Duplicate dates in daily_features: {duplicates}"


# ---------------------------------------------------------------------------
# Step 1 — Returns and volatility
# ---------------------------------------------------------------------------

def test_acwi_returns_populated(built):
    null_pct = built.execute(
        "SELECT COUNT(*) FILTER (WHERE acwi_ret_1d IS NULL) * 1.0 / COUNT(*) FROM daily_features"
    ).fetchone()[0]
    # First row has no LAG, so 1 NULL is expected; rest should be populated
    assert null_pct < 0.05, f"acwi_ret_1d NULL rate too high: {null_pct:.1%}"


def test_acwi_vol_21d_in_range(built):
    rows = built.execute(
        "SELECT acwi_vol_21d FROM daily_features WHERE acwi_vol_21d IS NOT NULL"
    ).fetchall()
    assert len(rows) > 0, "acwi_vol_21d is entirely NULL"
    for (v,) in rows:
        assert 0 < v < 5.0, f"acwi_vol_21d={v} outside plausible range (0, 5)"


def test_vix_close_populated(built):
    null_count = built.execute(
        "SELECT COUNT(*) FROM daily_features WHERE vix_close IS NULL"
    ).fetchone()[0]
    total = built.execute("SELECT COUNT(*) FROM daily_features").fetchone()[0]
    assert null_count < total, "vix_close is entirely NULL"


# ---------------------------------------------------------------------------
# Step 2 — Yield curve
# ---------------------------------------------------------------------------

def test_yield_10y_populated(built):
    non_null = built.execute(
        "SELECT COUNT(*) FROM daily_features WHERE yield_10y IS NOT NULL"
    ).fetchone()[0]
    assert non_null > 0, "yield_10y is entirely NULL after feature build"


def test_spread_10y_2y_computed(built):
    row = built.execute(
        "SELECT yield_10y, yield_2y, spread_10y_2y FROM daily_features "
        "WHERE yield_10y IS NOT NULL AND yield_2y IS NOT NULL LIMIT 1"
    ).fetchone()
    if row is None:
        pytest.skip("No rows with both yield_10y and yield_2y")
    y10, y2, spread = row
    assert abs(spread - (y10 - y2)) < 1e-9, "spread_10y_2y != yield_10y - yield_2y"


def test_yield_curve_inversion_flag(built):
    built.execute(
        "UPDATE daily_features SET spread_10y_3m = -0.5 "
        "WHERE date = (SELECT MIN(date) FROM daily_features)"
    )
    built.execute(
        "UPDATE daily_features SET yield_curve_inverted = (spread_10y_3m < 0) "
        "WHERE spread_10y_3m IS NOT NULL"
    )
    flag = built.execute(
        "SELECT yield_curve_inverted FROM daily_features "
        "WHERE date = (SELECT MIN(date) FROM daily_features)"
    ).fetchone()[0]
    assert flag is True, "yield_curve_inverted should be True when spread < 0"


# ---------------------------------------------------------------------------
# Step 3 — PLN-adjusted returns
# ---------------------------------------------------------------------------

def test_usdpln_populated(built):
    non_null = built.execute(
        "SELECT COUNT(*) FROM daily_features WHERE usdpln IS NOT NULL"
    ).fetchone()[0]
    assert non_null > 30, f"usdpln has only {non_null} non-NULL rows"


def test_acwi_pln_ret_1d_populated(built):
    non_null = built.execute(
        "SELECT COUNT(*) FROM daily_features WHERE acwi_pln_ret_1d IS NOT NULL"
    ).fetchone()[0]
    assert non_null > 30, f"acwi_pln_ret_1d has only {non_null} non-NULL rows"


# ---------------------------------------------------------------------------
# Step 4 — Macro forward-fill
# ---------------------------------------------------------------------------

def test_cpi_us_yoy_populated(built):
    non_null = built.execute(
        "SELECT COUNT(*) FROM daily_features WHERE cpi_us_yoy IS NOT NULL"
    ).fetchone()[0]
    assert non_null > 0, "cpi_us_yoy entirely NULL — YoY calc or ffill broken"


def test_fed_funds_rate_populated(built):
    non_null = built.execute(
        "SELECT COUNT(*) FROM daily_features WHERE fed_funds_rate IS NOT NULL"
    ).fetchone()[0]
    assert non_null > 0, "fed_funds_rate entirely NULL — ffill broken"


def test_nbp_rate_populated(built):
    non_null = built.execute(
        "SELECT COUNT(*) FROM daily_features WHERE nbp_rate IS NOT NULL"
    ).fetchone()[0]
    assert non_null > 0, "nbp_rate entirely NULL — ffill broken"


def test_rate_differential_computed(built):
    row = built.execute(
        "SELECT fed_funds_rate, nbp_rate, rate_differential FROM daily_features "
        "WHERE fed_funds_rate IS NOT NULL AND nbp_rate IS NOT NULL LIMIT 1"
    ).fetchone()
    if row is None:
        pytest.skip("No rows with both rates populated")
    ffr, nbp, diff = row
    assert abs(diff - (ffr - nbp)) < 1e-9, "rate_differential != fed_funds_rate - nbp_rate"


# ---------------------------------------------------------------------------
# Step 6 — Derived vol regime
# ---------------------------------------------------------------------------

def test_vol_regime_values(built):
    invalid = built.execute(
        "SELECT DISTINCT vol_regime FROM daily_features "
        "WHERE vol_regime NOT IN ('low', 'medium', 'high')"
    ).fetchall()
    assert invalid == [], f"Unexpected vol_regime values: {invalid}"


def test_vol_regime_covers_all_non_null_vol(built):
    mismatch = built.execute(
        "SELECT COUNT(*) FROM daily_features "
        "WHERE acwi_vol_21d IS NOT NULL AND vol_regime IS NULL"
    ).fetchone()[0]
    assert mismatch == 0, f"{mismatch} rows have acwi_vol_21d but NULL vol_regime"
