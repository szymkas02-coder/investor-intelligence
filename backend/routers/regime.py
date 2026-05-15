"""
backend/routers/regime.py — Regime history endpoint

GET /regime/history?days=365
  Returns the last N days of HMM regime predictions for the history chart.
"""

from fastapi import APIRouter, Depends, Query
from typing import Annotated

from backend.database import get_db
from backend.hmm_utils import resolve_hmm_probs
from backend.models import RegimeHistoryResponse, RegimeHistoryRow

router = APIRouter(prefix="/regime", tags=["regime"])


@router.get("/history", response_model=RegimeHistoryResponse)
def get_regime_history(
    db:   Annotated[object, Depends(get_db)],
    days: int = Query(default=365, ge=30, le=3650),
):
    mv = db.execute("""
        SELECT model_version FROM hmm_predictions ORDER BY predicted_at DESC LIMIT 1
    """).fetchone()

    if not mv:
        return RegimeHistoryResponse(model_version="none", rows=[])

    model_version = mv[0]

    rows = db.execute(f"""
        SELECT date, state_label, prob_bull, prob_bear, prob_consolidation
        FROM hmm_predictions
        WHERE model_version = '{model_version}'
          AND date >= (CURRENT_DATE - INTERVAL '{days} days')
        ORDER BY date
    """).fetchall()

    result_rows = []
    for r in rows:
        state, p_bull, p_bear, p_cons, p_stag = resolve_hmm_probs(r[1], r[2], r[3], r[4])
        result_rows.append(RegimeHistoryRow(
            date               = r[0],
            state              = state,
            prob_bull          = p_bull,
            prob_bear          = p_bear,
            prob_consolidation = p_cons,
            prob_stagflation   = p_stag,
        ))

    return RegimeHistoryResponse(model_version=model_version, rows=result_rows)
