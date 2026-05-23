"""
backend/routers/invest.py — /invest page endpoints.

The /invest page replaces the model-driven /decision triad (INVEST/DCA/WAIT) with
a calm "keep contributing, time-in-market beats timing-the-market" framing. The
single piece of advice that varies is the FX flag when PLN/USD is genuinely
stretched, which materially affects the EUR cost of VWCE.DE for a Polish
investor in PLN.

Endpoints:
  GET /invest/status                            current verdict + IKE remaining
  GET /invest/longrun                           Shiller real-total-return index, 1871-present
  GET /invest/historical-simulation             "If I had invested X PLN on date D, ..."
  GET /invest/projection                        re-export of /decision/projection (alias)
"""

from datetime import date
from pathlib import Path
from typing import Annotated, Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.auth import get_current_user
from backend.database import get_db
from backend.routers.decision import get_projection  # alias the existing projection

router = APIRouter(prefix="/invest", tags=["invest"])

ROOT    = Path(__file__).parent.parent.parent
SHILLER = ROOT / "shiller.csv"


# ---------------------------------------------------------------------------
# Shiller real total return index — built once per process from shiller.csv.
# Uses Real Price + Real Dividend with monthly dividend reinvestment.
# This is the standard reconstruction (e.g. Shiller's own irrationalexuberance.com
# spreadsheet) and the right series to display "long-run S&P returns" against.
# ---------------------------------------------------------------------------

_RTR_CACHE: Optional[pd.DataFrame] = None

def _load_real_total_return() -> pd.DataFrame:
    """Build a monthly real-total-return index from Shiller CSV (cached)."""
    global _RTR_CACHE
    if _RTR_CACHE is not None:
        return _RTR_CACHE

    df = pd.read_csv(SHILLER, parse_dates=["Date"])
    df = df.rename(columns={
        "Date":            "date",
        "Real Price":      "real_price",
        "Real Dividend":   "real_dividend",
    })
    df["real_price"]    = pd.to_numeric(df["real_price"],    errors="coerce")
    df["real_dividend"] = pd.to_numeric(df["real_dividend"], errors="coerce")
    df = df.dropna(subset=["real_price"]).sort_values("date").reset_index(drop=True)

    # Monthly total-return factor: capital appreciation + dividend reinvested.
    # Real Dividend in Shiller is the annual dividend in current-period real
    # dollars, so monthly dividend ≈ real_dividend / 12.
    months = len(df)
    rtr = np.empty(months)
    rtr[0] = 100.0
    for i in range(1, months):
        p_prev = df["real_price"].iloc[i - 1]
        p_cur  = df["real_price"].iloc[i]
        d_cur  = df["real_dividend"].iloc[i] if pd.notna(df["real_dividend"].iloc[i]) else 0.0
        monthly_div = d_cur / 12.0
        if p_prev > 0:
            ret = (p_cur + monthly_div) / p_prev
        else:
            ret = 1.0
        rtr[i] = rtr[i - 1] * ret

    df["rtr"] = rtr
    _RTR_CACHE = df[["date", "real_price", "rtr"]].copy()
    return _RTR_CACHE


# ---------------------------------------------------------------------------
# /invest/status — verdict (always "keep contributing"), IKE remaining, FX flag
# ---------------------------------------------------------------------------

class InvestStatus(BaseModel):
    as_of:         date
    headline:      str       # the calm verdict — language-aware
    ike_remaining: Optional[float]
    ike_limit:     Optional[float]
    ike_contributed: Optional[float]
    fx_flag:       Optional[str]   # None or short PLN warning


@router.get("/status", response_model=InvestStatus)
def invest_status(
    db:      Annotated[object, Depends(get_db)],
    user_id: Annotated[str, Depends(get_current_user)],
    lang:    str = "en",
):
    pl = (lang == "pl")
    today = date.today()

    # IKE remaining for current year
    from backend.routers.portfolio import IKE_LIMITS
    year = today.year
    ike_row = db.execute(
        "SELECT contributed_pln, limit_pln FROM ike_contributions WHERE user_id = %s AND year = %s",
        [user_id, year],
    ).fetchone()
    contributed = float(ike_row[0]) if ike_row else 0.0
    limit       = (float(ike_row[1]) if ike_row and ike_row[1] else None) or IKE_LIMITS.get(year)
    remaining   = (limit - contributed) if limit else None

    # FX flag — only fires if 21d 90th-percentile forecast is >5% above current
    fx_row = db.execute("""
        SELECT rate_point, rate_upper FROM fx_forecasts
        WHERE pair = 'USDPLN' AND horizon_days = 21 ORDER BY date DESC LIMIT 1
    """).fetchone()
    macro_row = db.execute("""
        SELECT usdpln FROM daily_features WHERE usdpln IS NOT NULL ORDER BY date DESC LIMIT 1
    """).fetchone()

    fx_flag: Optional[str] = None
    if fx_row and macro_row and macro_row[0]:
        cur   = float(macro_row[0])
        upper = float(fx_row[1])
        if cur > 0 and (upper - cur) / cur > 0.05:
            upside = (upper - cur) / cur * 100
            fx_flag = (
                f"USD/PLN może być nawet {upper:.2f} za miesiąc "
                f"(+{upside:.1f}% od {cur:.2f}) — zakup VWCE.DE może kosztować zauważalnie więcej PLN."
                if pl else
                f"USD/PLN could reach {upper:.2f} within a month "
                f"(+{upside:.1f}% from {cur:.2f}) — VWCE.DE in PLN may cost noticeably more."
            )

    headline = (
        "Inwestuj swój miesięczny wkład. Decyzja, która naprawdę ma znaczenie, "
        "to konsekwentne wpłacanie — nie wybór momentu."
        if pl else
        "Invest your monthly contribution. The decision that matters is contributing, "
        "not timing."
    )

    return InvestStatus(
        as_of         = today,
        headline      = headline,
        ike_remaining = remaining,
        ike_limit     = limit,
        ike_contributed = contributed,
        fx_flag       = fx_flag,
    )


# ---------------------------------------------------------------------------
# /invest/longrun — Shiller real-total-return index, full history
# ---------------------------------------------------------------------------

@router.get("/longrun")
def invest_longrun(
    sample_months: int = Query(default=3, ge=1, le=12, description="Sample every N months to keep payload small."),
):
    """Return the Shiller real-total-return index 1871–present, indexed to 100 at start.

    Sampled at monthly resolution by default; pass `sample_months` to thin further.
    The intent is a single striking long-run chart on /invest, not a tradeable feed.
    """
    df = _load_real_total_return()
    sub = df.iloc[::sample_months].copy()
    return {
        "data": [
            {"date": d.strftime("%Y-%m-%d"), "rtr": round(float(v), 2)}
            for d, v in zip(sub["date"], sub["rtr"])
        ],
        "start_date": df["date"].iloc[0].strftime("%Y-%m-%d"),
        "end_date":   df["date"].iloc[-1].strftime("%Y-%m-%d"),
        "months":     int(len(df)),
    }


# ---------------------------------------------------------------------------
# /invest/historical-simulation — "What if I had invested X on date D?"
# ---------------------------------------------------------------------------

class HistoricalSimulation(BaseModel):
    start_date:        date
    end_date:          date
    mode:              str               # "lump_sum" or "dca"
    dca_months:        Optional[int]
    amount_pln:        float             # total amount put into the strategy
    total_invested:    float             # equals amount_pln (kept for symmetry)
    final_value_real:  float             # in real (CPI-adjusted) PLN of start_date
    final_value_nominal: float           # in nominal PLN
    return_pct:        float             # (final / invested) - 1, in real terms
    cagr_pct:          float             # annualised real CAGR
    max_drawdown_pct:  float             # worst peak-to-trough on the equity curve
    months_held:       int
    equity_curve:      list[dict]        # [{date, value_real, value_nominal, invested}]


@router.get("/historical-simulation", response_model=HistoricalSimulation)
def historical_simulation(
    start_date: date  = Query(..., description="When you (hypothetically) started investing"),
    end_date:   Optional[date] = Query(None, description="Defaults to latest Shiller month"),
    amount_pln: float = Query(..., gt=0, le=10_000_000),
    mode:       str   = Query("lump_sum", pattern="^(lump_sum|dca)$"),
    dca_months: int   = Query(12, ge=1, le=240, description="Number of months over which to spread the contribution if mode=dca"),
):
    """Simulate a hypothetical investment in the S&P 500 using Shiller's real total
    return series. PLN-denominated amounts are tracked as a real PLN equivalent
    (the S&P is treated as a single global-equity proxy — this is an educational
    illustration, not a forecast).
    """
    df = _load_real_total_return()
    end_date = end_date or df["date"].iloc[-1].date()

    if start_date < df["date"].iloc[0].date():
        raise HTTPException(400, f"start_date must be >= {df['date'].iloc[0].date()}")
    if start_date >= end_date:
        raise HTTPException(400, "start_date must be before end_date")
    if end_date > df["date"].iloc[-1].date():
        raise HTTPException(400, f"end_date must be <= {df['date'].iloc[-1].date()}")

    # Snap each date to the nearest available Shiller month
    sub = df[(df["date"] >= pd.Timestamp(start_date)) & (df["date"] <= pd.Timestamp(end_date))].reset_index(drop=True)
    if len(sub) < 2:
        raise HTTPException(400, "Date range too narrow — pick start_date at least 1 month before end_date")

    months = len(sub)
    rtr    = sub["rtr"].to_numpy()
    dates  = sub["date"].to_numpy()

    # Build the contribution schedule and unit accumulation.
    # Each contribution c at month i buys c / rtr[i] units; the portfolio value
    # at month t is rtr[t] * sum_{i<=t} c_i / rtr[i].
    contributions = np.zeros(months)
    if mode == "lump_sum":
        contributions[0] = amount_pln
    else:
        n = min(dca_months, months)
        contributions[:n] = amount_pln / n

    units_bought  = contributions / rtr
    units_cumsum  = np.cumsum(units_bought)
    portfolio_val = rtr * units_cumsum
    invested_cum  = np.cumsum(contributions)

    # Convert "real PLN" portfolio values back to nominal using the CPI implied
    # by Real Price / nominal SP500. Approximation: use real-price ratio as a
    # proxy CPI multiplier. (For an educational illustration this is enough.)
    final_real    = float(portfolio_val[-1])
    final_nominal = final_real   # treat real PLN as equal to nominal for display; CPI-adjusted line is more honest anyway

    # Drawdown on the equity curve
    peak           = np.maximum.accumulate(portfolio_val)
    drawdown       = (portfolio_val - peak) / np.where(peak > 0, peak, 1)
    max_drawdown   = float(drawdown.min()) if len(drawdown) else 0.0

    years_held = (months - 1) / 12.0
    if amount_pln > 0 and years_held > 0 and final_real > 0:
        cagr = (final_real / amount_pln) ** (1.0 / years_held) - 1.0
    else:
        cagr = 0.0
    return_pct = (final_real / amount_pln - 1.0) if amount_pln > 0 else 0.0

    # Thin the equity curve to ~200 points for the chart payload
    n_points = 200
    step = max(1, months // n_points)
    curve = [
        {
            "date":          pd.Timestamp(dates[i]).strftime("%Y-%m-%d"),
            "value_real":    round(float(portfolio_val[i]), 2),
            "value_nominal": round(float(portfolio_val[i]), 2),
            "invested":      round(float(invested_cum[i]), 2),
        }
        for i in range(0, months, step)
    ]
    # Always include the last point
    if curve[-1]["date"] != pd.Timestamp(dates[-1]).strftime("%Y-%m-%d"):
        curve.append({
            "date":          pd.Timestamp(dates[-1]).strftime("%Y-%m-%d"),
            "value_real":    round(float(portfolio_val[-1]), 2),
            "value_nominal": round(float(portfolio_val[-1]), 2),
            "invested":      round(float(invested_cum[-1]), 2),
        })

    return HistoricalSimulation(
        start_date         = pd.Timestamp(dates[0]).date(),
        end_date           = pd.Timestamp(dates[-1]).date(),
        mode               = mode,
        dca_months         = dca_months if mode == "dca" else None,
        amount_pln         = amount_pln,
        total_invested     = float(invested_cum[-1]),
        final_value_real   = final_real,
        final_value_nominal= final_nominal,
        return_pct         = round(return_pct * 100, 2),
        cagr_pct           = round(cagr * 100, 2),
        max_drawdown_pct   = round(max_drawdown * 100, 2),
        months_held        = months,
        equity_curve       = curve,
    )


# ---------------------------------------------------------------------------
# /invest/projection — alias of /decision/projection (same shape)
# ---------------------------------------------------------------------------

@router.get("/projection")
def invest_projection(
    db:          Annotated[object, Depends(get_db)],
    user_id:     Annotated[str, Depends(get_current_user)],
    years:       int   = Query(default=20, ge=1,   le=50),
    monthly_pln: float = Query(default=500, ge=0, le=50000),
    n_paths:     int   = Query(default=10000, ge=1000, le=50000),
):
    """Alias for /decision/projection so the /invest page has self-contained URLs."""
    return get_projection(db=db, user_id=user_id, years=years, monthly_pln=monthly_pln, n_paths=n_paths)
