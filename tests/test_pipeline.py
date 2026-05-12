"""
tests/test_pipeline.py — Integration tests for ingestion/pipeline.py

Tests verify the orchestrator behaviour:
  1. run_step catches exceptions and returns a structured error dict
  2. run_step returns status='ok' on success
  3. The pipeline summary dict has the expected keys
  4. Skipped steps are recorded correctly
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from ingestion.pipeline import run_step


# ---------------------------------------------------------------------------
# run_step helper
# ---------------------------------------------------------------------------

def test_run_step_ok_on_success():
    result = run_step("test_step", lambda: {"rows": 5})
    assert result["status"] == "ok"
    assert result["result"] == {"rows": 5}
    assert result["elapsed"] >= 0


def test_run_step_error_on_exception():
    def boom():
        raise ValueError("something went wrong")

    result = run_step("bad_step", boom)
    assert result["status"] == "error"
    assert "something went wrong" in result["error"]
    assert result["elapsed"] >= 0


def test_run_step_passes_args_and_kwargs():
    def add(a, b=0):
        return a + b

    result = run_step("add_step", add, 3, b=4)
    assert result["status"] == "ok"
    assert result["result"] == 7


def test_run_step_elapsed_is_float():
    import time
    def slow():
        time.sleep(0.01)

    result = run_step("slow_step", slow)
    assert isinstance(result["elapsed"], float)
    assert result["elapsed"] >= 0.01


# ---------------------------------------------------------------------------
# Pipeline summary structure
# ---------------------------------------------------------------------------

def test_pipeline_summary_keys():
    """
    Run a minimal fake pipeline to verify the summary dict has the right keys.
    We patch all ingestion modules so no real network calls are made.
    """
    import unittest.mock as mock

    # Minimal stubs that return immediately
    stub = lambda **kw: {}

    with mock.patch("ingestion.prices.run", return_value={}), \
         mock.patch("ingestion.fx.run", return_value={}), \
         mock.patch("ingestion.macro.run", return_value={}), \
         mock.patch("ingestion.stooq.run", return_value={}), \
         mock.patch("ingestion.ecb.run", return_value={}), \
         mock.patch("ingestion.econdb.run", return_value={}), \
         mock.patch("ingestion.sentiment.run", return_value={}), \
         mock.patch("processing.features.build_features", return_value=None), \
         mock.patch("processing.features.report", return_value=None), \
         mock.patch("db.init_db.get_connection") as mock_conn, \
         mock.patch("processing.labels.run", return_value={"total": 0, "distribution": {}}), \
         mock.patch("processing.qc.run", return_value={}):

        mock_conn.return_value.__enter__ = lambda s: s
        mock_conn.return_value.__exit__ = mock.Mock(return_value=False)
        mock_conn.return_value.execute = mock.Mock()
        mock_conn.return_value.commit = mock.Mock()
        mock_conn.return_value.close = mock.Mock()

        from ingestion.pipeline import run
        results = run(skip_fundamentals=True)

    expected_keys = {"prices", "fx", "macro", "stooq", "ecb",
                     "econdb", "sentiment", "fundamentals", "features", "labels", "qc"}
    assert expected_keys == set(results.keys()), \
        f"Missing keys: {expected_keys - set(results.keys())}"


def test_fundamentals_skipped_when_flag_set():
    import unittest.mock as mock

    with mock.patch("ingestion.prices.run", return_value={}), \
         mock.patch("ingestion.fx.run", return_value={}), \
         mock.patch("ingestion.macro.run", return_value={}), \
         mock.patch("ingestion.stooq.run", return_value={}), \
         mock.patch("ingestion.ecb.run", return_value={}), \
         mock.patch("ingestion.econdb.run", return_value={}), \
         mock.patch("ingestion.sentiment.run", return_value={}), \
         mock.patch("processing.features.build_features", return_value=None), \
         mock.patch("processing.features.report", return_value=None), \
         mock.patch("db.init_db.get_connection") as mock_conn, \
         mock.patch("processing.labels.run", return_value={"total": 0, "distribution": {}}), \
         mock.patch("processing.qc.run", return_value={}):

        mock_conn.return_value.execute = mock.Mock()
        mock_conn.return_value.commit = mock.Mock()
        mock_conn.return_value.close = mock.Mock()

        from ingestion.pipeline import run
        results = run(skip_fundamentals=True)

    assert results["fundamentals"]["status"] == "skipped"
    assert results["fundamentals"]["reason"] == "skip_fundamentals=True"
