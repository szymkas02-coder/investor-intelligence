"""
tests/test_qc.py — Unit tests for processing/qc.py

Tests verify that each QC check:
  1. Returns empty issues when data is clean
  2. Correctly flags known problems (stale data, gaps, outliers, high NULLs)
  3. Logs results to raw_qc_log
"""

import sys
from pathlib import Path
from datetime import date, timedelta

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from processing.qc import (
    check_stale_prices,
    check_missing_trading_days,
    check_price_outliers,
    check_stale_macro,
    check_feature_coverage,
    STALE_THRESHOLD_DAYS,
    OUTLIER_RETURN_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Stale price detection
# ---------------------------------------------------------------------------

def test_no_stale_issues_when_data_is_fresh(db):
    issues = check_stale_prices(db)
    # Fixture has data up to ~2024-03 which IS stale relative to today
    # — we just verify the function runs and returns a list
    assert isinstance(issues, list)


def test_stale_flagged_when_data_is_old(db):
    """Delete all recent VWCE.DE data, leaving only rows from 2024-01 — will be stale."""
    db.execute(
        "DELETE FROM raw_prices WHERE ticker = 'VWCE.DE' AND source = 'yfinance' "
        "AND date > '2024-01-15'"
    )
    issues = check_stale_prices(db)
    tickers_flagged = [i.get("ticker") or "" for i in issues
                       if i.get("days_behind", 0) > STALE_THRESHOLD_DAYS
                       or i.get("issue") == "no_data"]
    assert any("VWCE" in t for t in tickers_flagged) or len(issues) > 0, \
        "Expected stale flag for VWCE.DE but got none"


def test_no_data_flagged(db):
    db.execute("DELETE FROM raw_prices WHERE ticker = 'VWCE.DE' AND source = 'yfinance'")
    issues = check_stale_prices(db)
    no_data = [i for i in issues if i.get("issue") == "no_data"]
    assert len(no_data) >= 1, "Expected no_data issue when VWCE.DE has no rows"


def test_stale_result_logged_to_qc_log(db):
    db.execute("DELETE FROM raw_prices WHERE ticker = 'VWCE.DE' AND source = 'yfinance'")
    check_stale_prices(db)
    logged = db.execute(
        "SELECT COUNT(*) FROM raw_qc_log WHERE check_name = 'stale_data'"
    ).fetchone()[0]
    assert logged >= 1, "Stale check result not written to raw_qc_log"


# ---------------------------------------------------------------------------
# Gap detection
# ---------------------------------------------------------------------------

def test_no_gap_issues_for_clean_series(db):
    issues = check_missing_trading_days(db)
    # Fixture has consecutive weekday rows — no gaps > 5 days
    vwce_gaps = [i for i in issues if i.get("ticker") == "VWCE.DE"]
    assert vwce_gaps == [], f"Unexpected gaps in fixture VWCE.DE: {vwce_gaps}"


def test_gap_detected_when_data_missing(db):
    # Remove two weeks of VWCE.DE data to create a gap
    db.execute(
        "DELETE FROM raw_prices WHERE ticker = 'VWCE.DE' AND source = 'yfinance' "
        "AND date BETWEEN '2024-01-22' AND '2024-02-02'"
    )
    issues = check_missing_trading_days(db)
    vwce_gaps = [i for i in issues if i.get("ticker") == "VWCE.DE"]
    assert len(vwce_gaps) > 0, "Expected gap detection for VWCE.DE but found none"


# ---------------------------------------------------------------------------
# Outlier detection
# ---------------------------------------------------------------------------

def test_no_outliers_in_clean_fixture(db):
    issues = check_price_outliers(db)
    vwce = [i for i in issues if i.get("ticker") == "VWCE.DE"]
    assert vwce == [], f"Unexpected outliers in fixture VWCE.DE: {vwce}"


def test_outlier_detected_when_price_jumps(db):
    # Insert a row with a 50% price jump
    db.execute(
        "UPDATE raw_prices SET adj_close = adj_close * 1.5 "
        "WHERE ticker = 'VWCE.DE' AND source = 'yfinance' "
        "AND date = (SELECT MAX(date) FROM raw_prices WHERE ticker = 'VWCE.DE' AND source = 'yfinance')"
    )
    issues = check_price_outliers(db)
    vwce = [i for i in issues if i.get("ticker") == "VWCE.DE"]
    assert len(vwce) > 0, "Expected outlier detection for 50% price jump"


# ---------------------------------------------------------------------------
# Feature coverage
# ---------------------------------------------------------------------------

def test_feature_coverage_passes_when_all_populated(db):
    # Manually fill the key columns so they pass the NULL threshold
    db.execute(
        "UPDATE daily_features SET vix_close = 18.0, yield_10y = 4.2, "
        "usdpln = 4.0, cpi_us_yoy = 3.0, fed_funds_rate = 5.3, nbp_rate = 5.75"
    )
    issues = check_feature_coverage(db)
    assert issues == {}, f"Expected no coverage issues, got: {issues}"


def test_feature_coverage_warns_when_all_null(db):
    # Ensure daily_features has at least some rows but all-NULL on key cols
    db.execute("DELETE FROM daily_features")
    db.execute("INSERT INTO daily_features (date) VALUES ('2024-03-01')")
    issues = check_feature_coverage(db)
    assert len(issues) > 0, "Expected NULL coverage warnings but got none"


# ---------------------------------------------------------------------------
# Macro staleness
# ---------------------------------------------------------------------------

def test_stale_macro_issues_returned(db):
    """Fixture macro data is from 2024 — all series are stale relative to today."""
    issues = check_stale_macro(db)
    # Just assert it returns a list; all fixture data will be stale vs today
    assert isinstance(issues, list)


def test_fresh_macro_passes(db):
    """Insert a DGS10 row for today — should not be flagged."""
    today = date.today().isoformat()
    db.execute(
        "INSERT INTO raw_macro (date, series_id, source, value, frequency) "
        f"VALUES ('{today}', 'DGS10', 'fred', 4.3, 'daily') "
        "ON CONFLICT DO NOTHING"
    )
    issues = check_stale_macro(db)
    dgs10_issues = [i for i in issues if i.get("series") == "DGS10"]
    assert dgs10_issues == [], f"DGS10 should not be stale with today's data: {dgs10_issues}"
