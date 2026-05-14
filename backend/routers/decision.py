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

Projection — horizon-dependent ensemble:
  Different signals dominate at different horizons (evidence-based):
  - Momentum (1–3Y):  Jegadeesh-Titman (1993) — 3-12M momentum predicts 1-3Y returns
  - CAPE (2–10Y):     Campbell-Shiller (1988, 1998) — CAPE explains ~40% of 10Y variance
  - Base rate (5Y+):  DMS Yearbook 2025 — 5.5% real for globally diversified ACWI
  Weights are continuous functions of horizon, not discrete buckets.
  Each year of the Monte Carlo uses the weight appropriate for that horizon.
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
    cape_return:      float       # CAPE-implied annualised real return (Shiller E/P - RF)
    base_rate_return: float       # DMS long-run base rate (rate-adjusted)
    momentum_return:  float       # momentum-adjusted return estimate
    momentum_adj:     float       # raw momentum adjustment before bounding
    ensemble_median:  float       # horizon-weighted blend (at specified horizon)
    ensemble_std:     float
    weights:          dict        # weights at specified horizon {cape, base_rate, momentum}


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

def cape_to_decile(cape: float) -> int:
    for i, threshold in enumerate(CAPE_DECILE_BREAKS, start=1):
        if cape < threshold:
            return i
    return 10


def _horizon_weights(t: float) -> tuple[float, float, float]:
    """
    Compute (w_momentum, w_cape, w_base_rate) for horizon t (years).

    Evidence basis:
    - Momentum: Jegadeesh-Titman (1993), Fama-French (1996) — significant
      at 3–12 months, fades by 3 years, reverses at 5Y+. We use 63d ACWI
      return as proxy (strongest available signal in our features).
      Weight = max(0, 1 - t/3) * 0.40 — full 40% at t=0, zero at t≥3Y.
      Capped at 40% to prevent a single hot/cold market from dominating.

    - CAPE: Campbell-Shiller (1988, 1998, 2001) — CAPE explains ~5% of
      1Y return variance, ~40% of 10Y return variance. Bell curve peaked
      at t=5Y with std=3Y so it contributes meaningfully from ~2Y to ~12Y.
      Uses Gaussian bell: w = 0.55 * exp(-0.5 * ((t-5)/3)^2)

    - Base rate: DMS Yearbook 2025 — law of large numbers means the
      long-run equity premium dominates at very long horizons. Gets
      whatever weight remains: w_base = 1 - w_momentum - w_cape.

    All weights sum to 1.0 by construction.
    """
    w_mom  = max(0.0, 1.0 - t / 3.0) * 0.40
    w_cape = 0.55 * math.exp(-0.5 * ((t - 5.0) / 3.0) ** 2)
    # Ensure cape doesn't exceed what's left after momentum
    w_cape = min(w_cape, 1.0 - w_mom)
    w_base = max(0.0, 1.0 - w_mom - w_cape)
    # Renormalise to exactly 1.0
    total  = w_mom + w_cape + w_base
    return w_mom / total, w_cape / total, w_base / total


def _cape_shiller_return(
    cape: float,
    fed_funds_rate: Optional[float],
    cpi_us_yoy: Optional[float],
) -> tuple[float, float, int]:
    """
    CAPE-implied annualised real return using Shiller's E/P - RF formula.

    E/P = 1/CAPE (earnings yield)
    Real RF = Fed funds rate - CPI (approximate real risk-free rate)
    Expected real equity return ≈ E/P - Real_RF + equity risk premium
    ERP: DMS global average ~3.5% (Dimson-Marsh-Staunton 2025)

    Also returns the decile for display purposes.
    Fallback to Asness decile table if inputs are missing.

    Bounded to [0%, 15%] — prevents extreme readings from dominating.
    """
    decile = cape_to_decile(cape)
    cape_table_median, cape_std = CAPE_DECILE_RETURNS[decile]

    if cape > 0 and fed_funds_rate is not None and cpi_us_yoy is not None:
        earnings_yield = 1.0 / cape
        real_rf        = (fed_funds_rate / 100.0) - (cpi_us_yoy / 100.0)
        erp            = 0.035   # DMS global equity risk premium (2025)
        cape_return    = earnings_yield - max(0.0, real_rf) + erp
        # Blend 60% Shiller formula / 40% Asness table for robustness
        cape_return = 0.60 * cape_return + 0.40 * cape_table_median
        cape_return = max(0.00, min(0.15, cape_return))
    else:
        cape_return = cape_table_median

    return cape_return, cape_std, decile


def _momentum_return(
    acwi_ret_63d: Optional[float],
    cape: float,
) -> tuple[float, float]:
    """
    Momentum-based short-term return estimate.

    Uses ACWI 63d (≈3M) return as momentum signal — the onset of the
    Jegadeesh-Titman momentum effect (strongest 3-12M, fades by 3Y).

    CAPE dampening: when CAPE > 30 (expensive), momentum signal is
    dampened by 50% — overvalued markets with momentum are more dangerous
    (2000 tech peak had strong momentum AND extreme CAPE).

    Returns (momentum_return, momentum_adj) where:
      momentum_return = BASE_RATE_MEDIAN + momentum_adj
    """
    momentum_adj = 0.0
    if acwi_ret_63d is not None:
        # Annualise roughly: 63d return → ×4 is too aggressive, use ×1.5
        # (momentum partially mean-reverts; we want the persistent component)
        raw_signal = acwi_ret_63d * 1.5
        # CAPE dampening: reduce signal linearly from 100% at CAPE=20 to 50% at CAPE=35+
        cape_damp   = max(0.5, 1.0 - max(0.0, cape - 20.0) / 30.0)
        momentum_adj = raw_signal * cape_damp * 0.25   # scale down: momentum is noisy
    momentum_adj = max(-0.020, min(0.020, momentum_adj))   # cap ±2%
    return BASE_RATE_MEDIAN + momentum_adj, momentum_adj


def _base_rate_return(fed_funds_rate: Optional[float], cpi_us_yoy: Optional[float]) -> float:
    """
    Long-run base rate, adjusted for current interest rate environment.

    DMS global ACWI base: 5.5% real p.a. (2025 Yearbook, 1900-2024).
    Adjustment: when real rates are very high (>2%), equity premium compresses.
    When real rates are negative, equity is relatively more attractive.
    Effect is modest (±0.5% max) — base rate is the most stable component.
    """
    if fed_funds_rate is not None and cpi_us_yoy is not None:
        real_rate = (fed_funds_rate / 100.0) - (cpi_us_yoy / 100.0)
        # Each 1% of real rate above 0% compresses equity return by ~0.1%
        # (equity risk premium shrinks as bonds become more competitive)
        rate_adj  = -0.10 * max(0.0, real_rate)
        rate_adj  = max(-0.005, min(0.005, rate_adj))   # cap ±0.5%
        return BASE_RATE_MEDIAN + rate_adj
    return BASE_RATE_MEDIAN


def _ensemble_return_at_horizon(
    cape:           float,
    acwi_ret_63d:   Optional[float],
    fed_funds_rate: Optional[float],
    cpi_us_yoy:     Optional[float],
    horizon_years:  float,
) -> tuple[float, float]:
    """
    Return (median, std) for the ensemble at a specific horizon.
    Used year-by-year in the Monte Carlo so each future year uses
    the weight appropriate for its remaining distance from today.
    """
    w_mom, w_cape, w_base = _horizon_weights(horizon_years)

    cape_ret, cape_std, _   = _cape_shiller_return(cape, fed_funds_rate, cpi_us_yoy)
    mom_ret,  _             = _momentum_return(acwi_ret_63d, cape)
    base_ret                = _base_rate_return(fed_funds_rate, cpi_us_yoy)

    median = w_mom * mom_ret + w_cape * cape_ret + w_base * base_ret

    # Uncertainty: weighted quadrature + dispersion penalty
    std = math.sqrt(
        w_mom**2  * BASE_RATE_STD**2 +
        w_cape**2 * cape_std**2       +
        w_base**2 * BASE_RATE_STD**2
    )
    spread = max(abs(cape_ret - base_ret), abs(mom_ret - base_ret))
    std = std + 0.25 * spread

    return median, std


def _ensemble_summary(
    cape:           float,
    acwi_ret_63d:   Optional[float],
    fed_funds_rate: Optional[float],
    cpi_us_yoy:     Optional[float],
    horizon_years:  float,
) -> dict:
    """
    Build the EnsembleComponents dict for the UI display.
    Uses the weights at the specified horizon for the summary card.
    """
    w_mom, w_cape, w_base  = _horizon_weights(horizon_years)
    cape_ret, cape_std, decile = _cape_shiller_return(cape, fed_funds_rate, cpi_us_yoy)
    mom_ret, mom_adj           = _momentum_return(acwi_ret_63d, cape)
    base_ret                   = _base_rate_return(fed_funds_rate, cpi_us_yoy)

    median = w_mom * mom_ret + w_cape * cape_ret + w_base * base_ret
    std    = math.sqrt(
        w_mom**2  * BASE_RATE_STD**2 +
        w_cape**2 * cape_std**2       +
        w_base**2 * BASE_RATE_STD**2
    )
    spread = max(abs(cape_ret - base_ret), abs(mom_ret - base_ret))
    std    = std + 0.25 * spread

    return {
        "cape_decile":        decile,
        "cape_return":        round(cape_ret,   4),
        "base_rate_return":   round(base_ret,   4),
        "momentum_return":    round(mom_ret,    4),
        "momentum_adj":       round(mom_adj,    4),
        "ensemble_median":    round(median,     4),
        "ensemble_std":       round(std,        4),
        "weights":            {
            "cape":       round(w_cape, 3),
            "base_rate":  round(w_base, 3),
            "momentum":   round(w_mom,  3),
        },
    }


# ---------------------------------------------------------------------------
# Decision engine
# ---------------------------------------------------------------------------

def _make_decision(
    prob_risk_off:    float,
    prob_stagflation: float,
    vol_21d:          Optional[float],
    usdpln_current:   Optional[float],
    usdpln_upper_21d: Optional[float],
    lang:             str = "en",
) -> tuple[str, str, list[str], list[str]]:
    """
    Returns (action, confidence, reasons, flags).
    action:     INVEST | DCA | WAIT
    confidence: HIGH | MEDIUM | LOW
    reasons:    list of strings explaining the action
    flags:      non-blocking warnings
    lang:       'en' or 'pl'
    """
    reasons: list[str] = []
    flags:   list[str] = []
    action = "INVEST"
    pl = (lang == "pl")

    # --- Primary signal: regime ---
    if prob_risk_off > 0.50:
        action = "WAIT"
        reasons.append(
            f"Prawdopodobieństwo risk-off wynosi {prob_risk_off:.0%} — powyżej progu 50%. "
            "Zachowanie kapitału do stabilizacji reżimu."
            if pl else
            f"Risk-off probability is {prob_risk_off:.0%} — above 50% threshold. "
            "Preserving capital until regime stabilises."
        )
    elif prob_risk_off > 0.30:
        action = "DCA"
        reasons.append(
            f"Prawdopodobieństwo risk-off wynosi {prob_risk_off:.0%} — podwyższone, ale poniżej 50%. "
            "Inwestuj w 2-3 tygodniowych transzach zamiast jednorazowo."
            if pl else
            f"Risk-off probability is {prob_risk_off:.0%} — elevated but below 50%. "
            "Invest in 2-3 weekly tranches rather than a lump sum."
        )

    # --- Stagflation overlay ---
    if prob_stagflation > 0.50 and (vol_21d or 0) > 0.20:
        if action == "INVEST":
            action = "DCA"
        reasons.append(
            f"Prawdopodobieństwo stagflacji wynosi {prob_stagflation:.0%} przy podwyższonej zmienności "
            f"({vol_21d:.1%}). Stagflacja obniża realne stopy zwrotu — DCA redukuje ryzyko timingu."
            if pl else
            f"Stagflation probability is {prob_stagflation:.0%} with elevated vol "
            f"({vol_21d:.1%}). Stagflation erodes real returns — DCA reduces timing risk."
        )

    # --- Volatility overlay ---
    if vol_21d and vol_21d > 0.25:
        if action == "INVEST":
            action = "DCA"
        reasons.append(
            f"Prognoza zmienności 21d wynosi {vol_21d:.1%} (w skali roku) — powyżej progu 25%. "
            "DCA wygładza cenę wejścia w okresach wysokiej zmienności."
            if pl else
            f"21-day volatility forecast is {vol_21d:.1%} (annualised) — above 25% "
            "threshold. DCA smooths entry price in high-vol periods."
        )

    # --- FX flag (non-blocking) ---
    if usdpln_current and usdpln_upper_21d:
        fx_upside = (usdpln_upper_21d - usdpln_current) / usdpln_current
        if fx_upside > 0.05:
            flags.append(
                f"PLN/USD: prognoza 90. percentyla na 21 dni to {usdpln_upper_21d:.2f} "
                f"(+{fx_upside:.1%} od {usdpln_current:.2f}). "
                "Zakup VWCE.DE może kosztować znacznie więcej PLN za miesiąc — "
                "rozważ poczekanie lub podział zakupu."
                if pl else
                f"PLN/USD: 90th-percentile 21d forecast is {usdpln_upper_21d:.2f} "
                f"(+{fx_upside:.1%} from {usdpln_current:.2f}). "
                "Buying VWCE.DE may cost significantly more PLN in a month — "
                "consider waiting or splitting the purchase."
            )

    # --- Default reason if investing ---
    if action == "INVEST" and not reasons:
        reasons.append(
            f"Sygnały reżimu są korzystne (prawdop. risk-off {prob_risk_off:.0%}, "
            f"stagflacja {prob_stagflation:.0%}), a zmienność jest w normie. "
            "Jednorazowa miesięczna inwestycja jest odpowiednia."
            if pl else
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
    lang:    str = "en",
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
        lang             = lang,
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

    # Inputs for ensemble: CAPE, ACWI 63d return, macro rates
    inputs_row = db.execute("""
        SELECT sp500_pe_ratio, acwi_ret_63d, fed_funds_rate, cpi_us_yoy
        FROM daily_features
        WHERE sp500_pe_ratio IS NOT NULL
        ORDER BY date DESC
        LIMIT 1
    """).fetchone()
    # Use Shiller CAPE from cape_forecasts if available (more accurate than P/E ratio)
    cape_row = db.execute("""
        SELECT cape FROM cape_forecasts ORDER BY date DESC LIMIT 1
    """).fetchone()

    cape           = float(cape_row[0])      if cape_row    and cape_row[0]    else (float(inputs_row[0]) if inputs_row and inputs_row[0] else 30.0)
    acwi_ret_63d   = float(inputs_row[1])    if inputs_row  and inputs_row[1]  else None
    fed_funds_rate = float(inputs_row[2])    if inputs_row  and inputs_row[2]  else None
    cpi_us_yoy     = float(inputs_row[3])    if inputs_row  and inputs_row[3]  else None

    # Summary components at the specified horizon (for UI display card)
    components = _ensemble_summary(cape, acwi_ret_63d, fed_funds_rate, cpi_us_yoy, float(years))

    # Monte Carlo: each year uses horizon-appropriate weights.
    # Year 1 is momentum-heavy; year 10 is CAPE-heavy; year 20+ is base-rate-heavy.
    rng = np.random.default_rng(42)
    portfolio = np.full(n_paths, current_value_pln)
    bands: list[ProjectionBand] = []

    for yr in range(1, years + 1):
        # Remaining horizon at the start of this year = (years - yr + 1)
        # We use the midpoint of the year for weight calculation
        remaining = float(years - yr + 0.5)
        mu_annual, sigma_annual = _ensemble_return_at_horizon(
            cape, acwi_ret_63d, fed_funds_rate, cpi_us_yoy, remaining
        )
        mu_monthly    = mu_annual / 12
        sigma_monthly = sigma_annual / math.sqrt(12)

        monthly_returns = rng.normal(
            loc   = mu_monthly,
            scale = sigma_monthly,
            size  = (n_paths, 12),
        )
        for m in range(12):
            portfolio = portfolio * (1 + monthly_returns[:, m]) + monthly_pln

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
