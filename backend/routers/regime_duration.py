"""
backend/routers/regime_duration.py — GET /regime-duration

Returns current regime age and Kaplan-Meier survival statistics.
Uses HMM state as current regime (not the removed LightGBM model).
Also exposes the full KM table for the frontend survival curve.
"""

import math
import pandas as pd
from fastapi import APIRouter, Depends
from typing import Annotated

from backend.database import get_db

router = APIRouter(prefix="/regime-duration", tags=["regime_duration"])


@router.get("")
def get_regime_duration(db: Annotated[object, Depends(get_db)]):
    # Latest HMM state — walk back to find when current regime started
    hmm_rows = db.execute("""
        SELECT date, state_label
        FROM hmm_predictions
        ORDER BY date DESC
        LIMIT 90
    """).fetchall()

    if not hmm_rows:
        return {"error": "No HMM predictions. Run ml/hmm_regime.py train first."}

    current_state = hmm_rows[0][1]   # keep stagflation as its own state
    latest_date = pd.Timestamp(hmm_rows[0][0])

    regime_start = latest_date
    for h_date, h_label in hmm_rows:
        if h_label != current_state:
            break
        regime_start = pd.Timestamp(h_date)

    current_duration = max(1, math.ceil((latest_date - regime_start).days / 30.44))

    # KM survival at current duration
    km_row = db.execute(f"""
        SELECT km_survival, km_survival_lower, km_survival_upper
        FROM regime_duration_stats
        WHERE regime = '{current_state}'
          AND duration_months <= {current_duration}
        ORDER BY duration_months DESC
        LIMIT 1
    """).fetchone()

    # Derived summary statistics from KM table
    stats_row = db.execute(f"""
        SELECT
            MIN(CASE WHEN km_survival <= 0.50 THEN duration_months END) AS median_dur,
            MIN(CASE WHEN km_survival <= 0.75 THEN duration_months END) AS p25_dur,
            MIN(CASE WHEN km_survival <= 0.25 THEN duration_months END) AS p75_dur
        FROM regime_duration_stats
        WHERE regime = '{current_state}'
    """).fetchone()

    # Full KM table for survival curve chart
    km_table = db.execute(f"""
        SELECT duration_months, km_survival, km_survival_lower, km_survival_upper,
               n_at_risk, n_events
        FROM regime_duration_stats
        WHERE regime = '{current_state}'
        ORDER BY duration_months
    """).fetchall()

    return {
        "current_state":           current_state,
        "current_duration_months": current_duration,
        "km_survival_at_current":  round(float(km_row[0]), 3) if km_row and km_row[0] is not None else None,
        "km_survival_lower":       round(float(km_row[1]), 3) if km_row and km_row[1] is not None else None,
        "km_survival_upper":       round(float(km_row[2]), 3) if km_row and km_row[2] is not None else None,
        "median_duration":         int(stats_row[0]) if stats_row and stats_row[0] else None,
        "p25_duration":            int(stats_row[1]) if stats_row and stats_row[1] else None,
        "p75_duration":            int(stats_row[2]) if stats_row and stats_row[2] else None,
        "km_table": [
            {
                "t":        r[0],
                "survival": round(float(r[1]), 4) if r[1] is not None else None,
                "lower":    round(float(r[2]), 4) if r[2] is not None else None,
                "upper":    round(float(r[3]), 4) if r[3] is not None else None,
                "at_risk":  r[4],
                "events":   r[5],
            }
            for r in km_table
        ],
    }
