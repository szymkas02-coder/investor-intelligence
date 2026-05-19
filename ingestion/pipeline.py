"""
ingestion/pipeline.py — Master ingestion orchestrator

Runs all data sources in dependency order, then triggers feature engineering,
regime labeling, and QC. Designed to be called daily by Cloud Scheduler.

WHY idempotency matters:
- Cloud Functions can retry on timeout or transient failure. Running pipeline.py
  twice on the same day must produce the same database state as running it once.
- Every ingestion module uses INSERT OR REPLACE / ON CONFLICT DO UPDATE, so
  re-inserting the same rows is a no-op on the data, just wasted API calls.
- get_latest_date() in each module ensures we only fetch from the last stored
  date forward — so a full re-run fetches ~0 new rows if already up to date.

WHY this order:
  1. Prices      — needed for PLN-adjusted return calculation in features.py
  2. FX          — needed for PLN join in features.py
  3. Macro       — FRED yields needed for yield curve features
  4. STOOQ       — Polish market data (WIG20)
  5. ECB         — EA yield curve and HICP
  6. Econdb      — Polish macro (NBP rate via FRED, CPI/GDP via WorldBank)
  7. Sentiment   — daily Finnhub news + calendar
  8. Fundamentals — weekly SEC EDGAR (skipped on non-Friday runs to save quota)
  9. features.py — rebuild daily_features from updated raw tables
  10. labels.py  — re-apply regime rules to new dates
  11. qc.py      — validate data freshness and flag issues

Crypto (CoinGecko) is omitted until API key is obtained.
WSB and pytrends are permanently skipped (see PROGRESS.md for rationale).
"""

import sys
import time
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.logging_config import get_logger

log = get_logger(__name__)


def run_step(name: str, fn, *args, **kwargs) -> dict:
    """Run a pipeline step, catch errors, and return a result dict."""
    log.info("[%s]", name)
    t0 = time.time()
    try:
        result = fn(*args, **kwargs)
        elapsed = time.time() - t0
        log.info("Done in %.1fs", elapsed)
        return {"status": "ok", "result": result, "elapsed": elapsed}
    except Exception as exc:
        elapsed = time.time() - t0
        log.error("ERROR after %.1fs: %s", elapsed, exc)
        return {"status": "error", "error": str(exc), "elapsed": elapsed}


def run(skip_fundamentals: bool = False,
        full_reload: bool = False) -> dict:
    """
    Run the full ingestion pipeline.

    Args:
        skip_fundamentals: skip SEC EDGAR (heavy, weekly cadence)
        full_reload: pass --full-reload to all ingestion modules
    """
    results = {}
    today = date.today()

    # ------------------------------------------------------------------
    # 1. Prices (yfinance UCITS ETFs + benchmarks)
    # ------------------------------------------------------------------
    from ingestion.prices import run as run_prices
    results["prices"] = run_step(
        "Prices (yfinance)", run_prices,
        full_reload=full_reload
    )

    # ------------------------------------------------------------------
    # 2. FX rates (NBP)
    # ------------------------------------------------------------------
    from ingestion.fx import run as run_fx
    results["fx"] = run_step(
        "FX rates (NBP)", run_fx,
        full_reload=full_reload
    )

    # ------------------------------------------------------------------
    # 3. Macro (FRED)
    # ------------------------------------------------------------------
    from ingestion.macro import run as run_macro
    results["macro"] = run_step(
        "Macro (FRED)", run_macro,
        full_reload=full_reload
    )

    # ------------------------------------------------------------------
    # 4. STOOQ (Polish + European market data)
    # ------------------------------------------------------------------
    from ingestion.stooq import run as run_stooq
    results["stooq"] = run_step(
        "Market data (STOOQ)", run_stooq
    )

    # ------------------------------------------------------------------
    # 5. ECB SDW
    # ------------------------------------------------------------------
    from ingestion.ecb import run as run_ecb
    results["ecb"] = run_step(
        "Macro (ECB SDW)", run_ecb
    )

    # ------------------------------------------------------------------
    # 6. Polish macro (NBP rate via FRED + WorldBank)
    # ------------------------------------------------------------------
    from ingestion.econdb import run as run_econdb
    results["econdb"] = run_step(
        "Polish macro (NBP+WorldBank)", run_econdb,
        full_reload=full_reload
    )

    # ------------------------------------------------------------------
    # 7. Sentiment + economic calendar (Finnhub)
    # ------------------------------------------------------------------
    from ingestion.sentiment import run as run_sentiment
    results["sentiment"] = run_step(
        "Sentiment (Finnhub)", run_sentiment
    )

    # ------------------------------------------------------------------
    # 8. SEC EDGAR fundamentals (weekly — skip on non-Friday by default)
    # WHY: SEC EDGAR rate limits are tight and P/E data changes quarterly.
    # Running daily wastes quota. We default to Friday-only runs; use
    # --fundamentals flag to force a run on any day.
    # ------------------------------------------------------------------
    is_friday = today.weekday() == 4
    if not skip_fundamentals and is_friday:
        from ingestion.fundamentals import run as run_fundamentals
        results["fundamentals"] = run_step(
            "Fundamentals (SEC EDGAR)", run_fundamentals
        )
    else:
        reason = "skip_fundamentals=True" if skip_fundamentals else "not Friday"
        log.info("[Fundamentals] Skipped (%s)", reason)
        results["fundamentals"] = {"status": "skipped", "reason": reason}

    # ------------------------------------------------------------------
    # 9. Feature engineering
    # ------------------------------------------------------------------
    from processing.features import build_features, report
    from db.init_db import get_connection

    def rebuild_features():
        from db.init_db import get_connection
        conn = get_connection()
        conn.execute("DELETE FROM daily_features")
        conn.commit()
        conn.close()
        build_features()
        conn2 = get_connection()
        report(conn2)
        conn2.close()

    results["features"] = run_step(
        "Feature engineering", rebuild_features
    )

    # ------------------------------------------------------------------
    # 10. Regime labels
    # ------------------------------------------------------------------
    from processing.labels import run as run_labels
    results["labels"] = run_step(
        "Regime labels", run_labels
    )

    # ------------------------------------------------------------------
    # 11. Regime duration (Kaplan-Meier survival analysis)
    # ------------------------------------------------------------------
    from ml.regime_duration import compute as compute_regime_duration
    results["regime_duration"] = run_step(
        "Regime duration (KM)", compute_regime_duration
    )

    # ------------------------------------------------------------------
    # 12. Correlation PCA (diversification index)
    # ------------------------------------------------------------------
    from ml.correlation_pca import compute as compute_correlation_pca
    results["correlation_pca"] = run_step(
        "Correlation PCA", compute_correlation_pca
    )

    # ------------------------------------------------------------------
    # 13. QC
    # ------------------------------------------------------------------
    from processing.qc import run as run_qc
    results["qc"] = run_step(
        "Data quality checks", run_qc
    )

    # ------------------------------------------------------------------
    # 14. HMM regime inference
    # ------------------------------------------------------------------
    from ml.hmm_regime import predict as hmm_predict
    results["hmm"] = run_step("HMM regime inference", hmm_predict)

    # ------------------------------------------------------------------
    # 15. Volatility forecasts
    # ------------------------------------------------------------------
    from ml.volatility import predict as vol_predict
    results["volatility"] = run_step("Volatility forecasts", vol_predict)

    # ------------------------------------------------------------------
    # 16. FX forecasts
    # ------------------------------------------------------------------
    from ml.currency import predict as fx_predict
    results["fx_forecast"] = run_step("FX forecasts", fx_predict)

    # ------------------------------------------------------------------
    # 17. Recession predictions
    # ------------------------------------------------------------------
    from ml.recession import predict as rec_predict
    results["recession"] = run_step("Recession predictions", rec_predict)

    # ------------------------------------------------------------------
    # 18. CAPE forecasts
    # ------------------------------------------------------------------
    from ml.cape_signal import predict as cape_predict
    results["cape"] = run_step("CAPE forecasts", cape_predict)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    ok = [k for k, v in results.items() if v.get("status") == "ok"]
    errors = [k for k, v in results.items() if v.get("status") == "error"]
    skipped = [k for k, v in results.items() if v.get("status") == "skipped"]
    total_elapsed = sum(v.get("elapsed", 0) for v in results.values()
                        if isinstance(v, dict))

    log.info("=" * 50)
    log.info("PIPELINE SUMMARY")
    log.info("=" * 50)
    log.info("OK:      %s", ok)
    if skipped:
        log.info("Skipped: %s", skipped)
    if errors:
        log.error("ERRORS:  %s", errors)
        for e in errors:
            log.error("  %s: %s", e, results[e].get("error"))

    log.info("Total time: %ds", int(total_elapsed))
    log.info("Run date:   %s", today)

    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run the full ingestion pipeline")
    parser.add_argument("--full-reload", action="store_true",
                        help="Reload all history (not just incremental)")
    parser.add_argument("--skip-fundamentals", action="store_true",
                        help="Skip SEC EDGAR fundamentals fetch")
    parser.add_argument("--fundamentals", action="store_true",
                        help="Force fundamentals fetch even if not Friday")
    args = parser.parse_args()

    skip_fund = args.skip_fundamentals or (
        not args.fundamentals and date.today().weekday() != 4
    )

    log.info("=== Investor Intelligence Pipeline — %s ===", date.today())
    run(skip_fundamentals=skip_fund, full_reload=args.full_reload)
