"""
backend/routers/regime.py — Regime history endpoint

GET /regime/history?days=365
  Returns the last N days of regime predictions for the chart.
"""

from fastapi import APIRouter, Depends, Query
from typing import Annotated

from backend.database import get_db
from backend.models import RegimeHistoryResponse, RegimeHistoryRow

router = APIRouter(prefix="/regime", tags=["regime"])


@router.get("/history", response_model=RegimeHistoryResponse)
def get_regime_history(
    db:   Annotated[object, Depends(get_db)],
    days: int = Query(default=365, ge=30, le=3650),
):
    # Latest model version
    mv = db.execute("""
        SELECT model_version
        FROM regime_predictions
        ORDER BY predicted_at DESC
        LIMIT 1
    """).fetchone()

    if not mv:
        return RegimeHistoryResponse(model_version="none", rows=[])

    model_version = mv[0]

    rows = db.execute(f"""
        SELECT date, regime_pred,
               prob_risk_on, prob_risk_off, prob_stagflation, prob_deflation
        FROM regime_predictions
        WHERE model_version = '{model_version}'
          AND date >= (CURRENT_DATE - INTERVAL '{days} days')
        ORDER BY date
    """).fetchall()

    return RegimeHistoryResponse(
        model_version = model_version,
        rows = [
            RegimeHistoryRow(
                date             = r[0],
                regime_pred      = r[1],
                prob_risk_on     = r[2],
                prob_risk_off    = r[3],
                prob_stagflation = r[4],
                prob_deflation   = r[5],
            )
            for r in rows
        ],
    )
