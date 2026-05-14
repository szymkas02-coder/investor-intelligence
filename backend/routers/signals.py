"""
backend/routers/signals.py — Multi-model signal panel

GET /signals  — latest outputs from all 4 models:
    LightGBM regime, HMM regime, NBER recession, CAPE 10Y signal
"""

from fastapi import APIRouter, Depends
from typing import Annotated, Optional
from datetime import date

from backend.database import get_db

router = APIRouter(prefix="/signals", tags=["signals"])


@router.get("")
def get_signals(db: Annotated[object, Depends(get_db)]):

    # 1. LightGBM regime (existing)
    lgbm_row = db.execute("""
        SELECT date, regime_pred, prob_risk_on, prob_risk_off,
               prob_stagflation, prob_deflation, model_version
        FROM regime_predictions
        ORDER BY date DESC, predicted_at DESC LIMIT 1
    """).fetchone()

    lgbm = None
    if lgbm_row:
        lgbm = {
            "date":             str(lgbm_row[0]),
            "regime":           lgbm_row[1],
            "prob_risk_on":     round(lgbm_row[2], 4),
            "prob_risk_off":    round(lgbm_row[3], 4),
            "prob_stagflation": round(lgbm_row[4], 4),
            "prob_deflation":   round(lgbm_row[5], 4),
            "model_version":    lgbm_row[6],
            "note":             "signals.noteLgbm",
        }

    # 2. HMM regime
    hmm_row = db.execute("""
        SELECT date, state_label, prob_bull, prob_bear, prob_consolidation, model_version
        FROM hmm_predictions
        ORDER BY date DESC, predicted_at DESC LIMIT 1
    """).fetchone()

    hmm = None
    if hmm_row:
        state = hmm_row[1]
        # HMM probabilities underflow to ~0 for non-active states at high confidence
        # Reconstruct clean probabilities: active state gets confidence, rest share remainder
        p_bull = float(hmm_row[2] or 0)
        p_bear = float(hmm_row[3] or 0)
        p_cons = float(hmm_row[4] or 0)
        total  = p_bull + p_bear + p_cons
        # Normalise 'stagflation' to 'consolidation' — they are the same HMM state
        # (HMM has no stagflation state; the label was historically mapped from consolidation)
        if state == "stagflation":
            state = "consolidation"
        if total < 0.01:
            # Underflow — assign 99% to active state
            p_bull = 0.99 if state == "bull" else 0.005
            p_bear = 0.99 if state == "bear" else 0.005
            p_cons = 0.99 if state == "consolidation" else 0.005
        hmm = {
            "date":               str(hmm_row[0]),
            "state":              state,
            "prob_bull":          round(p_bull, 4),
            "prob_bear":          round(p_bear, 4),
            "prob_consolidation": round(p_cons, 4),
            "model_version":      hmm_row[5],
            "note":               "signals.noteHmm",
        }

    # 3. Recession probability
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

    # 4. CAPE 10Y signal (latest available)
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

    # 5. Signal agreement summary
    bearish_signals = 0
    total_signals   = 0

    if lgbm:
        total_signals += 1
        if lgbm["prob_risk_off"] > 0.3 or lgbm["regime"] in ("risk_off", "stagflation"):
            bearish_signals += 1

    if hmm:
        total_signals += 1
        if hmm["prob_bear"] > 0.3 or hmm["state"] in ("bear", "stagflation"):
            bearish_signals += 1

    if recession:
        total_signals += 1
        if recession["recession_prob"] > 0.3:
            bearish_signals += 1

    if cape and cape["ret_q50"] < 0.03:
        total_signals += 1
        bearish_signals += 1

    if total_signals > 0:
        ratio = bearish_signals / total_signals
        agreement = "BULLISH" if ratio < 0.25 else "BEARISH" if ratio > 0.65 else "MIXED"
    else:
        agreement = "UNKNOWN"

    return {
        "as_of":           date.today().isoformat(),
        "lgbm_regime":     lgbm,
        "hmm_regime":      hmm,
        "recession":       recession,
        "cape_10y":        cape,
        "signal_agreement": agreement,
        "bearish_count":   bearish_signals,
        "total_signals":   total_signals,
    }
