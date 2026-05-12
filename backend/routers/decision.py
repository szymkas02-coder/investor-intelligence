"""
backend/routers/decision.py — Decision engine + long-term projection

GET /decision          — monthly investment recommendation
GET /decision/projection?years=20&monthly_pln=500  — long-term portfolio projection

WHY a rule-based decision engine rather than another ML model:
  The decision output ("invest now" vs "wait") is a high-stakes, low-frequency
  action (once per month). A rule-based engine whose logic the investor can read
  and understand is more trustworthy than a black-box classifier for this use
  case. The ML models (regime, vol, FX) provide probabilistic inputs; the
  decision layer translates those into an actionable recommendation using
  explicit, auditable rules. This matches how professional investment committees
  work: models inform the decision, humans (or rules) make it.

Decision logic:
  - risk_off probability > 0.5  → WAIT  (preserve capital)
  - risk_off probability > 0.3  → DCA   (invest in tranches, not lump sum)
  - stagflation probability > 0.5 AND vol_21d > 0.20 → DCA
  - vol_21d forecast > 0.25     → DCA   (elevated near-term uncertainty)
  - usdpln rate_upper (90th pct, 21d) > current * 1.05 → FLAG_FX
    (PLN expected to weaken significantly — buying USD-denominated ETF costs more)
  - otherwise                   → INVEST (lump sum is fine)

Projection:
  Uses CAPE-implied return distribution from Asness (2012) decile table.
  Runs a Monte Carlo with 10,000 paths over the specified horizon.
  Returns median, 10th, and 90th percentile terminal values.
"""

import math
import os
from datetime import date
from typing import Annotated, Optional

import numpy as np
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backend.auth import get_current_user
from backend.database import get_db

router = APIRouter(prefix="/decision", tags=["decision"])


# ---------------------------------------------------------------------------
# Response models (local — specific to this router)
# ---------------------------------------------------------------------------

class SignalSummary(BaseModel):
    prob_risk_off:    float
    prob_stagflation: float
    vol_21d_forecast: Optional[float]
    usdpln_current:   Optional[float]
    usdpln_upper_21d: Optional[float]
    cpi_us_yoy:       Optional[float]
    spread_10y_3m:    Optional[float]


class DecisionResponse(BaseModel):
    as_of:       date
    action:      str          # INVEST | DCA | WAIT
    confidence:  str          # HIGH | MEDIUM | LOW
    reasons:     list[str]
    flags:       list[str]    # non-blocking warnings shown in UI
    signals:     SignalSummary


class ProjectionBand(BaseModel):
    year:       int
    p10_pln:    float
    median_pln: float
    p90_pln:    float


class EnsembleComponents(BaseModel):
    cape_decile:      int
    cape_return:      float
    base_rate_return: float
    momentum_return:  float
    momentum_adj:     float
    ensemble_median:  float
    ensemble_std:     float
    weights:          dict


class ProjectionResponse(BaseModel):
    as_of:             date
    horizon_years:     int
    monthly_pln:       float
    current_value_pln: float
    ensemble:          EnsembleComponents
    paths:             list[ProjectionBand]


# ---------------------------------------------------------------------------
# CAPE decile → annualised US real return (Asness 2012 / AQR)
# Source: Asness, C. (2012). "An Old Friend: The Stock Market's Shiller P/E."
#         AQR Capital Management. Decile 1 = cheapest, 10 = most expensive.
# These are US-only estimates. We use them as one of three ensemble components.
# ---------------------------------------------------------------------------
CAPE_DECILE_RETURNS = {
    1:  (0.103, 0.060),
    2:  (0.090, 0.055),
    3:  (0.082, 0.058),
    4:  (0.075, 0.055),
    5:  (0.068, 0.060),
    6:  (0.062, 0.058),
    7:  (0.056, 0.062),
    8:  (0.040, 0.065),
    9:  (0.009, 0.068),
    10: (0.005, 0.072),
}

CAPE_DECILE_BREAKS = [9.6, 11.6, 13.6, 15.6, 17.3, 19.4, 21.1, 25.1]

# ---------------------------------------------------------------------------
# Long-run historical base rate (global equities, real, annualised)
# Source: Dimson, Marsh & Staunton — Global Investment Returns Yearbook 2025
#         (UBS/LBS). 125 years of data, 1900-2024.
#   - World equities:  5.2% real p.a.
#   - US equities:     6.6% real p.a.
#   - Ex-US equities:  4.3% real p.a.
# VWCE.DE tracks ACWI (~60% US / ~40% ex-US):
#   Blended DMS:   0.6 × 6.6% + 0.4 × 4.3% = 5.7% real
#   Vanguard VCMM forward (Q1 2026, real ~):  ~5.0-5.5%
#   Base rate adopted: 5.5% real (midpoint, conservative vs pure history)
# Std: DMS reports ~17% annual vol for single markets; for a globally
#      diversified portfolio we use 15% (diversification benefit).
# ---------------------------------------------------------------------------
BASE_RATE_MEDIAN = 0.055
BASE_RATE_STD    = 0.150

# ---------------------------------------------------------------------------
# Ensemble weights: CAPE signal / base rate / momentum-valuation
# ---------------------------------------------------------------------------
W_CAPE     = 0.30
W_BASE     = 0.50
W_MOMENTUM = 0.20


def cape_to_decile(cape: float) -> int:
    for i, threshold in enumerate(CAPE_DECILE_BREAKS, start=1):
        if cape < threshold:
            return i
    return 10


def _ensemble_return(
    cape: float,
    acwi_ret_63d: Optional[float],
    earnings_yield: Optional[float],
) -> tuple[float, float, dict]:
    """
    Compute ensemble median real return and std for Monte Carlo projection.

    Returns (median, std, components) where components is a dict for the UI.

    Component 1 — CAPE signal (US, Asness 2012):
      Uses the Asness decile table for the US market. Not geographically
      adjusted (ex-US CAPE omitted — insufficient data quality in pipeline).

    Component 2 — Long-run historical base rate (DMS 2025):
      5.5% real for a globally diversified ACWI portfolio. Anchors the
      estimate against short-term valuation noise.

    Component 3 — Momentum/valuation adjustment:
      Uses ACWI 63d return and earnings yield from daily_features.
      If earnings yield is high (cheap) and momentum positive → nudge up.
      If earnings yield is low (expensive) and momentum negative → nudge down.
      Bounded to ±1.5% to prevent dominating the ensemble.
    """
    decile = cape_to_decile(cape)
    cape_median, cape_std = CAPE_DECILE_RETURNS[decile]

    # Momentum/valuation component
    momentum_adj = 0.0
    if acwi_ret_63d is not None:
        momentum_adj += acwi_ret_63d * 0.5          # partial momentum signal
    if earnings_yield is not None:
        # earnings yield - 5% = excess over long-run base; scale to return adj
        momentum_adj += (earnings_yield - 0.05) * 0.3
    momentum_adj = max(-0.015, min(0.015, momentum_adj))  # cap ±1.5%
    momentum_median = BASE_RATE_MEDIAN + momentum_adj

    # Ensemble median (weighted average)
    ensemble_median = (
        W_CAPE     * cape_median     +
        W_BASE     * BASE_RATE_MEDIAN +
        W_MOMENTUM * momentum_median
    )

    # Ensemble std: weighted quadrature combination
    ensemble_std = math.sqrt(
        W_CAPE**2     * cape_std**2   +
        W_BASE**2     * BASE_RATE_STD**2 +
        W_MOMENTUM**2 * BASE_RATE_STD**2
    )
    # Scale up slightly if signals disagree (dispersion penalty)
    signal_spread = max(abs(cape_median - BASE_RATE_MEDIAN),
                        abs(momentum_median - BASE_RATE_MEDIAN))
    ensemble_std = ensemble_std + 0.3 * signal_spread

    components = {
        "cape_decile":        decile,
        "cape_return":        round(cape_median, 4),
        "base_rate_return":   round(BASE_RATE_MEDIAN, 4),
        "momentum_return":    round(momentum_median, 4),
        "momentum_adj":       round(momentum_adj, 4),
        "ensemble_median":    round(ensemble_median, 4),
        "ensemble_std":       round(ensemble_std, 4),
        "weights":            {"cape": W_CAPE, "base_rate": W_BASE, "momentum": W_MOMENTUM},
    }
    return ensemble_median, ensemble_std, components


# ---------------------------------------------------------------------------
# Decision engine
# ---------------------------------------------------------------------------

def _make_decision(
    prob_risk_off:    float,
    prob_stagflation: float,
    vol_21d:          Optional[float],
    usdpln_current:   Optional[float],
    usdpln_upper_21d: Optional[float],
) -> tuple[str, str, list[str], list[str]]:
    """
    Returns (action, confidence, reasons, flags).
    action:     INVEST | DCA | WAIT
    confidence: HIGH | MEDIUM | LOW
    reasons:    list of strings explaining the action
    flags:      non-blocking warnings
    """
    reasons: list[str] = []
    flags:   list[str] = []
    action = "INVEST"

    # --- Primary signal: regime ---
    if prob_risk_off > 0.50:
        action = "WAIT"
        reasons.append(
            f"Risk-off probability is {prob_risk_off:.0%} — above 50% threshold. "
            "Preserving capital until regime stabilises."
        )
    elif prob_risk_off > 0.30:
        action = "DCA"
        reasons.append(
            f"Risk-off probability is {prob_risk_off:.0%} — elevated but below 50%. "
            "Invest in 2-3 weekly tranches rather than a lump sum."
        )

    # --- Stagflation overlay ---
    if prob_stagflation > 0.50 and (vol_21d or 0) > 0.20:
        if action == "INVEST":
            action = "DCA"
        reasons.append(
            f"Stagflation probability is {prob_stagflation:.0%} with elevated vol "
            f"({vol_21d:.1%}). Stagflation erodes real returns — DCA reduces timing risk."
        )

    # --- Volatility overlay ---
    if vol_21d and vol_21d > 0.25:
        if action == "INVEST":
            action = "DCA"
        reasons.append(
            f"21-day volatility forecast is {vol_21d:.1%} (annualised) — above 25% "
            "threshold. DCA smooths entry price in high-vol periods."
        )

    # --- FX flag (non-blocking) ---
    if usdpln_current and usdpln_upper_21d:
        fx_upside = (usdpln_upper_21d - usdpln_current) / usdpln_current
        if fx_upside > 0.05:
            flags.append(
                f"PLN/USD: 90th-percentile 21d forecast is {usdpln_upper_21d:.2f} "
                f"(+{fx_upside:.1%} from {usdpln_current:.2f}). "
                "Buying VWCE.DE may cost significantly more PLN in a month — "
                "consider waiting or splitting the purchase."
            )

    # --- Default reason if investing ---
    if action == "INVEST" and not reasons:
        reasons.append(
            f"Regime signals are benign (risk-off prob {prob_risk_off:.0%}, "
            f"stagflation prob {prob_stagflation:.0%}) and volatility is within "
            "normal range. Monthly lump sum investment is appropriate."
        )

    # --- Confidence ---
    if prob_risk_off > 0.65 or (prob_risk_off < 0.15 and (vol_21d or 0) < 0.15):
        confidence = "HIGH"
    elif prob_risk_off > 0.40 or (vol_21d or 0) > 0.22:
        confidence = "MEDIUM"
    else:
        confidence = "HIGH" if action == "INVEST" else "MEDIUM"

    return action, confidence, reasons, flags


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=DecisionResponse)
def get_decision(
    db:      Annotated[object, Depends(get_db)],
    _user:   Annotated[str, Depends(get_current_user)],
):
    # Latest regime probs
    regime_row = db.execute("""
        SELECT date, prob_risk_off, prob_stagflation
        FROM regime_predictions
        ORDER BY date DESC, predicted_at DESC
        LIMIT 1
    """).fetchone()

    as_of          = regime_row[0] if regime_row else date.today()
    prob_risk_off  = float(regime_row[1]) if regime_row else 0.0
    prob_stagflat  = float(regime_row[2]) if regime_row else 0.0

    # Latest vol forecast (21d)
    vol_row = db.execute("""
        SELECT vol_forecast
        FROM volatility_forecasts
        WHERE ticker = 'VWCE.DE' AND horizon_days = 21
        ORDER BY date DESC
        LIMIT 1
    """).fetchone()
    vol_21d = float(vol_row[0]) if vol_row else None

    # Latest FX forecast (21d — upper bound = 90th pct)
    fx_row = db.execute("""
        SELECT rate_point, rate_upper
        FROM fx_forecasts
        WHERE pair = 'USDPLN' AND horizon_days = 21
        ORDER BY date DESC
        LIMIT 1
    """).fetchone()
    usdpln_point = float(fx_row[0]) if fx_row else None
    usdpln_upper = float(fx_row[1]) if fx_row else None

    # Current macro snapshot
    macro_row = db.execute("""
        SELECT usdpln, cpi_us_yoy, spread_10y_3m
        FROM daily_features
        WHERE usdpln IS NOT NULL
        ORDER BY date DESC
        LIMIT 1
    """).fetchone()
    usdpln_current = float(macro_row[0]) if macro_row and macro_row[0] is not None else None
    cpi_us_yoy     = float(macro_row[1]) if macro_row and macro_row[1] is not None else None
    spread_10y_3m  = float(macro_row[2]) if macro_row and macro_row[2] is not None else None

    action, confidence, reasons, flags = _make_decision(
        prob_risk_off    = prob_risk_off,
        prob_stagflation = prob_stagflat,
        vol_21d          = vol_21d,
        usdpln_current   = usdpln_current,
        usdpln_upper_21d = usdpln_upper,
    )

    return DecisionResponse(
        as_of      = as_of,
        action     = action,
        confidence = confidence,
        reasons    = reasons,
        flags      = flags,
        signals    = SignalSummary(
            prob_risk_off    = prob_risk_off,
            prob_stagflation = prob_stagflat,
            vol_21d_forecast = vol_21d,
            usdpln_current   = usdpln_current,
            usdpln_upper_21d = usdpln_upper,
            cpi_us_yoy       = cpi_us_yoy,
            spread_10y_3m    = spread_10y_3m,
        ),
    )


@router.get("/projection", response_model=ProjectionResponse)
def get_projection(
    db:          Annotated[object, Depends(get_db)],
    user_id:     Annotated[str, Depends(get_current_user)],
    years:       int   = Query(default=20, ge=1,   le=50),
    monthly_pln: float = Query(default=500, ge=0, le=50000),
    n_paths:     int   = Query(default=10000, ge=1000, le=50000),
):
    # FX rates for currency conversion
    fx_row = db.execute("""
        SELECT eurpln, usdpln FROM daily_features
        WHERE eurpln IS NOT NULL AND usdpln IS NOT NULL
        ORDER BY date DESC LIMIT 1
    """).fetchone()
    eurpln = float(fx_row[0]) if fx_row else 4.25
    usdpln = float(fx_row[1]) if fx_row else 3.85
    gbppln = eurpln * 1.17

    EUR_TICKERS = {'VWCE.DE', 'IUSQ.DE', 'SPPW.DE', 'ZPRV.DE', 'ZPRX.DE'}
    GBP_TICKERS = {'IWDA.L', 'CSPX.L', 'CNDX.L', 'IDTL.L', 'IGLN.L',
                   'EIMI.L', 'VUSA.L', 'VAGF.L', 'AGGH.L', 'IBTM.L'}

    # Per-ticker latest price (avoids global MAX date across all tickers)
    pos_rows = db.execute(f"""
        SELECT p.ticker, p.shares, r.adj_close
        FROM user_positions p
        LEFT JOIN (
            SELECT rp.ticker, rp.adj_close
            FROM raw_prices rp
            INNER JOIN (
                SELECT ticker, MAX(date) AS max_date
                FROM raw_prices WHERE source = 'yfinance'
                GROUP BY ticker
            ) latest ON rp.ticker = latest.ticker AND rp.date = latest.max_date
            WHERE rp.source = 'yfinance'
        ) r ON p.ticker = r.ticker
        WHERE p.user_id = '{user_id}'
    """).fetchall()

    current_value_pln = 0.0
    for ticker, shares, price_native in pos_rows:
        if price_native is None:
            continue
        if ticker in EUR_TICKERS:
            current_value_pln += shares * price_native * eurpln
        elif ticker in GBP_TICKERS:
            current_value_pln += shares * price_native * gbppln
        else:
            current_value_pln += shares * price_native * usdpln

    # Inputs for ensemble: CAPE, ACWI 63d return, S&P earnings yield
    inputs_row = db.execute("""
        SELECT sp500_pe_ratio, acwi_ret_63d, sp500_earnings_yield
        FROM daily_features
        WHERE sp500_pe_ratio IS NOT NULL
        ORDER BY date DESC
        LIMIT 1
    """).fetchone()
    cape            = float(inputs_row[0]) if inputs_row and inputs_row[0] else 30.0
    acwi_ret_63d    = float(inputs_row[1]) if inputs_row and inputs_row[1] else None
    earnings_yield  = float(inputs_row[2]) if inputs_row and inputs_row[2] else None

    median_ret, ret_std, components = _ensemble_return(cape, acwi_ret_63d, earnings_yield)

    # Monte Carlo: monthly compounding with normally distributed shocks
    rng = np.random.default_rng(42)
    mu_monthly    = median_ret / 12
    sigma_monthly = ret_std / math.sqrt(12)

    monthly_returns = rng.normal(
        loc   = mu_monthly,
        scale = sigma_monthly,
        size  = (n_paths, years * 12),
    )

    portfolio = np.full(n_paths, current_value_pln)
    bands: list[ProjectionBand] = []

    for month in range(years * 12):
        portfolio = portfolio * (1 + monthly_returns[:, month]) + monthly_pln
        if (month + 1) % 12 == 0:
            yr = (month + 1) // 12
            bands.append(ProjectionBand(
                year       = yr,
                p10_pln    = float(np.percentile(portfolio, 10)),
                median_pln = float(np.percentile(portfolio, 50)),
                p90_pln    = float(np.percentile(portfolio, 90)),
            ))

    return ProjectionResponse(
        as_of             = date.today(),
        horizon_years     = years,
        monthly_pln       = monthly_pln,
        current_value_pln = current_value_pln,
        ensemble          = EnsembleComponents(**components),
        paths             = bands,
    )
