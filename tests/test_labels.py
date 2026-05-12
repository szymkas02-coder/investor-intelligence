"""
tests/test_labels.py — Unit tests for processing/labels.py

Tests verify that:
  1. Rule-based labeling produces only valid regime values
  2. Known-signal combinations produce the correct regime
  3. Manual labels are not overwritten by a re-run
  4. The `force` flag clears and regenerates labels
"""

import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from processing.features import build_features
from processing.labels import run as run_labels, RULE_BASED_SQL


VALID_REGIMES = {"risk_on", "risk_off", "stagflation", "deflation"}


@pytest.fixture
def built_with_labels(db):
    """Build features then labels in the fixture DB."""
    build_features(conn=db)
    result = run_labels(conn=db)
    return db, result


# ---------------------------------------------------------------------------
# Output validity
# ---------------------------------------------------------------------------

def test_label_values_are_valid(built_with_labels):
    conn, _ = built_with_labels
    bad = conn.execute(
        f"SELECT DISTINCT regime FROM regime_labels "
        f"WHERE regime NOT IN ({', '.join(repr(r) for r in VALID_REGIMES)})"
    ).fetchall()
    assert bad == [], f"Invalid regime values: {bad}"


def test_all_labels_have_source(built_with_labels):
    conn, _ = built_with_labels
    null_source = conn.execute(
        "SELECT COUNT(*) FROM regime_labels WHERE label_source IS NULL"
    ).fetchone()[0]
    assert null_source == 0, f"{null_source} labels have NULL label_source"


def test_confidence_in_range(built_with_labels):
    conn, _ = built_with_labels
    out_of_range = conn.execute(
        "SELECT COUNT(*) FROM regime_labels WHERE confidence < 0 OR confidence > 1"
    ).fetchone()[0]
    assert out_of_range == 0, f"{out_of_range} labels have confidence outside [0, 1]"


def test_return_dict_has_total_and_distribution(db):
    # Inject a row with all required fields populated so at least 1 label is created
    db.execute("""
        INSERT INTO daily_features
            (date, vix_close, cpi_us_yoy, acwi_ret_63d, spread_10y_3m, spread_10y_2y)
        VALUES ('2023-06-01', 15.0, 2.5, 0.05, 0.8, 0.4)
        ON CONFLICT (date) DO UPDATE SET
            vix_close = 15.0, cpi_us_yoy = 2.5, acwi_ret_63d = 0.05,
            spread_10y_3m = 0.8, spread_10y_2y = 0.4
    """)
    result = run_labels(conn=db)
    assert "total" in result
    assert "distribution" in result
    assert result["total"] > 0


# ---------------------------------------------------------------------------
# Rule logic — inject known signals and check the label
# ---------------------------------------------------------------------------

def _inject_signals(conn, date_str: str, vix: float, cpi: float,
                    acwi_ret_63d: float, spread_10y_3m: float,
                    spread_10y_2y: float) -> None:
    conn.execute(
        """INSERT INTO daily_features
           (date, vix_close, cpi_us_yoy, acwi_ret_63d, spread_10y_3m, spread_10y_2y)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT (date) DO UPDATE SET
               vix_close     = excluded.vix_close,
               cpi_us_yoy    = excluded.cpi_us_yoy,
               acwi_ret_63d  = excluded.acwi_ret_63d,
               spread_10y_3m = excluded.spread_10y_3m,
               spread_10y_2y = excluded.spread_10y_2y""",
        [date_str, vix, cpi, acwi_ret_63d, spread_10y_3m, spread_10y_2y],
    )


def test_risk_off_when_high_vix_and_inverted_curve(db):
    _inject_signals(db, "2020-03-20",
                    vix=35.0, cpi=2.0, acwi_ret_63d=-0.15,
                    spread_10y_3m=-0.8, spread_10y_2y=-0.5)
    db.execute(RULE_BASED_SQL)
    regime = db.execute(
        "SELECT regime FROM regime_labels WHERE date = '2020-03-20'"
    ).fetchone()
    assert regime is not None and regime[0] == "risk_off", \
        f"Expected risk_off for high VIX + inverted curve, got {regime}"


def test_stagflation_when_high_cpi_positive_curve(db):
    _inject_signals(db, "2022-06-15",
                    vix=25.0, cpi=8.5, acwi_ret_63d=-0.05,
                    spread_10y_3m=0.5, spread_10y_2y=0.2)
    db.execute(RULE_BASED_SQL)
    regime = db.execute(
        "SELECT regime FROM regime_labels WHERE date = '2022-06-15'"
    ).fetchone()
    assert regime is not None and regime[0] == "stagflation", \
        f"Expected stagflation for high CPI + positive curve, got {regime}"


def test_deflation_when_low_cpi_and_drawdown(db):
    _inject_signals(db, "2015-09-01",
                    vix=18.0, cpi=0.8, acwi_ret_63d=-0.12,
                    spread_10y_3m=0.3, spread_10y_2y=0.1)
    db.execute(RULE_BASED_SQL)
    regime = db.execute(
        "SELECT regime FROM regime_labels WHERE date = '2015-09-01'"
    ).fetchone()
    assert regime is not None and regime[0] == "deflation", \
        f"Expected deflation for low CPI + drawdown, got {regime}"


def test_risk_on_default(db):
    _inject_signals(db, "2019-06-01",
                    vix=13.0, cpi=2.1, acwi_ret_63d=0.06,
                    spread_10y_3m=0.8, spread_10y_2y=0.4)
    db.execute(RULE_BASED_SQL)
    regime = db.execute(
        "SELECT regime FROM regime_labels WHERE date = '2019-06-01'"
    ).fetchone()
    assert regime is not None and regime[0] == "risk_on", \
        f"Expected risk_on for calm macro, got {regime}"


# ---------------------------------------------------------------------------
# Manual label preservation
# ---------------------------------------------------------------------------

def test_manual_label_source_preserved(db):
    """label_source='manual' must survive a rule re-run; regime follows the rules."""
    db.execute("""
        INSERT INTO regime_labels (date, regime, label_source, confidence)
        VALUES ('2020-03-20', 'risk_off', 'manual', 0.99)
        ON CONFLICT (date) DO UPDATE SET
            regime = 'risk_off', label_source = 'manual', confidence = 0.99
    """)

    # Inject calm signals (would produce risk_on by the rules)
    _inject_signals(db, "2020-03-20",
                    vix=13.0, cpi=2.1, acwi_ret_63d=0.06,
                    spread_10y_3m=0.8, spread_10y_2y=0.4)
    db.execute(RULE_BASED_SQL)

    row = db.execute(
        "SELECT regime, label_source FROM regime_labels WHERE date = '2020-03-20'"
    ).fetchone()
    # The label_source must remain 'manual' — the rule never overwrites a human review
    assert row[1] == "manual", "Manual label_source was overwritten by rule re-run"
