"""
backend/routers/signals.py — Multi-model signal panel

GET /signals  — latest outputs from all 4 models:
    HMM regime, NBER recession, CAPE 10Y signal, Regime duration (KM)

LightGBM regime removed — circular labels (99.5% train accuracy, discovers nothing).
HMM is now the primary regime signal (genuinely unsupervised, 1871–2026 Shiller data).
"""

import math
from pathlib import Path
import pandas as pd
from fastapi import APIRouter, Depends
from typing import Annotated
from datetime import date

from backend.database import get_db
from backend.hmm_utils import resolve_hmm_probs

_SHILLER_CSV = Path(__file__).parent.parent.parent / "shiller.csv"


_VWCE_US_WEIGHT    = 0.60   # VWCE geographic split (iShares factsheet 2024)
_VWCE_EXUS_WEIGHT  = 0.40
# Ex-US blended CAPE: ~0.75 * Developed_exUS(16) + 0.25 * EM(13) ≈ 15
# Source: Research Affiliates / StarCapital country CAPE estimates, 2024
_EXUS_CAPE_ESTIMATE = 15.0


def _compute_valuation() -> dict | None:
    """Compute trailing P/E, 5Y EPS CAGR, and VWCE-weighted global CAPE from shiller.csv."""
    try:
        df = pd.read_csv(_SHILLER_CSV)
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.sort_values("Date").dropna(subset=["SP500", "Earnings", "PE10"])
        latest = df.iloc[-1]

        trailing_pe = latest["SP500"] / latest["Earnings"] if latest["Earnings"] > 0 else None
        us_cape = round(float(latest["PE10"]), 1)

        # VWCE-weighted global CAPE: 60% US + 40% blended ex-US estimate
        global_cape = round(
            _VWCE_US_WEIGHT * us_cape + _VWCE_EXUS_WEIGHT * _EXUS_CAPE_ESTIMATE, 1
        )

        # 5Y EPS CAGR (60 months)
        df_sorted = df.reset_index(drop=True)
        eps_now = latest["Earnings"]
        eps_5y = df_sorted.iloc[-61]["Earnings"] if len(df_sorted) > 61 else None
        cagr_5y = ((eps_now / eps_5y) ** (1 / 5) - 1) if eps_5y and eps_5y > 0 else None

        # Historical median 5Y CAGR since 1950
        hist = df_sorted[df_sorted["Date"].dt.year >= 1950].copy()
        hist["cagr"] = (hist["Earnings"] / hist["Earnings"].shift(60)) ** (1 / 5) - 1
        hist_median = float(hist["cagr"].median()) if not hist["cagr"].isna().all() else None

        return {
            "date":                   str(latest["Date"].date()),
            "trailing_pe":            round(trailing_pe, 1) if trailing_pe else None,
            "us_cape":                us_cape,
            "global_cape":            global_cape,
            "exus_cape_estimate":     _EXUS_CAPE_ESTIMATE,
            "eps_growth_5y":          round(cagr_5y, 4) if cagr_5y is not None else None,
            "eps_growth_hist_median": round(hist_median, 4) if hist_median is not None else None,
        }
    except Exception:
        return None

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("")
def get_signals(db: Annotated[object, Depends(get_db)]):

    # 1. HMM regime (primary regime signal)
    hmm_row = db.execute("""
        SELECT date, state_label, prob_bull, prob_bear, prob_consolidation, model_version
        FROM hmm_predictions
        ORDER BY date DESC, predicted_at DESC LIMIT 1
    """).fetchone()

    hmm = None
    if hmm_row:
        state, p_bull, p_bear, p_cons, p_stag = resolve_hmm_probs(
            hmm_row[1], hmm_row[2], hmm_row[3], hmm_row[4]
        )
        hmm = {
            "date":               str(hmm_row[0]),
            "state":              state,
            "prob_bull":          p_bull,
            "prob_bear":          p_bear,
            "prob_consolidation": p_cons,
            "prob_stagflation":   p_stag,
            "model_version":      hmm_row[5],
            "note":               "signals.noteHmm",
        }

    # 2. Recession probability
    rec_row = db.execute("""
        SELECT date, recession_prob, recession_pred, model_version
        FROM recession_predictions
        ORDER BY date DESC LIMIT 1
    """).fetchone()

    recession = None
    if rec_row:
        recession = {
            "date":           str(rec_row[0]),
            "recession_prob": round(rec_row[1] or 0, 4),
            "recession_pred": bool(rec_row[2]),
            "model_version":  rec_row[3],
            "note":           "signals.noteRecession",
        }

    # 3. CAPE 10Y signal
    cape_row = db.execute("""
        SELECT date, cape, ret_q10, ret_q50, ret_q90, model_version
        FROM cape_forecasts
        ORDER BY date DESC LIMIT 1
    """).fetchone()

    cape = None
    if cape_row:
        cape = {
            "date":          str(cape_row[0]),
            "cape":          round(cape_row[1] or 0, 1),
            "ret_q10":       round(cape_row[2] or 0, 4),
            "ret_q50":       round(cape_row[3] or 0, 4),
            "ret_q90":       round(cape_row[4] or 0, 4),
            "model_version": cape_row[5],
            "note":          "signals.noteCape",
        }

    # 4. Regime duration (Kaplan-Meier)
    regime_duration = None
    try:
        hmm_rows = db.execute("""
            SELECT date, state_label FROM hmm_predictions ORDER BY date DESC LIMIT 90
        """).fetchall()

        if hmm_rows:
            current_state = hmm_rows[0][1]   # keep stagflation as-is
            latest_dt = pd.Timestamp(hmm_rows[0][0])
            start_dt  = latest_dt
            for h_date, h_label in hmm_rows:
                if h_label != current_state:
                    break
                start_dt = pd.Timestamp(h_date)
            current_duration = max(1, math.ceil((latest_dt - start_dt).days / 30.44))

            km_row = db.execute(f"""
                SELECT km_survival, km_survival_lower, km_survival_upper
                FROM regime_duration_stats
                WHERE regime = '{current_state}'
                  AND duration_months <= {current_duration}
                ORDER BY duration_months DESC LIMIT 1
            """).fetchone()

            stats_row = db.execute(f"""
                SELECT
                    MIN(CASE WHEN km_survival <= 0.50 THEN duration_months END),
                    MIN(CASE WHEN km_survival <= 0.75 THEN duration_months END),
                    MIN(CASE WHEN km_survival <= 0.25 THEN duration_months END)
                FROM regime_duration_stats
                WHERE regime = '{current_state}'
            """).fetchone()

            regime_duration = {
                "current_state":           current_state,
                "current_duration_months": current_duration,
                "km_survival_at_current":  round(float(km_row[0]), 3) if km_row and km_row[0] is not None else None,
                "km_survival_lower":       round(float(km_row[1]), 3) if km_row and km_row[1] is not None else None,
                "km_survival_upper":       round(float(km_row[2]), 3) if km_row and km_row[2] is not None else None,
                "median_duration":         int(stats_row[0]) if stats_row and stats_row[0] else None,
                "p25_duration":            int(stats_row[1]) if stats_row and stats_row[1] else None,
                "p75_duration":            int(stats_row[2]) if stats_row and stats_row[2] else None,
            }
    except Exception:
        pass

    # 5. Signal agreement summary
    bearish_signals = 0
    total_signals   = 0

    if hmm:
        total_signals += 1
        # stagflation = high-vol stress state (negative returns, highest volatility)
        if hmm["prob_bear"] > 0.3 or hmm["state"] in ("bear", "stagflation") or hmm["prob_stagflation"] > 0.3:
            bearish_signals += 1

    if recession:
        total_signals += 1
        if recession["recession_prob"] > 0.3:
            bearish_signals += 1

    if cape and cape["ret_q50"] < 0.03:
        total_signals += 1
        bearish_signals += 1

    if regime_duration and regime_duration.get("km_survival_at_current") is not None:
        # Low survival = regime near its historical end → slightly bullish (transition likely)
        # High survival = regime likely to persist → weight depends on current state
        total_signals += 1
        if hmm and hmm["state"] == "bear" and regime_duration["km_survival_at_current"] > 0.5:
            bearish_signals += 1  # bear regime still young → likely to persist

    if total_signals > 0:
        ratio = bearish_signals / total_signals
        agreement = "BULLISH" if ratio < 0.25 else "BEARISH" if ratio > 0.65 else "MIXED"
    else:
        agreement = "UNKNOWN"

    return {
        "as_of":            date.today().isoformat(),
        "hmm_regime":       hmm,
        "recession":        recession,
        "cape_10y":         cape,
        "regime_duration":  regime_duration,
        "valuation":        _compute_valuation(),
        "signal_agreement": agreement,
        "bearish_count":    bearish_signals,
        "total_signals":    total_signals,
    }
