"""
processing/qc.py — Data quality checks after each ingestion cycle

Runs a suite of checks against raw tables and logs results to raw_qc_log.
Designed to be run after pipeline.py completes ingestion.

WHY we flag rather than auto-remove outliers:
- A 20%+ daily return could be a genuine market event (COVID crash, flash crash)
  or a data error (split not adjusted, wrong price). Auto-removal would silently
  delete real market history. Flagging lets a human decide, and the ML model
  can be trained with or without flagged rows using the QC log as a filter.

WHY stale detection matters for a live recommendation engine:
- If VWCE.DE price data is 5 days stale, the volatility forecast and regime
  classification are based on old data. The Decision Center would show a
  recommendation derived from last week's market conditions — potentially
  dangerous for an investor making a monthly contribution decision.

WHY missing trading day detection is separate from stale detection:
- A missing trading day (e.g. gap on 2023-03-15) could be a genuine exchange
  holiday or a data gap. Stale = the whole series stopped updating. Missing =
  a hole in an otherwise active series. Both need different responses.
"""

import sys
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))
from db.init_db import get_connection, PH
from utils.logging_config import get_logger

log = get_logger(__name__)

# Liquid tickers that must have data on every trading day
LIQUID_TICKERS = [
    ("VWCE.DE",  "yfinance"),
    ("CSPX.L",   "yfinance"),
    ("^VIX",     "yfinance"),
    ("WIG20",    "stooq"),
]

# Max acceptable days behind today before flagging as stale
STALE_THRESHOLD_DAYS = 5

# Daily return threshold for outlier detection (absolute value)
OUTLIER_RETURN_THRESHOLD = 0.20


def log_qc(conn, check_name: str, table_name: str,
           issue_count: int, details: str) -> None:
    conn.execute(
        f"""
        INSERT INTO raw_qc_log (check_name, table_name, issue_count, details)
        VALUES ({PH}, {PH}, {PH}, {PH})
        """,
        [check_name, table_name, issue_count, details]
    )


def check_stale_prices(conn) -> list[dict]:
    """Flag tickers whose latest date is more than STALE_THRESHOLD_DAYS behind today."""
    today = date.today()
    issues = []

    for ticker, source in LIQUID_TICKERS:
        count = conn.execute(
            f"SELECT COUNT(*) FROM raw_prices WHERE ticker = {PH} AND source = {PH}",
            [ticker, source]
        ).fetchall()[0][0]

        if count == 0:
            detail = f"{ticker} ({source}): NO DATA"
            log_qc(conn, "stale_data", "raw_prices", 1, detail)
            issues.append({"ticker": ticker, "issue": "no_data"})
            continue

        rows = conn.execute(
            f"SELECT MAX(date) FROM raw_prices WHERE ticker = {PH} AND source = {PH}",
            [ticker, source]
        ).fetchall()
        latest = rows[0][0] if rows and rows[0][0] else None

        if latest is None:
            continue

        days_behind = (today - latest).days
        if days_behind > STALE_THRESHOLD_DAYS:
            detail = f"{ticker} ({source}): latest={latest}, {days_behind}d behind"
            log_qc(conn, "stale_data", "raw_prices", 1, detail)
            issues.append({"ticker": ticker, "days_behind": days_behind})
            log.warning("STALE: %s", detail)
        else:
            log.info("OK  %s: latest=%s (%dd behind)", ticker, latest, days_behind)

    if not issues:
        log_qc(conn, "stale_data", "raw_prices", 0, "All liquid tickers up to date")

    return issues


def check_missing_trading_days(conn) -> list[dict]:
    """
    Detect unexpected gaps in price series for liquid tickers.
    A gap > 5 calendar days on a weekday is flagged (excludes holiday clusters).

    WHY 5 calendar days: weekends account for 2 days, and some markets have
    3-4 day holiday breaks (Easter, Christmas). A gap > 5 days on a weekday
    suggests a genuine data issue rather than a scheduled closure.
    """
    issues = []

    for ticker, source in LIQUID_TICKERS:
        rows = conn.execute(
            f"""
            SELECT date,
                   LAG(date) OVER (ORDER BY date) AS prev_date,
                   date - LAG(date) OVER (ORDER BY date) AS gap_days
            FROM raw_prices
            WHERE ticker = {PH} AND source = {PH}
            ORDER BY date
            """,
            [ticker, source]
        ).fetchall()

        gaps = [(r[0], r[1], r[2]) for r in rows if r[2] and r[2] > 5]

        if gaps:
            detail = f"{ticker}: {len(gaps)} gaps >5d: " + \
                     ", ".join(f"{g[1]}→{g[0]}({g[2]}d)" for g in gaps[:5])
            log_qc(conn, "missing_trading_days", "raw_prices", len(gaps), detail)
            issues.append({"ticker": ticker, "gaps": gaps})
            log.warning("GAPS: %s has %d gaps >5 calendar days", ticker, len(gaps))
        else:
            log.info("OK  %s: no gaps >5d", ticker)

    return issues


def check_price_outliers(conn) -> list[dict]:
    """
    Flag daily returns > OUTLIER_RETURN_THRESHOLD without removing them.
    Outliers are logged for human review — they may be real (COVID crash)
    or data errors (unadjusted splits).
    """
    issues = []

    # WHY: VIX is a volatility index — 20%+ daily moves are structurally
    # normal (2007 subprime spike was +49% in a day). Applying a price-outlier
    # threshold to VIX would generate hundreds of false positives. Only
    # investable ETF prices are meaningful to check for outliers.
    price_tickers = [(t, s) for t, s in LIQUID_TICKERS if not t.startswith("^")]

    for ticker, source in price_tickers:
        rows = conn.execute(
            f"""
            SELECT date, adj_close,
                   ABS(LN(adj_close / LAG(adj_close) OVER (ORDER BY date))) AS abs_ret
            FROM raw_prices
            WHERE ticker = {PH} AND source = {PH}
            ORDER BY date
            """,
            [ticker, source]
        ).fetchall()

        outliers = [(r[0], r[1], r[2]) for r in rows
                    if r[2] is not None and r[2] > OUTLIER_RETURN_THRESHOLD]

        if outliers:
            detail = (
                f"{ticker}: {len(outliers)} days with |return|>{OUTLIER_RETURN_THRESHOLD:.0%}: "
                + ", ".join(f"{o[0]}({o[2]:.1%})" for o in outliers[:5])
            )
            log_qc(conn, "price_outlier", "raw_prices", len(outliers), detail)
            issues.append({"ticker": ticker, "outliers": outliers})
            log.warning("OUTLIERS: %s", detail)
        else:
            log.info("OK  %s: no outliers >%d%%", ticker, int(OUTLIER_RETURN_THRESHOLD * 100))

    return issues


def check_stale_macro(conn) -> list[dict]:
    """Check that key macro series are not stale."""
    today = date.today()
    issues = []

    series_checks = [
        ("DGS10",       "fred",   7),   # daily — allow a week (weekends + holidays)
        ("CPIAUCSL",    "fred",  70),   # monthly — FRED publishes CPI ~35-40d after period end; 70d avoids false positive
        ("FEDFUNDS",    "fred",  60),   # monthly
        ("HICP_EA_YOY", "ecb",  200),  # ECB HICP has longer publication lag (~3-4 months)
    ]

    for series_id, source, max_days in series_checks:
        count = conn.execute(
            f"SELECT COUNT(*) FROM raw_macro WHERE series_id = {PH} AND source = {PH}",
            [series_id, source]
        ).fetchall()[0][0]

        if count == 0:
            detail = f"{series_id} ({source}): NO DATA"
            log_qc(conn, "stale_macro", "raw_macro", 1, detail)
            issues.append({"series": series_id, "issue": "no_data"})
            log.warning("NO DATA: %s", detail)
            continue

        rows = conn.execute(
            f"SELECT MAX(date) FROM raw_macro WHERE series_id = {PH} AND source = {PH}",
            [series_id, source]
        ).fetchall()
        latest = rows[0][0] if rows and rows[0][0] else None
        if latest is None:
            continue

        days_behind = (today - latest).days
        if days_behind > max_days:
            detail = f"{series_id} ({source}): latest={latest}, {days_behind}d behind (max {max_days})"
            log_qc(conn, "stale_macro", "raw_macro", 1, detail)
            issues.append({"series": series_id, "days_behind": days_behind})
            log.warning("STALE: %s", detail)
        else:
            log.info("OK  %s: latest=%s (%dd behind)", series_id, latest, days_behind)

    if not issues:
        log_qc(conn, "stale_macro", "raw_macro", 0, "All macro series up to date")

    return issues


def check_feature_coverage(conn) -> dict:
    """
    Check that daily_features has acceptable NULL rates for key columns.
    High NULL rates indicate ingestion or feature engineering failures.
    """
    total = conn.execute("SELECT COUNT(*) FROM daily_features").fetchall()[0][0]
    if total == 0:
        log_qc(conn, "feature_coverage", "daily_features", 1, "daily_features is empty")
        return {}

    checks = [
        ("vix_close",      0.05),  # allow 5% NULL (weekends/holidays in FRED)
        ("yield_10y",      0.05),
        ("usdpln",         0.05),
        ("cpi_us_yoy",     0.02),
        ("fed_funds_rate", 0.02),
        ("nbp_rate",       0.02),
    ]

    issues = {}
    for col, max_null_rate in checks:
        null_count = conn.execute(
            f"SELECT COUNT(*) FROM daily_features WHERE {col} IS NULL"
        ).fetchall()[0][0]
        null_rate = null_count / total
        if null_rate <= max_null_rate:
            log.info("OK  %s: %.1f%% NULL (%d/%d)", col, null_rate * 100, null_count, total)
        else:
            log.warning("WARN %s: %.1f%% NULL (%d/%d)", col, null_rate * 100, null_count, total)
        if null_rate > max_null_rate:
            detail = f"{col}: {null_rate:.1%} NULL exceeds threshold {max_null_rate:.0%}"
            log_qc(conn, "feature_coverage", "daily_features", null_count, detail)
            issues[col] = null_rate

    if not issues:
        log_qc(conn, "feature_coverage", "daily_features", 0,
               f"All key features within NULL thresholds ({total} rows)")

    return issues


def run() -> dict:
    conn = get_connection()
    results = {}

    log.info("[1] Stale price check ...")
    results["stale_prices"] = check_stale_prices(conn)

    log.info("[2] Missing trading days ...")
    results["missing_days"] = check_missing_trading_days(conn)

    log.info("[3] Price outliers ...")
    results["outliers"] = check_price_outliers(conn)

    log.info("[4] Stale macro check ...")
    results["stale_macro"] = check_stale_macro(conn)

    log.info("[5] Feature coverage ...")
    results["feature_coverage"] = check_feature_coverage(conn)

    conn.commit()

    # Summary
    total_issues = sum(
        len(v) if isinstance(v, list) else len(v)
        for v in results.values()
    )
    log.info("QC complete — %d issues flagged, all logged to raw_qc_log.", total_issues)

    conn.close()
    return results


if __name__ == "__main__":
    log.info("=== Data Quality Checks ===")
    run()
    log.info("Done.")
