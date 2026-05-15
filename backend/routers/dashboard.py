"""
backend/routers/dashboard.py — GET /dashboard

Returns today's complete signal panel in one request so the frontend
makes a single API call to populate the entire dashboard page.

Response shape: DashboardResponse (see models.py)
- as_of: latest HMM prediction date
- regime: latest HMM state + probabilities (replaces circular LightGBM regime)
- regime_duration: Kaplan-Meier current regime age + survival statistics
- correlation: rolling PCA diversification index + pairwise correlations
- volatility: latest 21d and 63d vol forecasts with confidence bands
- fx: latest 21d and 63d USDPLN forecasts (point + 10th/90th pct)
- macro: key macro snapshot for the context panel
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import Annotated

from backend.database import get_db
from backend.hmm_utils import resolve_hmm_probs
from backend.models import (
    DashboardResponse, RegimeSignal, RegimeDurationSignal,
    CorrelationSnapshot, VolatilitySignal, FXSignal, MacroSnapshot,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

WINDOW_DAYS = 63  # must match ml/correlation_pca.py


@router.get("", response_model=DashboardResponse)
def get_dashboard(db: Annotated[object, Depends(get_db)]):

    # ------------------------------------------------------------------
    # 1. Latest HMM regime prediction (primary regime signal)
    # ------------------------------------------------------------------
    regime_row = db.execute("""
        SELECT date, state_label, prob_bull, prob_bear, prob_consolidation, model_version
        FROM hmm_predictions
        ORDER BY date DESC, predicted_at DESC
        LIMIT 1
    """).fetchone()

    if not regime_row:
        raise HTTPException(status_code=404, detail="No HMM predictions found. Run ml/hmm_regime.py train first.")

    as_of = regime_row[0]

    state, p_bull, p_bear, p_cons, p_stag = resolve_hmm_probs(
        regime_row[1], regime_row[2], regime_row[3], regime_row[4]
    )
    regime = RegimeSignal(
        state              = state,
        prob_bull          = p_bull,
        prob_bear          = p_bear,
        prob_consolidation = p_cons,
        prob_stagflation   = p_stag,
        model_version      = regime_row[5] or "hmm_v1",
    )

    # ------------------------------------------------------------------
    # 2. Regime duration (Kaplan-Meier current age + survival prob)
    # ------------------------------------------------------------------
    regime_duration = None
    try:
        import math
        import pandas as pd

        hmm_rows = db.execute("""
            SELECT date, state_label FROM hmm_predictions ORDER BY date DESC LIMIT 90
        """).fetchall()

        if hmm_rows:
            current_state = hmm_rows[0][1]   # keep stagflation as-is
            latest_dt  = pd.Timestamp(hmm_rows[0][0])
            start_dt   = latest_dt
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

            regime_duration = RegimeDurationSignal(
                current_state           = current_state,
                current_duration_months = current_duration,
                km_survival_at_current  = round(float(km_row[0]), 3) if km_row and km_row[0] is not None else None,
                km_survival_lower       = round(float(km_row[1]), 3) if km_row and km_row[1] is not None else None,
                km_survival_upper       = round(float(km_row[2]), 3) if km_row and km_row[2] is not None else None,
                median_duration         = int(stats_row[0]) if stats_row and stats_row[0] else None,
                p25_duration            = int(stats_row[1]) if stats_row and stats_row[1] else None,
                p75_duration            = int(stats_row[2]) if stats_row and stats_row[2] else None,
            )
    except Exception:
        pass  # regime_duration stays None — frontend handles it gracefully

    # ------------------------------------------------------------------
    # 3. Correlation / diversification snapshot
    # ------------------------------------------------------------------
    correlation = None
    try:
        div_row = db.execute("""
            SELECT computed_date, regime, div_index, pc1_explained
            FROM diversification_index
            ORDER BY computed_date DESC
            LIMIT 1
        """).fetchone()

        if div_row:
            latest_date = str(div_row[0])
            corr_rows = db.execute(f"""
                SELECT asset_pair, correlation
                FROM correlation_stats
                WHERE computed_date = '{latest_date}'
                  AND window_days = {WINDOW_DAYS}
                ORDER BY asset_pair
            """).fetchall()

            correlation = CorrelationSnapshot(
                computed_date         = latest_date,
                regime                = div_row[1],
                diversification_index = round(float(div_row[2]), 3) if div_row[2] is not None else None,
                pc1_explained         = round(float(div_row[3]), 3) if div_row[3] is not None else None,
                top_correlations      = [
                    {"pair": r[0], "r": round(float(r[1]), 3)}
                    for r in corr_rows if r[1] is not None
                ],
            )
    except Exception:
        pass  # correlation stays None

    # ------------------------------------------------------------------
    # 4. Latest vol forecasts (21d and 63d)
    # ------------------------------------------------------------------
    vol_rows = db.execute("""
        SELECT horizon_days, vol_forecast, vol_lower, vol_upper, model_version
        FROM volatility_forecasts
        WHERE date = (SELECT MAX(date) FROM volatility_forecasts)
          AND ticker = 'VWCE.DE'
        ORDER BY horizon_days
    """).fetchall()

    volatility = [
        VolatilitySignal(
            horizon_days  = r[0],
            vol_forecast  = r[1],
            vol_lower     = r[2],
            vol_upper     = r[3],
            model_version = r[4],
        )
        for r in vol_rows
    ]

    # ------------------------------------------------------------------
    # 5. Latest FX forecasts (21d and 63d)
    # ------------------------------------------------------------------
    fx_rows = db.execute("""
        SELECT pair, horizon_days, rate_point, rate_lower, rate_upper, model_version
        FROM fx_forecasts
        WHERE date = (SELECT MAX(date) FROM fx_forecasts)
          AND pair = 'USDPLN'
        ORDER BY horizon_days
    """).fetchall()

    fx = [
        FXSignal(
            pair          = r[0],
            horizon_days  = r[1],
            rate_point    = r[2],
            rate_lower    = r[3],
            rate_upper    = r[4],
            model_version = r[5],
        )
        for r in fx_rows
    ]

    # ------------------------------------------------------------------
    # 6. Macro snapshot
    # ------------------------------------------------------------------
    macro_row = db.execute("""
        SELECT vix_close, spread_10y_3m, spread_10y_2y, yield_curve_inverted,
               cpi_us_yoy, cpi_core_us_yoy, cpi_ea_yoy, cpi_pl_yoy,
               fed_funds_rate, ecb_rate, nbp_rate,
               usdpln, eurpln, wig20_ret_1d,
               acwi_ret_21d, acwi_ret_63d,
               hy_spread, sp500_earnings_yield
        FROM daily_features
        WHERE vix_close IS NOT NULL
        ORDER BY date DESC
        LIMIT 1
    """).fetchone()

    macro = MacroSnapshot(
        vix_close             = macro_row[0]  if macro_row else None,
        spread_10y_3m         = macro_row[1]  if macro_row else None,
        spread_10y_2y         = macro_row[2]  if macro_row else None,
        yield_curve_inverted  = macro_row[3]  if macro_row else None,
        cpi_us_yoy            = macro_row[4]  if macro_row else None,
        cpi_core_us_yoy       = macro_row[5]  if macro_row else None,
        cpi_ea_yoy            = macro_row[6]  if macro_row else None,
        cpi_pl_yoy            = macro_row[7]  if macro_row else None,
        fed_funds_rate        = macro_row[8]  if macro_row else None,
        ecb_rate              = macro_row[9]  if macro_row else None,
        nbp_rate              = macro_row[10] if macro_row else None,
        usdpln                = macro_row[11] if macro_row else None,
        eurpln                = macro_row[12] if macro_row else None,
        wig20_ret_1d          = macro_row[13] if macro_row else None,
        acwi_ret_21d          = macro_row[14] if macro_row else None,
        acwi_ret_63d          = macro_row[15] if macro_row else None,
        hy_spread             = macro_row[16] if macro_row else None,
        sp500_earnings_yield  = macro_row[17] if macro_row else None,
    )

    return DashboardResponse(
        as_of            = as_of,
        regime           = regime,
        regime_duration  = regime_duration,
        correlation      = correlation,
        volatility       = volatility,
        fx               = fx,
        macro            = macro,
    )
