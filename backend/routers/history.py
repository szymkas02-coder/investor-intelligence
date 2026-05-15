"""
backend/routers/history.py — Historical data for charts

GET /history/prices?ticker=VWCE.DE&days=365
GET /history/regime?days=730
GET /history/macro?series=vix,spread_10y_3m,cpi_us_yoy&days=730
GET /history/fx?days=365
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from typing import Annotated, Any
import json, math

from backend.database import get_db

router = APIRouter(prefix="/history", tags=["history"])


def _clean(v):
    """Replace NaN/Inf with None so JSON serialisation doesn't crash."""
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def _json(data) -> Response:
    """
    Bypass FastAPI/Pydantic serialisation and return raw JSON directly.

    WHY: FastAPI validates every field in the response dict through Pydantic,
    which adds ~2 seconds of overhead for large payloads (250KB+). For
    read-only chart data we don't need validation on the way out — we built
    the dict ourselves. Returning a pre-serialised Response drops latency
    from ~2000ms to ~15ms for the history endpoints.
    """
    return Response(content=json.dumps(data, default=str), media_type="application/json")

# Actual data start dates — requests beyond these return all available data
DATA_START = {
    "prices":  "2005-01-01",
    "regime":  "2010-01-01",
    "macro":   "2010-01-01",
    "fx":      "2005-01-01",
    "cape":    "1871-01-01",
}
MAX_DAYS = 9999  # sentinel for "all"

VALID_MACRO_SERIES = {
    "vix_close", "spread_10y_3m", "spread_10y_2y",
    "cpi_us_yoy", "cpi_core_us_yoy", "cpi_ea_yoy", "cpi_pl_yoy",
    "fed_funds_rate", "ecb_rate", "nbp_rate",
    "usdpln", "eurpln",
    "acwi_ret_21d", "acwi_ret_63d", "acwi_vol_21d",
    "hy_spread", "sp500_earnings_yield", "sp500_pe_ratio",
    "wig20_ret_1d", "gold_ret_1d", "gold_ret_21d",
    "unemployment_us", "gdp_us_yoy",
    "rate_differential", "cpi_differential",
    "yield_10y", "yield_2y", "yield_3m",
    "acwi_vol_21d", "acwi_vol_63d",
}


@router.get("/prices")
def get_price_history(
    db:     Annotated[Any, Depends(get_db)],
    ticker: str = Query(default="VWCE.DE"),
    days:   int = Query(default=365, ge=30, le=MAX_DAYS),
):
    """OHLC + adj_close for a ticker, converted to PLN where applicable."""
    EUR_TICKERS = {'VWCE.DE', 'IUSQ.DE', 'SPPW.DE', 'ZPRV.DE', 'ZPRX.DE', 'SXR8.DE'}
    GBP_TICKERS = {'IWDA.L', 'CSPX.L', 'CNDX.L', 'IDTL.L', 'IGLN.L',
                   'EIMI.L', 'VUSA.L', 'VAGF.L', 'AGGH.L', 'IBTM.L'}
    # ISAC.L is iShares MSCI ACWI, USD-denominated on LSE — falls through to USD

    rows = db.execute(f"""
        SELECT r.date, r.adj_close, f.eurpln, f.usdpln
        FROM raw_prices r
        LEFT JOIN daily_features f ON r.date = f.date
        WHERE r.ticker = '{ticker}'
          AND r.source = 'yfinance'
          AND r.date >= (CURRENT_DATE - INTERVAL '{days} days')
        ORDER BY r.date ASC
    """).fetchall()

    result = []
    for date, price_native, eurpln, usdpln in rows:
        if price_native is None:
            continue
        eurpln = eurpln or 4.25
        usdpln = usdpln or 3.85
        if ticker in EUR_TICKERS:
            price_pln = price_native * eurpln
        elif ticker in GBP_TICKERS:
            price_pln = price_native * eurpln * 1.17
        else:
            price_pln = price_native * usdpln
        result.append({
            "date":         str(date),
            "price_native": round(price_native, 4),
            "price_pln":    round(price_pln, 2),
        })
    currency = "EUR" if ticker in EUR_TICKERS else "GBP" if ticker in GBP_TICKERS else "USD"
    return _json({"ticker": ticker, "currency": currency, "rows": result})


@router.get("/regime")
def get_regime_history(
    db:   Annotated[Any, Depends(get_db)],
    days: int = Query(default=730, ge=30, le=MAX_DAYS),
):
    rows = db.execute(f"""
        SELECT date, state_label, prob_bull, prob_bear, prob_consolidation
        FROM hmm_predictions
        WHERE date >= (CURRENT_DATE - INTERVAL '{days} days')
        ORDER BY date ASC
    """).fetchall()
    from backend.hmm_utils import resolve_hmm_probs
    result = []
    for r in rows:
        state, p_bull, p_bear, p_cons, p_stag = resolve_hmm_probs(r[1], r[2], r[3], r[4])
        result.append({
            "date":               str(r[0]),
            "regime":             state,
            "prob_bull":          p_bull,
            "prob_bear":          p_bear,
            "prob_consolidation": p_cons,
            "prob_stagflation":   p_stag,
        })
    return _json({"rows": result})


@router.get("/macro")
def get_macro_history(
    db:     Annotated[Any, Depends(get_db)],
    series: str = Query(default="vix_close,spread_10y_3m,cpi_us_yoy,fed_funds_rate"),
    days:   int = Query(default=730, ge=30, le=MAX_DAYS),
):
    requested = [s.strip() for s in series.split(",")]
    cols = [c for c in requested if c in VALID_MACRO_SERIES]
    if not cols:
        return _json({"rows": [], "series": []})

    col_sql = ", ".join(cols)
    rows = db.execute(f"""
        SELECT date, {col_sql}
        FROM daily_features
        WHERE date >= (CURRENT_DATE - INTERVAL '{days} days')
        ORDER BY date ASC
    """).fetchall()
    return _json({
        "series": cols,
        "rows": [
            {"date": str(r[0]), **{cols[i]: _clean(r[i+1]) for i in range(len(cols))}}
            for r in rows
        ],
    })


@router.get("/cape")
def get_cape_history(
    db:   Annotated[Any, Depends(get_db)],
    days: int = Query(default=730, ge=30, le=50000),
):
    rows = db.execute(f"""
        SELECT date, cape, ret_q50
        FROM cape_forecasts
        WHERE date >= (CURRENT_DATE - INTERVAL '{days} days')
        ORDER BY date ASC
    """).fetchall()
    return _json({"rows": [
        {"date": str(r[0]),
         "cape": round(r[1], 2) if r[1] else None,
         "implied_return_q50": round(r[2] * 100, 2) if r[2] else None}
        for r in rows
    ]})


@router.get("/fx")
def get_fx_history(
    db:   Annotated[Any, Depends(get_db)],
    days: int = Query(default=365, ge=30, le=MAX_DAYS),
):
    rows = db.execute(f"""
        SELECT date, usdpln, eurpln
        FROM daily_features
        WHERE (usdpln IS NOT NULL OR eurpln IS NOT NULL)
          AND date >= (CURRENT_DATE - INTERVAL '{days} days')
        ORDER BY date ASC
    """).fetchall()
    return _json({"rows": [
        {"date": str(r[0]), "usdpln": r[1], "eurpln": r[2]}
        for r in rows
    ]})
