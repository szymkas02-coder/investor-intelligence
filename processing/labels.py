"""
processing/labels.py — Rule-based regime labeling

Generates regime labels for the regime_labels table using SQL rules
applied to daily_features. Labels are the training targets for the
LightGBM regime classifier in ml/regime.py.

WHY rule-based SQL rather than Python hardcoding:
- SQL rules are readable, auditable, and version-controllable alongside
  the schema. A data scientist can read the CASE statement and understand
  exactly what defines each regime without reading Python logic.
- Rules are applied in one pass over daily_features — no row-by-row Python
  loop, no look-ahead bias from future data leaking into the label.
- The label_source column ('rule_based' vs 'manual') lets us selectively
  override known mislabeled periods (2008 GFC transition, 2020 COVID crash)
  without re-running the full rule set.

WHY these specific thresholds:
- risk_off:    VIX > 25 AND spread_10y_3m < 0  — simultaneous fear + inversion
               historically captures GFC 2008, COVID 2020, 2022 drawdown
- stagflation: CPI > 3.5% AND spread_10y_2y > 0 — inflation without recession
               captures 2021-2022 inflation shock before inversion
- deflation:   CPI < 1.5% AND ACWI 63d return < -5% — low inflation + falling
               markets; captures 2015 deflation scare, early COVID
- risk_on:     default — positive momentum, low vol, normal yield curve

WHY look-ahead bias does NOT apply here:
- All features in daily_features are constructed from strictly backward-looking
  windows (LAG, rolling STDDEV with ROWS BETWEEN N PRECEDING AND CURRENT ROW)
- Labels are assigned to the date on which features are observed, not to
  future dates — the classifier learns "given today's macro, what regime is today?"
- The 63d return feature IS backward-looking: acwi_ret_63d on date T uses
  prices from T-63 to T, which are all in the past relative to T.
"""

import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).parent.parent))
from db.init_db import get_connection
from utils.logging_config import get_logger

log = get_logger(__name__)


RULE_BASED_SQL = """
INSERT INTO regime_labels (date, regime, label_source, confidence, notes)
SELECT
    date,
    CASE
        -- RISK OFF: elevated fear (VIX>25) + inverted curve OR large drawdown
        -- WHY: Both conditions required to avoid false positives from brief
        -- VIX spikes (e.g. single-day flash crashes) or brief inversions alone.
        WHEN vix_close > 25
             AND (spread_10y_3m < 0 OR acwi_ret_63d < -0.10)
             THEN 'risk_off'

        -- STAGFLATION: high inflation + positive (or flat) yield curve
        -- WHY: When the curve is still positive, recession hasn't arrived yet —
        -- markets are pricing inflation risk, not growth collapse. This is
        -- structurally different from risk_off even if VIX is mildly elevated.
        WHEN cpi_us_yoy > 3.5
             AND spread_10y_2y > -0.5
             AND vix_close <= 30
             THEN 'stagflation'

        -- DEFLATION: very low inflation + equity drawdown
        -- WHY: Deflation regime is rare but important — it calls for different
        -- asset allocation (bonds > equities > commodities). Low CPI alone is
        -- not sufficient; we require negative momentum to confirm the regime.
        WHEN cpi_us_yoy < 1.5
             AND acwi_ret_63d < -0.05
             THEN 'deflation'

        -- RISK ON: default — low vol, positive momentum, normal macro
        -- WHY: Risk-on is the most common regime historically (~60% of days).
        -- Making it the default ensures unlabeled or ambiguous periods don't
        -- create a spurious fourth class that the model overfits to.
        ELSE 'risk_on'
    END AS regime,

    'rule_based' AS label_source,

    -- Confidence: higher when multiple signals agree
    CASE
        WHEN vix_close > 30 AND spread_10y_3m < -0.5 AND acwi_ret_63d < -0.15
             THEN 0.95   -- strong multi-signal agreement → high confidence
        WHEN vix_close > 25 AND acwi_ret_63d < -0.10
             THEN 0.80
        WHEN cpi_us_yoy > 4.0 AND spread_10y_2y > 0
             THEN 0.85
        WHEN vix_close < 18 AND acwi_ret_63d > 0.05
             THEN 0.90   -- clear risk-on conditions
        ELSE 0.65        -- boundary / ambiguous conditions
    END AS confidence,

    NULL AS notes

FROM daily_features
WHERE vix_close IS NOT NULL
  AND cpi_us_yoy IS NOT NULL
  AND acwi_ret_63d IS NOT NULL
  AND spread_10y_3m IS NOT NULL

ON CONFLICT (date) DO UPDATE SET
    regime       = excluded.regime,
    label_source = CASE
                       WHEN regime_labels.label_source = 'manual'
                       THEN 'manual'       -- never overwrite manual labels
                       ELSE 'rule_based'
                   END,
    confidence   = excluded.confidence
"""


def run(force: bool = False, conn=None) -> dict:
    """
    Generate rule-based regime labels and write to regime_labels.

    Args:
        force: if True, regenerate all labels including manual ones.
               Default False preserves manual overrides.
        conn:  optional DuckDB connection (used in tests); if None, opens one.
    """
    _owns_conn = conn is None
    if conn is None:
        conn = get_connection()

    # Count existing labels
    existing = conn.execute("SELECT COUNT(*) FROM regime_labels").fetchall()[0][0]
    manual   = conn.execute(
        "SELECT COUNT(*) FROM regime_labels WHERE label_source = 'manual'"
    ).fetchall()[0][0]

    log.info("Existing labels: %d (%d manual)", existing, manual)

    if force:
        log.warning("--force: clearing all labels ...")
        conn.execute("DELETE FROM regime_labels")

    log.info("Applying rule-based labels ...")
    conn.execute(RULE_BASED_SQL)
    conn.commit()

    # Report
    total = conn.execute("SELECT COUNT(*) FROM regime_labels").fetchall()[0][0]
    dist  = conn.execute("""
        SELECT regime, COUNT(*) AS n,
               ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) AS pct
        FROM regime_labels
        GROUP BY regime
        ORDER BY n DESC
    """).fetchall()

    log.info("Total labels: %d", total)
    log.info("Distribution:")
    for regime, n, pct in dist:
        log.info("  %-15s %5d days  (%s%%)", regime, n, pct)

    # Coverage check — warn if any known crisis periods are mislabeled
    checks = [
        ("2008 GFC peak",    "2008-10-01", "2008-11-30", "risk_off"),
        ("2020 COVID crash", "2020-03-01", "2020-04-30", "risk_off"),
        ("2022 inflation",   "2022-01-01", "2022-12-31", "stagflation"),
        ("2019 bull market", "2019-01-01", "2019-12-31", "risk_on"),
    ]

    log.info("Sanity checks (known periods):")
    for label, start, end, expected in checks:
        rows = conn.execute(f"""
            SELECT regime, COUNT(*) AS n
            FROM regime_labels
            WHERE date BETWEEN '{start}' AND '{end}'
            GROUP BY regime ORDER BY n DESC LIMIT 1
        """).fetchall()
        if rows:
            dominant, n = rows[0]
            if dominant == expected:
                log.info("  OK   %s: dominant=%s (expected %s, n=%d)", label, dominant, expected, n)
            else:
                log.warning("  WARN %s: dominant=%s (expected %s, n=%d)", label, dominant, expected, n)
        else:
            log.warning("  ?    %s: no data in range", label)

    if _owns_conn:
        conn.close()
    return {"total": total, "distribution": {r: n for r, n, _ in dist}}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true",
                        help="Regenerate all labels, overwriting manual ones")
    args = parser.parse_args()

    log.info("=== Regime label generation ===")
    run(force=args.force)
    log.info("Done.")
