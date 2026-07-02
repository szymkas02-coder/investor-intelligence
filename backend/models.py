"""
backend/models.py — Pydantic request/response schemas

All API responses are typed here. Using Pydantic models (not bare dicts)
means FastAPI auto-generates OpenAPI docs and validates response shapes
at runtime — if a DB query returns unexpected nulls the 422 error is
caught before it silently corrupts the frontend.
"""

from __future__ import annotations
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class RegimeSignal(BaseModel):
    state:              str       # bull | bear | consolidation | stagflation (from HMM)
    prob_bull:          float
    prob_bear:          float
    prob_consolidation: float
    prob_stagflation:   float     # 4th HMM state: high-vol stress (high CAPE, neg returns)
    model_version:      str


class RegimeDurationSignal(BaseModel):
    current_state:           Optional[str]
    current_duration_months: Optional[int]
    km_survival_at_current:  Optional[float]
    km_survival_lower:       Optional[float]
    km_survival_upper:       Optional[float]
    median_duration:         Optional[int]
    p25_duration:            Optional[int]
    p75_duration:            Optional[int]


class CorrelationSnapshot(BaseModel):
    computed_date:          Optional[str]
    regime:                 Optional[str]
    diversification_index:  Optional[float]
    pc1_explained:          Optional[float]
    top_correlations:       list[dict]


class VolatilitySignal(BaseModel):
    horizon_days:  int
    vol_forecast:  float
    vol_lower:     float
    vol_upper:     float
    model_version: str


class FXSignal(BaseModel):
    pair:          str
    horizon_days:  int
    rate_point:    float
    rate_lower:    float
    rate_upper:    float
    model_version: str


class MacroSnapshot(BaseModel):
    vix_close:         Optional[float]
    spread_10y_3m:     Optional[float]
    spread_10y_2y:     Optional[float]
    yield_curve_inverted: Optional[bool]
    cpi_us_yoy:        Optional[float]
    cpi_core_us_yoy:   Optional[float]
    cpi_ea_yoy:        Optional[float]
    cpi_pl_yoy:        Optional[float]
    fed_funds_rate:    Optional[float]
    ecb_rate:          Optional[float]
    nbp_rate:          Optional[float]
    usdpln:            Optional[float]
    eurpln:            Optional[float]
    wig20_ret_1d:      Optional[float]
    acwi_ret_21d:      Optional[float]
    acwi_ret_63d:      Optional[float]
    hy_spread:         Optional[float]
    sp500_earnings_yield: Optional[float]


class DashboardResponse(BaseModel):
    as_of:            date
    regime:           RegimeSignal
    regime_duration:  Optional[RegimeDurationSignal]
    correlation:      Optional[CorrelationSnapshot]
    volatility:       list[VolatilitySignal]
    fx:               list[FXSignal]
    macro:            MacroSnapshot


# ---------------------------------------------------------------------------
# Regime history
# ---------------------------------------------------------------------------

class RegimeHistoryRow(BaseModel):
    date:               date
    state:              str       # bull | bear | consolidation | stagflation
    prob_bull:          float
    prob_bear:          float
    prob_consolidation: float
    prob_stagflation:   float


class RegimeHistoryResponse(BaseModel):
    model_version: str
    rows:          list[RegimeHistoryRow]


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------

class Position(BaseModel):
    ticker:         str
    shares:         float
    avg_cost_pln:   float
    account_type:   str
    opened_at:      date
    current_price:  Optional[float] = None
    value_pln:      Optional[float] = None
    gain_pct:       Optional[float] = None


class AccountSummary(BaseModel):
    """Per-account-type yearly contribution summary."""
    account_type:   str                # IKE | IKZE | regular
    year:           int
    contributed:    float              # PLN contributed this year via buy/deposit
    limit:          Optional[float]    # None for regular accounts (no limit)
    remaining:      Optional[float]    # None for regular accounts


class PortfolioResponse(BaseModel):
    user_id:          str
    positions:        list[Position]
    total_value_pln:  Optional[float]
    # Legacy IKE fields kept for backwards-compat with existing UI
    ike_contributed:  Optional[float]
    ike_limit:        Optional[float]
    ike_remaining:    Optional[float]
    # New unified per-account summary (IKE + IKZE + regular)
    accounts:         list[AccountSummary] = []


class TransactionCreate(BaseModel):
    ticker:       Optional[str] = None
    date:         date
    type:         str = Field(..., pattern="^(buy|sell|dividend|deposit)$")
    shares:       Optional[float] = Field(default=None, gt=0)
    price_pln:    Optional[float] = Field(default=None, gt=0)
    amount_pln:   Optional[float] = Field(default=None, gt=0)  # for deposit type
    usdpln_rate:  Optional[float] = None
    account_type: str = Field(default="IKE", pattern="^(IKE|IKZE|regular)$")
    notes:        Optional[str] = None


class TransactionResponse(BaseModel):
    transaction_id: str
    message:        str


class TransactionRow(BaseModel):
    transaction_id: str
    ticker:         Optional[str]
    date:           date
    type:           str
    shares:         Optional[float]
    price_pln:      Optional[float]
    account_type:   str
    notes:          Optional[str]
    created_at:     Optional[datetime]


class TransactionsResponse(BaseModel):
    transactions: list[TransactionRow]


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class PipelineRunResponse(BaseModel):
    status:     str
    started_at: datetime
    message:    str
    # Populated only for synchronous runs (?wait=true): per-step status summary.
    results:    Optional[dict] = None
