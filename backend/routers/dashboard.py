"""
backend/routers/dashboard.py — GET /dashboard

Returns today's complete signal panel in one request so the frontend
makes a single API call to populate the entire dashboard page.

Response shape: DashboardResponse (see models.py)
- as_of: latest date with regime prediction
- regime: latest LightGBM regime probabilities
- volatility: latest 21d and 63d vol forecasts with confidence bands
- fx: latest 21d and 63d USDPLN forecasts (point + 10th/90th pct)
- macro: key macro snapshot for the "context" panel
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import Annotated

from backend.database import get_db
from backend.models import (
    DashboardResponse, RegimeSignal, VolatilitySignal,
    FXSignal, MacroSnapshot,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardResponse)
def get_dashboard(db: Annotated[object, Depends(get_db)]):

    # ------------------------------------------------------------------
    # 1. Latest regime prediction (most recent model version by date)
    # ------------------------------------------------------------------
    regime_row = db.execute("""
        SELECT date, regime_pred,
               prob_risk_on, prob_risk_off, prob_stagflation, prob_deflation,
               model_version
        FROM regime_predictions
        ORDER BY date DESC, predicted_at DESC
        LIMIT 1
    """).fetchone()

    if not regime_row:
        raise HTTPException(status_code=404, detail="No regime predictions found. Run ml/regime.py train first.")

    as_of = regime_row[0]

    regime = RegimeSignal(
        regime           = regime_row[1],
        prob_risk_on     = regime_row[2],
        prob_risk_off    = regime_row[3],
        prob_stagflation = regime_row[4],
        prob_deflation   = regime_row[5],
        model_version    = regime_row[6],
    )

    # ------------------------------------------------------------------
    # 2. Latest vol forecasts (21d and 63d)
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
    # 3. Latest FX forecasts (21d and 63d)
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
    # 4. Macro snapshot (latest non-null values)
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
        as_of      = as_of,
        regime     = regime,
        volatility = volatility,
        fx         = fx,
        macro      = macro,
    )
