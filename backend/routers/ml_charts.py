"""
backend/routers/ml_charts.py — Chart-data endpoints for the ML model pages.

All endpoints return precomputed data from DB or pkl artifacts — no heavy
computation at request time. Data is suitable for direct consumption by
Recharts in the frontend.

Routes (all prefixed /api/ml):
  GET /api/ml/summary                    hub-page summary of all 7 models
  GET /api/ml/hmm/history                regime timeline 1871-present
  GET /api/ml/hmm/probabilities          rolling 4-state probabilities (last N years)
  GET /api/ml/hmm/transitions            transition matrix heatmap data
  GET /api/ml/hmm/state-stats            mean return/vol/CAPE per state
  GET /api/ml/hmm/current                current state + probabilities
  GET /api/ml/regime-duration/survival   KM survival curves per state
  GET /api/ml/regime-duration/episodes   episode history Gantt data
  GET /api/ml/regime-duration/current    current episode age + KM context
  GET /api/ml/volatility/forecast        predicted vs actual vol walk-forward
  GET /api/ml/volatility/horizons        21d vs 63d forecast comparison
  GET /api/ml/volatility/features        feature importance bar chart
  GET /api/ml/volatility/vix-scatter     VIX vs forecast scatter by regime
  GET /api/ml/cape/scatter               145Y CAPE vs 10Y return scatter
  GET /api/ml/cape/history               CAPE history 1871-present
  GET /api/ml/cape/current-signal        current q10/q50/q90 return estimates
  GET /api/ml/cape/decile-table          Asness decile table with current marker
  GET /api/ml/cape/feature-plane         real-rate vs CAPE scatter coloured by return
  GET /api/ml/recession/history          recession prob history + USREC bands
  GET /api/ml/recession/features         LightGBM feature importances
  GET /api/ml/recession/yield-curve      yield spread history with recession bands
  GET /api/ml/recession/calibration      calibration curve (reliability diagram)
  GET /api/ml/fx/fan-chart               USD/PLN fan chart history
  GET /api/ml/fx/error-distribution      forecast error histogram
  GET /api/ml/fx/band-width              uncertainty band width over time
  GET /api/ml/fx/features                FX model feature importance
  GET /api/ml/pca/history                diversification index history
  GET /api/ml/pca/correlations           pairwise correlations over time
  GET /api/ml/pca/by-regime              PC1 variance by regime (box plot data)
  GET /api/ml/pca/current-heatmap        current 5x5 correlation matrix
"""

import math
import pickle
from pathlib import Path
from typing import Annotated, Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, Query

from backend.database import get_db

router = APIRouter(prefix="/ml", tags=["ml-charts"])

ROOT      = Path(__file__).parent.parent.parent
SHILLER   = ROOT / "shiller.csv"
MODELS    = ROOT / "models"

REGIME_COLORS = {
    "bull": "#22c55e",
    "consolidation": "#3b82f6",
    "stagflation": "#f97316",
    "bear": "#ef4444",
}

ASNESS_DECILES = [
    {"decile": 1, "cape_max": 9.6,  "median_return": 10.3, "std": 6.0},
    {"decile": 2, "cape_max": 11.6, "median_return": 9.0,  "std": 5.5},
    {"decile": 3, "cape_max": 13.6, "median_return": 8.2,  "std": 5.8},
    {"decile": 4, "cape_max": 15.6, "median_return": 7.5,  "std": 5.5},
    {"decile": 5, "cape_max": 17.3, "median_return": 6.8,  "std": 6.0},
    {"decile": 6, "cape_max": 19.4, "median_return": 6.2,  "std": 5.8},
    {"decile": 7, "cape_max": 21.1, "median_return": 5.6,  "std": 6.2},
    {"decile": 8, "cape_max": 25.1, "median_return": 4.0,  "std": 6.5},
    {"decile": 9, "cape_max": None, "median_return": 0.9,  "std": 6.8},
    {"decile": 10,"cape_max": None, "median_return": 0.5,  "std": 7.2},
]


def _latest_hmm_version(db) -> str:
    row = db.execute(
        "SELECT model_version FROM hmm_predictions ORDER BY predicted_at DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else ""


# ─── HMM ─────────────────────────────────────────────────────────────────────

@router.get("/hmm/history")
def hmm_history(
    db: Annotated[object, Depends(get_db)],
    years: int = Query(default=0, description="0 = full history"),
):
    """Regime timeline — one row per month, coloured by state label."""
    version = _latest_hmm_version(db)
    where_date = ""
    if years > 0:
        where_date = f"AND date >= (CURRENT_DATE - INTERVAL '{years * 12} months')"

    rows = db.execute(f"""
        SELECT date, state_label, prob_bull, prob_bear, prob_consolidation
        FROM hmm_predictions
        WHERE model_version = %s {where_date}
        ORDER BY date
    """, [version]).fetchall()

    # Fetch USREC for recession overlay bands
    usrec_rows = db.execute("""
        SELECT date, value FROM raw_macro
        WHERE series_id = 'USREC'
        ORDER BY date
    """).fetchall()
    usrec = {str(r[0]): int(float(r[1])) for r in usrec_rows if r[1] is not None}

    data = []
    for r in rows:
        d = str(r[0])
        data.append({
            "date": d,
            "state": r[1],
            "color": REGIME_COLORS.get(r[1], "#6b7280"),
            "prob_bull": round(float(r[2] or 0), 3),
            "prob_bear": round(float(r[3] or 0), 3),
            "prob_consolidation": round(float(r[4] or 0), 3),
            "recession": usrec.get(d, 0),
        })
    return {"data": data, "version": version}


@router.get("/hmm/probabilities")
def hmm_probabilities(
    db: Annotated[object, Depends(get_db)],
    years: int = Query(default=10),
):
    """Rolling 4-state probabilities — stacked area chart data."""
    version = _latest_hmm_version(db)
    rows = db.execute(f"""
        SELECT date, prob_bull, prob_bear, prob_consolidation
        FROM hmm_predictions
        WHERE model_version = %s
          AND date >= (CURRENT_DATE - INTERVAL '{years * 12} months')
        ORDER BY date
    """, [version]).fetchall()

    data = []
    for r in rows:
        pb = float(r[1] or 0)
        pbr = float(r[2] or 0)
        pc = float(r[3] or 0)
        ps = max(0.0, round(1.0 - pb - pbr - pc, 3))
        data.append({
            "date": str(r[0]),
            "bull": round(pb, 3),
            "bear": round(pbr, 3),
            "consolidation": round(pc, 3),
            "stagflation": ps,
        })
    return {"data": data}


@router.get("/hmm/transitions")
def hmm_transitions(db: Annotated[object, Depends(get_db)]):
    """Transition matrix heatmap — P(next state | current state)."""
    try:
        with open(MODELS / "hmm_regime.pkl", "rb") as f:
            art = pickle.load(f)
        model = art["model"]
        labels = art["state_labels"]  # {int: "bull"/"bear"/...}

        n = model.n_components
        mat = model.transmat_
        states = [labels[i] for i in range(n)]

        rows = []
        for i in range(n):
            for j in range(n):
                rows.append({
                    "from": states[i],
                    "to": states[j],
                    "probability": round(float(mat[i, j]), 4),
                })
        return {"matrix": rows, "states": states}
    except Exception as e:
        return {"matrix": [], "error": str(e)}


@router.get("/hmm/state-stats")
def hmm_state_stats(db: Annotated[object, Depends(get_db)]):
    """Mean return, volatility and CAPE per HMM state from model parameters."""
    try:
        with open(MODELS / "hmm_regime.pkl", "rb") as f:
            art = pickle.load(f)
        model = art["model"]
        labels = art["state_labels"]
        feat_cols = art["feature_cols"]

        ret_idx  = feat_cols.index("sp500_log_ret")
        vol_idx  = feat_cols.index("vol_12m")
        cape_idx = feat_cols.index("cape")

        stats = []
        for i in range(model.n_components):
            means = model.means_[i]
            # means are in standardised space — need to unscale
            # We return standardised-space direction only (sign + relative magnitude)
            stats.append({
                "state": labels[i],
                "color": REGIME_COLORS.get(labels[i], "#6b7280"),
                "mean_return_raw": round(float(means[ret_idx]), 4),
                "mean_vol_raw": round(float(means[vol_idx]), 4),
                "mean_cape_raw": round(float(means[cape_idx]), 4),
            })

        # Also compute empirical stats from DB predictions
        version = _latest_hmm_version(db)
        df_shiller = pd.read_csv(SHILLER)
        df_shiller["Date"] = pd.to_datetime(df_shiller["Date"])
        df_shiller = df_shiller.rename(columns={"Date": "date", "SP500": "sp500", "PE10": "cape"})
        df_shiller["sp500_ret_ann"] = np.log(df_shiller["sp500"] / df_shiller["sp500"].shift(1)) * 12 * 100
        df_shiller["vol_ann"] = df_shiller["sp500_ret_ann"].rolling(12).std()

        hmm_rows = db.execute("""
            SELECT date, state_label FROM hmm_predictions
            WHERE model_version = %s ORDER BY date
        """, [version]).fetchall()
        df_hmm = pd.DataFrame(hmm_rows, columns=["date", "state"])
        df_hmm["date"] = pd.to_datetime(df_hmm["date"])

        merged = df_hmm.merge(
            df_shiller[["date", "sp500_ret_ann", "vol_ann", "cape"]],
            on="date", how="left"
        )
        empirical = []
        for state, grp in merged.groupby("state"):
            empirical.append({
                "state": state,
                "color": REGIME_COLORS.get(state, "#6b7280"),
                "mean_annual_return_pct": round(float(grp["sp500_ret_ann"].mean()), 1),
                "mean_annual_vol_pct": round(float(grp["vol_ann"].mean()), 1),
                "mean_cape": round(float(grp["cape"].mean()), 1),
                "n_months": len(grp),
            })

        return {"model_params": stats, "empirical": empirical}
    except Exception as e:
        return {"model_params": [], "empirical": [], "error": str(e)}


@router.get("/hmm/current")
def hmm_current(db: Annotated[object, Depends(get_db)]):
    """Current state and all 4 probabilities."""
    version = _latest_hmm_version(db)
    row = db.execute("""
        SELECT date, state_label, prob_bull, prob_bear, prob_consolidation
        FROM hmm_predictions WHERE model_version = %s
        ORDER BY date DESC LIMIT 1
    """, [version]).fetchone()
    if not row:
        return {}
    pb = float(row[2] or 0)
    pbr = float(row[3] or 0)
    pc = float(row[4] or 0)
    ps = max(0.0, round(1.0 - pb - pbr - pc, 3))
    return {
        "date": str(row[0]),
        "state": row[1],
        "probabilities": [
            {"state": "bull",         "prob": round(pb, 3),  "color": REGIME_COLORS["bull"]},
            {"state": "consolidation","prob": round(pc, 3),  "color": REGIME_COLORS["consolidation"]},
            {"state": "stagflation",  "prob": round(ps, 3),  "color": REGIME_COLORS["stagflation"]},
            {"state": "bear",         "prob": round(pbr, 3), "color": REGIME_COLORS["bear"]},
        ],
    }


# ─── REGIME DURATION (KM) ────────────────────────────────────────────────────

@router.get("/regime-duration/survival")
def km_survival(db: Annotated[object, Depends(get_db)]):
    """KM survival curves for all states, with 95% CI bands."""
    rows = db.execute("""
        SELECT regime, duration_months, km_survival, km_survival_lower, km_survival_upper,
               n_at_risk, n_events
        FROM regime_duration_stats
        ORDER BY regime, duration_months
    """).fetchall()

    by_state = {}
    for r in rows:
        s = r[0]
        if s not in by_state:
            by_state[s] = []
        by_state[s].append({
            "t": int(r[1]),
            "survival": round(float(r[2]), 4),
            "lower": round(float(r[3]), 4),
            "upper": round(float(r[4]), 4),
            "n_at_risk": int(r[5]) if r[5] else None,
            "n_events": int(r[6]) if r[6] else None,
        })

    return {
        "curves": [
            {"state": s, "color": REGIME_COLORS.get(s, "#6b7280"), "points": pts}
            for s, pts in by_state.items()
        ]
    }


@router.get("/regime-duration/episodes")
def km_episodes(db: Annotated[object, Depends(get_db)]):
    """Full episode history for Gantt chart display."""
    version = _latest_hmm_version(db)
    rows = db.execute("""
        SELECT date, state_label FROM hmm_predictions
        WHERE model_version = %s ORDER BY date
    """, [version]).fetchall()

    if not rows:
        return {"episodes": []}

    df = pd.DataFrame(rows, columns=["date", "state"])
    df["date"] = pd.to_datetime(df["date"])
    df["episode_id"] = (df["state"] != df["state"].shift()).cumsum()

    episodes = (
        df.groupby("episode_id")
          .agg(state=("state", "first"),
               start=("date", "min"),
               end=("date", "max"),
               duration=("state", "count"))
          .reset_index(drop=True)
    )

    return {
        "episodes": [
            {
                "state": row["state"],
                "color": REGIME_COLORS.get(row["state"], "#6b7280"),
                "start": str(row["start"].date()),
                "end": str(row["end"].date()),
                "duration_months": int(row["duration"]),
            }
            for _, row in episodes.iterrows()
        ]
    }


@router.get("/regime-duration/current")
def km_current(db: Annotated[object, Depends(get_db)]):
    """Current episode duration, KM survival at current age, median/P25/P75."""
    from ml.regime_duration import get_current_regime_status
    status = get_current_regime_status(db)

    # Add median, P25, P75 for current state
    if status.get("current_state"):
        state = status["current_state"]
        km_rows = db.execute("""
            SELECT duration_months, km_survival FROM regime_duration_stats
            WHERE regime = %s ORDER BY duration_months
        """, [state]).fetchall()
        status["km_curve"] = [{"t": r[0], "s": float(r[1])} for r in km_rows]

    return status


# ─── VOLATILITY ───────────────────────────────────────────────────────────────

@router.get("/volatility/forecast")
def vol_forecast(
    db: Annotated[object, Depends(get_db)],
    years: int = Query(default=5),
):
    """Predicted vs actual 21d vol with 80% interval band."""
    rows = db.execute(f"""
        SELECT v.date, v.vol_forecast, v.vol_lower, v.vol_upper,
               f.acwi_vol_21d AS actual_vol
        FROM volatility_forecasts v
        LEFT JOIN daily_features f ON f.date = v.date
        WHERE v.horizon_days = 21
          AND v.date >= (CURRENT_DATE - INTERVAL '{years * 365} days')
        ORDER BY v.date
    """).fetchall()

    return {
        "data": [
            {
                "date": str(r[0]),
                "forecast": round(float(r[1]) * 100, 2) if r[1] else None,
                "lower": round(float(r[2]) * 100, 2) if r[2] else None,
                "upper": round(float(r[3]) * 100, 2) if r[3] else None,
                "actual": round(float(r[4]) * 100, 2) if r[4] else None,
            }
            for r in rows
        ],
        "unit": "annualised %"
    }


@router.get("/volatility/horizons")
def vol_horizons(
    db: Annotated[object, Depends(get_db)],
    years: int = Query(default=3),
):
    """21d vs 63d forecast comparison."""
    rows_21 = db.execute(f"""
        SELECT date, vol_forecast FROM volatility_forecasts
        WHERE horizon_days = 21
          AND date >= (CURRENT_DATE - INTERVAL '{years * 365} days')
        ORDER BY date
    """).fetchall()
    rows_63 = db.execute(f"""
        SELECT date, vol_forecast FROM volatility_forecasts
        WHERE horizon_days = 63
          AND date >= (CURRENT_DATE - INTERVAL '{years * 365} days')
        ORDER BY date
    """).fetchall()

    d21 = {str(r[0]): round(float(r[1]) * 100, 2) for r in rows_21 if r[1]}
    d63 = {str(r[0]): round(float(r[1]) * 100, 2) for r in rows_63 if r[1]}
    dates = sorted(set(d21) | set(d63))

    return {
        "data": [{"date": d, "vol_21d": d21.get(d), "vol_63d": d63.get(d)} for d in dates],
        "unit": "annualised %"
    }


@router.get("/volatility/features")
def vol_features():
    """Feature importance from the RF volatility model (21d horizon)."""
    try:
        pkls = sorted((MODELS).glob("vol_rf_21d_*.pkl"))
        if not pkls:
            return {"features": []}
        with open(pkls[-1], "rb") as f:
            art = pickle.load(f)
        model = art["model"]
        feats = art.get("feature_cols", art.get("feature_names", art.get("features", [])))
        imps  = model.feature_importances_
        pairs = sorted(zip(feats, imps), key=lambda x: -x[1])
        return {
            "features": [{"feature": n, "importance": round(float(v), 4)} for n, v in pairs[:12]]
        }
    except Exception as e:
        return {"features": [], "error": str(e)}


@router.get("/volatility/vix-scatter")
def vol_vix_scatter(
    db: Annotated[object, Depends(get_db)],
    sample: int = Query(default=500),
):
    """VIX vs vol_21d_forecast scatter, coloured by HMM regime."""
    version = _latest_hmm_version(db)
    rows = db.execute("""
        SELECT f.date, f.vix_close, v.vol_forecast, h.state_label
        FROM daily_features f
        JOIN volatility_forecasts v ON v.date = f.date AND v.horizon_days = 21
        LEFT JOIN hmm_predictions h ON h.date = DATE_TRUNC('month', f.date)
                                    AND h.model_version = %s
        WHERE f.vix_close IS NOT NULL AND v.vol_forecast IS NOT NULL
        ORDER BY f.date DESC
        LIMIT %s
    """, [version, sample * 3]).fetchall()

    import random
    random.seed(42)
    sample_rows = random.sample(rows, min(sample, len(rows)))

    return {
        "data": [
            {
                "date": str(r[0]),
                "vix": round(float(r[1]), 2),
                "vol_forecast_pct": round(float(r[2]) * 100, 2),
                "regime": r[3] or "unknown",
                "color": REGIME_COLORS.get(r[3], "#6b7280"),
            }
            for r in sample_rows
        ]
    }


# ─── CAPE ────────────────────────────────────────────────────────────────────

@router.get("/cape/scatter")
def cape_scatter(db: Annotated[object, Depends(get_db)]):
    """145Y CAPE vs 10Y forward real return scatter + quantile regression lines."""
    df = pd.read_csv(SHILLER)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.rename(columns={"Date": "date", "SP500": "sp500", "PE10": "cape"})
    df = df.sort_values("date").reset_index(drop=True)

    HORIZON_M = 120
    df["real_price"] = pd.to_numeric(df.get("Real Price", df.get("Real_Price", np.nan)), errors="coerce")
    df["real_price_fwd"] = df["real_price"].shift(-HORIZON_M)
    df["ret_10y"] = ((df["real_price_fwd"] / df["real_price"]) ** (1 / 10) - 1) * 100
    df["cape"] = pd.to_numeric(df["cape"], errors="coerce")

    training = df.dropna(subset=["cape", "ret_10y"])
    scatter = [
        {"cape": round(float(r["cape"]), 1), "ret_10y": round(float(r["ret_10y"]), 2),
         "year": int(r["date"].year)}
        for _, r in training.iterrows()
    ]

    # Quantile lines from cape_forecasts
    cape_rows = db.execute("""
        SELECT cape, ret_q10, ret_q50, ret_q90
        FROM cape_forecasts
        WHERE cape IS NOT NULL AND ret_q50 IS NOT NULL
        ORDER BY cape
    """).fetchall()
    q_lines = [
        {"cape": round(float(r[0]), 1), "q10": round(float(r[1]) * 100, 2),
         "q50": round(float(r[2]) * 100, 2), "q90": round(float(r[3]) * 100, 2)}
        for r in cape_rows
    ]

    # Current CAPE
    latest_cape = float(df["cape"].dropna().iloc[-1])
    return {"scatter": scatter, "q_lines": q_lines, "current_cape": latest_cape}


@router.get("/cape/history")
def cape_history():
    """CAPE history 1871-present with historical mean/median reference lines."""
    df = pd.read_csv(SHILLER)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.rename(columns={"Date": "date", "PE10": "cape"})
    df["cape"] = pd.to_numeric(df["cape"], errors="coerce")
    df = df.dropna(subset=["cape"]).sort_values("date")

    cape_mean   = round(float(df["cape"].mean()), 1)
    cape_median = round(float(df["cape"].median()), 1)
    current     = round(float(df["cape"].iloc[-1]), 1)

    data = [{"date": str(r["date"].date()), "cape": round(float(r["cape"]), 1)}
            for _, r in df.iterrows()]
    return {
        "data": data,
        "current_cape": current,
        "historical_mean": cape_mean,
        "historical_median": cape_median,
    }


@router.get("/cape/current-signal")
def cape_current_signal(db: Annotated[object, Depends(get_db)]):
    """Current q10/q50/q90 10Y real return estimate at today's CAPE."""
    row = db.execute("""
        SELECT date, cape, ret_q10, ret_q50, ret_q90
        FROM cape_forecasts
        ORDER BY date DESC LIMIT 1
    """).fetchone()
    if not row:
        return {}

    df = pd.read_csv(SHILLER)
    df["PE10"] = pd.to_numeric(df["PE10"], errors="coerce")
    hist_median_ret = None
    # Historical median 10Y real return from all training rows
    df["ret_10y"] = ((df["Real Price"].shift(-120) / df["Real Price"]) ** 0.1 - 1) * 100
    hist_median_ret = round(float(df["ret_10y"].dropna().median()), 2)

    return {
        "date": str(row[0]),
        "cape": float(row[1]),
        "q10": round(float(row[2]) * 100, 2),
        "q50": round(float(row[3]) * 100, 2),
        "q90": round(float(row[4]) * 100, 2),
        "hist_median_ret": hist_median_ret,
        "base_rate": 5.5,  # DMS 2025
    }


@router.get("/cape/decile-table")
def cape_decile_table(db: Annotated[object, Depends(get_db)]):
    """Asness decile table with current CAPE decile highlighted."""
    row = db.execute("SELECT cape FROM cape_forecasts ORDER BY date DESC LIMIT 1").fetchone()
    current_cape = float(row[0]) if row else None

    current_decile = None
    if current_cape is not None:
        for d in ASNESS_DECILES:
            if d["cape_max"] is None or current_cape > d["cape_max"]:
                current_decile = d["decile"]

    table = [
        {**d, "is_current": (d["decile"] == current_decile)}
        for d in ASNESS_DECILES
    ]
    return {"table": table, "current_cape": current_cape, "current_decile": current_decile}


@router.get("/cape/feature-plane")
def cape_feature_plane():
    """Real long-rate vs CAPE scatter, coloured by 10Y return bucket."""
    df = pd.read_csv(SHILLER)
    df["Date"] = pd.to_datetime(df["Date"])
    df["cape"] = pd.to_numeric(df["PE10"], errors="coerce")
    df["cpi"]  = pd.to_numeric(df["Consumer Price Index"], errors="coerce")
    df["long_rate"] = pd.to_numeric(df["Long Interest Rate"], errors="coerce")
    df["real_price"] = pd.to_numeric(df["Real Price"], errors="coerce")
    df["real_long_rate"] = df["long_rate"] - df["cpi"].pct_change(12).fillna(0) * 100
    df["ret_10y"] = ((df["real_price"].shift(-120) / df["real_price"]) ** 0.1 - 1) * 100

    df = df.dropna(subset=["cape", "real_long_rate", "ret_10y"])
    def bucket(r):
        if r < 2: return "low (<2%)"
        if r < 6: return "mid (2-6%)"
        return "high (>6%)"
    df["return_bucket"] = df["ret_10y"].apply(bucket)

    BUCKET_COLORS = {"low (<2%)": "#ef4444", "mid (2-6%)": "#f97316", "high (>6%)": "#22c55e"}

    sample = df.sample(min(600, len(df)), random_state=42)
    return {
        "data": [
            {
                "cape": round(float(r["cape"]), 1),
                "real_long_rate": round(float(r["real_long_rate"]), 2),
                "ret_10y": round(float(r["ret_10y"]), 2),
                "bucket": r["return_bucket"],
                "color": BUCKET_COLORS[r["return_bucket"]],
                "year": int(r["Date"].year),
            }
            for _, r in sample.iterrows()
        ]
    }


# ─── RECESSION ───────────────────────────────────────────────────────────────

@router.get("/recession/history")
def recession_history(db: Annotated[object, Depends(get_db)]):
    """Recession probability history with USREC shading bands."""
    rows = db.execute("""
        SELECT rp.date, rp.recession_prob, rm.value AS usrec
        FROM recession_predictions rp
        LEFT JOIN raw_macro rm ON rm.date = DATE_TRUNC('month', rp.date)
                               AND rm.series_id = 'USREC'
        ORDER BY rp.date
    """).fetchall()

    # Build USREC recession bands (start/end of each recession period)
    data = []
    for r in rows:
        p = r[1]
        prob = None if p is None or (isinstance(p, float) and not math.isfinite(p)) else round(float(p), 3)
        data.append({
            "date": str(r[0]),
            "prob": prob,
            "usrec": int(float(r[2])) if r[2] is not None else 0,
        })

    # Compute recession bands for chart reference areas
    bands = []
    in_rec = False
    band_start = None
    for d in data:
        if d["usrec"] == 1 and not in_rec:
            in_rec = True
            band_start = d["date"]
        elif d["usrec"] == 0 and in_rec:
            in_rec = False
            bands.append({"start": band_start, "end": d["date"]})
    if in_rec:
        bands.append({"start": band_start, "end": data[-1]["date"]})

    return {"data": data, "recession_bands": bands}


@router.get("/recession/features")
def recession_features():
    """LightGBM feature importances from saved pkl."""
    try:
        with open(MODELS / "recession.pkl", "rb") as f:
            art = pickle.load(f)
        imps = art.get("importances", {})
        n_months  = art.get("n_total_months", None)
        n_rec     = art.get("n_recession_months", None)
        train_start = art.get("training_start", None)

        pairs = sorted(imps.items(), key=lambda x: -x[1])
        return {
            "features": [{"feature": k, "importance": int(v)} for k, v in pairs],
            "training_start": train_start,
            "n_total_months": n_months,
            "n_recession_months": n_rec,
        }
    except Exception as e:
        return {"features": [], "error": str(e)}


@router.get("/recession/yield-curve")
def recession_yield_curve(db: Annotated[object, Depends(get_db)]):
    """Yield spread (10Y-3M) history with USREC recession bands."""
    rows = db.execute("""
        SELECT f.date, f.spread_10y_3m, rm.value AS usrec
        FROM daily_features f
        LEFT JOIN raw_macro rm ON rm.date = DATE_TRUNC('month', f.date)
                               AND rm.series_id = 'USREC'
        WHERE f.spread_10y_3m IS NOT NULL
        ORDER BY f.date
    """).fetchall()

    data = []
    for r in rows:
        v = r[1]
        spread = None if v is None or (isinstance(v, float) and not math.isfinite(v)) else round(float(v), 3)
        data.append({
            "date": str(r[0]),
            "spread": spread,
            "usrec": int(float(r[2])) if r[2] is not None else 0,
        })

    bands = []
    in_rec = False
    band_start = None
    for d in data:
        if d["usrec"] == 1 and not in_rec:
            in_rec = True
            band_start = d["date"]
        elif d["usrec"] == 0 and in_rec:
            in_rec = False
            bands.append({"start": band_start, "end": d["date"]})
    if in_rec:
        bands.append({"start": band_start, "end": data[-1]["date"]})

    return {"data": data, "recession_bands": bands}


@router.get("/recession/calibration")
def recession_calibration(db: Annotated[object, Depends(get_db)]):
    """Reliability diagram: binned predicted prob vs actual recession frequency."""
    rows = db.execute("""
        SELECT rp.recession_prob, rm.value AS usrec
        FROM recession_predictions rp
        LEFT JOIN raw_macro rm ON rm.date = DATE_TRUNC('month', rp.date)
                               AND rm.series_id = 'USREC'
        WHERE rp.recession_prob IS NOT NULL
    """).fetchall()

    probs  = np.array([float(r[0]) for r in rows])
    actual = np.array([float(r[1]) if r[1] is not None else 0.0 for r in rows])

    bins = np.linspace(0, 1, 11)
    points = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        mask = (probs >= lo) & (probs < hi)
        if mask.sum() >= 5:
            points.append({
                "bin_center": round(float((lo + hi) / 2), 2),
                "mean_predicted": round(float(probs[mask].mean()), 3),
                "actual_frequency": round(float(actual[mask].mean()), 3),
                "n": int(mask.sum()),
            })

    return {"calibration": points, "perfect_line": [{"x": 0, "y": 0}, {"x": 1, "y": 1}]}


# ─── FX ──────────────────────────────────────────────────────────────────────

@router.get("/fx/fan-chart")
def fx_fan_chart(
    db: Annotated[object, Depends(get_db)],
    years: int = Query(default=3),
):
    """USD/PLN actual rate + q10/q50/q90 forecast fan."""
    rows_actual = db.execute(f"""
        SELECT date, usdpln FROM daily_features
        WHERE usdpln IS NOT NULL
          AND date >= (CURRENT_DATE - INTERVAL '{years * 365} days')
        ORDER BY date
    """).fetchall()

    rows_fx = db.execute(f"""
        SELECT date, rate_point, rate_lower, rate_upper
        FROM fx_forecasts
        WHERE pair = 'USDPLN' AND horizon_days = 21
          AND date >= (CURRENT_DATE - INTERVAL '{years * 365} days')
        ORDER BY date
    """).fetchall()

    actual = {str(r[0]): round(float(r[1]), 4) for r in rows_actual}
    forecasts = {str(r[0]): {
        "q50": round(float(r[1]), 4) if r[1] else None,
        "q10": round(float(r[2]), 4) if r[2] else None,
        "q90": round(float(r[3]), 4) if r[3] else None,
    } for r in rows_fx}

    dates = sorted(set(actual) | set(forecasts))
    data = []
    for d in dates:
        row = {"date": d, "actual": actual.get(d)}
        row.update(forecasts.get(d, {}))
        data.append(row)

    return {"data": data}


@router.get("/fx/error-distribution")
def fx_error_distribution(db: Annotated[object, Depends(get_db)]):
    """Forecast error (actual - q50) distribution at 21d and 63d horizons."""
    result = {}
    for horizon in [21, 63]:
        rows = db.execute(f"""
            SELECT f.date,
                   LEAD(df.usdpln, {horizon}) OVER (ORDER BY df.date) - fx.rate_point AS error
            FROM fx_forecasts fx
            JOIN daily_features df ON df.date = fx.date
            LEFT JOIN daily_features f ON f.date = fx.date
            WHERE fx.pair = 'USDPLN' AND fx.horizon_days = {horizon}
              AND df.usdpln IS NOT NULL AND fx.rate_point IS NOT NULL
            ORDER BY fx.date
        """).fetchall()
        errors = [float(r[1]) for r in rows if r[1] is not None]
        if not errors:
            result[f"h{horizon}"] = []
            continue

        err_arr = np.array(errors)
        hist, edges = np.histogram(err_arr, bins=30)
        result[f"h{horizon}"] = [
            {"bin_center": round(float((edges[i] + edges[i+1]) / 2), 4),
             "count": int(hist[i])}
            for i in range(len(hist))
        ]
        result[f"h{horizon}_stats"] = {
            "mean": round(float(err_arr.mean()), 4),
            "std": round(float(err_arr.std()), 4),
            "n": len(errors),
        }
    return result


@router.get("/fx/band-width")
def fx_band_width(
    db: Annotated[object, Depends(get_db)],
    years: int = Query(default=5),
):
    """Uncertainty band width (q90-q10) over time, both horizons."""
    rows = db.execute(f"""
        SELECT date, horizon_days,
               rate_upper - rate_lower AS band_width
        FROM fx_forecasts
        WHERE pair = 'USDPLN'
          AND rate_upper IS NOT NULL AND rate_lower IS NOT NULL
          AND date >= (CURRENT_DATE - INTERVAL '{years * 365} days')
        ORDER BY date, horizon_days
    """).fetchall()

    by_date = {}
    for r in rows:
        d = str(r[0])
        if d not in by_date:
            by_date[d] = {"date": d}
        by_date[d][f"band_width_{r[1]}d"] = round(float(r[2]), 4) if r[2] else None

    return {"data": sorted(by_date.values(), key=lambda x: x["date"])}


@router.get("/fx/features")
def fx_features():
    """Feature importances from the FX q50 21d model."""
    try:
        pkls = sorted(MODELS.glob("fx_lgbm_USDPLN_21d_q50_*.pkl"))
        if not pkls:
            pkls = sorted(MODELS.glob("fx_lgbm_USDPLN_21d_*.pkl"))
        if not pkls:
            return {"features": []}
        with open(pkls[-1], "rb") as f:
            art = pickle.load(f)
        model = art.get("model")
        feats = art.get("feature_cols", art.get("features", art.get("feature_names", [])))
        if model is None:
            return {"features": []}
        imps = model.feature_importances_
        pairs = sorted(zip(feats, imps), key=lambda x: -x[1])
        return {"features": [{"feature": n, "importance": int(v)} for n, v in pairs]}
    except Exception as e:
        return {"features": [], "error": str(e)}


# ─── PCA DIVERSIFICATION ─────────────────────────────────────────────────────

@router.get("/pca/history")
def pca_history(
    db: Annotated[object, Depends(get_db)],
    years: int = Query(default=0),
):
    """Diversification index history with regime background colour."""
    version = _latest_hmm_version(db)
    where_date = ""
    if years > 0:
        where_date = f"AND d.computed_date >= (CURRENT_DATE - INTERVAL '{years * 365} days')"

    rows = db.execute(f"""
        SELECT d.computed_date, d.div_index, d.pc1_explained, d.regime
        FROM diversification_index d
        WHERE 1=1 {where_date}
        ORDER BY d.computed_date
    """).fetchall()

    return {
        "data": [
            {
                "date": str(r[0]),
                "div_index": round(float(r[1]), 4) if r[1] else None,
                "pc1_explained": round(float(r[2]), 4) if r[2] else None,
                "regime": r[3],
                "color": REGIME_COLORS.get(r[3], "#6b7280"),
            }
            for r in rows
        ]
    }


@router.get("/pca/correlations")
def pca_correlations(
    db: Annotated[object, Depends(get_db)],
    years: int = Query(default=5),
):
    """Pairwise rolling correlations over time — ACWI/Gold, ACWI/Bonds, ACWI/USD."""
    rows = db.execute(f"""
        SELECT computed_date, asset_pair, correlation
        FROM correlation_stats
        WHERE computed_date >= (CURRENT_DATE - INTERVAL '{years * 365} days')
        ORDER BY computed_date, asset_pair
    """).fetchall()

    by_date = {}
    for r in rows:
        d = str(r[0])
        if d not in by_date:
            by_date[d] = {"date": d}
        by_date[d][r[1]] = round(float(r[2]), 4) if r[2] else None

    return {"data": sorted(by_date.values(), key=lambda x: x["date"])}


@router.get("/pca/by-regime")
def pca_by_regime(db: Annotated[object, Depends(get_db)]):
    """PC1 variance explained distribution per regime — box-plot data."""
    rows = db.execute("""
        SELECT regime, pc1_explained
        FROM diversification_index
        WHERE pc1_explained IS NOT NULL
        ORDER BY regime
    """).fetchall()

    by_regime = {}
    for r in rows:
        s = r[0] or "unknown"
        if s not in by_regime:
            by_regime[s] = []
        by_regime[s].append(float(r[1]))

    result = []
    for regime, vals in by_regime.items():
        arr = np.array(vals)
        result.append({
            "regime": regime,
            "color": REGIME_COLORS.get(regime, "#6b7280"),
            "min": round(float(arr.min()), 4),
            "q25": round(float(np.percentile(arr, 25)), 4),
            "median": round(float(np.median(arr)), 4),
            "q75": round(float(np.percentile(arr, 75)), 4),
            "max": round(float(arr.max()), 4),
            "mean": round(float(arr.mean()), 4),
            "n": len(vals),
        })
    return {"data": result}


@router.get("/pca/current-heatmap")
def pca_current_heatmap(db: Annotated[object, Depends(get_db)]):
    """Current 5-asset pairwise correlation matrix (most recent window)."""
    rows = db.execute("""
        SELECT asset_pair, correlation
        FROM correlation_stats
        WHERE computed_date = (SELECT MAX(computed_date) FROM correlation_stats)
    """).fetchall()

    pairs = {r[0]: round(float(r[1]), 3) for r in rows if r[1] is not None}
    assets = ["ACWI", "Gold", "Bonds", "USD", "VIX"]

    matrix = []
    for a in assets:
        for b in assets:
            key1 = f"{a}/{b}"
            key2 = f"{b}/{a}"
            val = 1.0 if a == b else pairs.get(key1, pairs.get(key2))
            matrix.append({"row": a, "col": b, "value": val})

    return {"matrix": matrix, "assets": assets, "pairs": pairs}


# ─── SUMMARY (hub page) ──────────────────────────────────────────────────────

@router.get("/summary")
def ml_summary(db: Annotated[object, Depends(get_db)]):
    """Hub-page summary: current signal from each of the 7 models."""
    result = {}

    # 1. HMM
    version = _latest_hmm_version(db)
    row = db.execute("""
        SELECT date, state_label, prob_bull, prob_bear, prob_consolidation
        FROM hmm_predictions WHERE model_version = %s ORDER BY date DESC LIMIT 1
    """, [version]).fetchone()
    if row:
        pb = float(row[2] or 0); pbr = float(row[3] or 0); pc = float(row[4] or 0)
        ps = max(0.0, 1.0 - pb - pbr - pc)
        probs = {"bull": pb, "bear": pbr, "consolidation": pc, "stagflation": ps}
        result["hmm"] = {
            "date": str(row[0]), "state": row[1], "color": REGIME_COLORS.get(row[1], "#6b7280"),
            "top_prob": round(max(probs.values()), 2),
        }

    # 2. Regime duration
    from ml.regime_duration import get_current_regime_status
    dur = get_current_regime_status(db)
    result["regime_duration"] = {
        "current_state": dur.get("current_state"),
        "current_duration_months": dur.get("current_duration_months"),
        "km_survival": dur.get("km_survival_at_current"),
        "median_duration": dur.get("median_duration"),
    }

    # 3. Volatility
    vol_row = db.execute("""
        SELECT date, vol_forecast FROM volatility_forecasts
        WHERE horizon_days = 21 ORDER BY date DESC LIMIT 1
    """).fetchone()
    result["volatility"] = {
        "date": str(vol_row[0]) if vol_row else None,
        "vol_21d_pct": round(float(vol_row[1]) * 100, 1) if vol_row and vol_row[1] else None,
        "signal": "high" if vol_row and vol_row[1] and float(vol_row[1]) > 0.25 else "normal",
    }

    # 4. FX
    fx_row = db.execute("""
        SELECT date, rate_point, rate_lower, rate_upper
        FROM fx_forecasts WHERE pair = 'USDPLN' AND horizon_days = 21
        ORDER BY date DESC LIMIT 1
    """).fetchone()
    result["fx"] = {
        "date": str(fx_row[0]) if fx_row else None,
        "usdpln_q50": round(float(fx_row[1]), 4) if fx_row and fx_row[1] else None,
        "usdpln_q10": round(float(fx_row[2]), 4) if fx_row and fx_row[2] else None,
        "usdpln_q90": round(float(fx_row[3]), 4) if fx_row and fx_row[3] else None,
    }

    # 5. Recession
    rec_row = db.execute("""
        SELECT date, recession_prob FROM recession_predictions ORDER BY date DESC LIMIT 1
    """).fetchone()
    result["recession"] = {
        "date": str(rec_row[0]) if rec_row else None,
        "prob": round(float(rec_row[1]), 3) if rec_row and rec_row[1] else None,
        "signal": "elevated" if rec_row and rec_row[1] and float(rec_row[1]) > 0.3 else "low",
    }

    # 6. CAPE
    cape_row = db.execute("""
        SELECT date, cape, ret_q10, ret_q50, ret_q90
        FROM cape_forecasts ORDER BY date DESC LIMIT 1
    """).fetchone()
    result["cape"] = {
        "date": str(cape_row[0]) if cape_row else None,
        "cape": round(float(cape_row[1]), 1) if cape_row and cape_row[1] else None,
        "ret_q50_pct": round(float(cape_row[3]) * 100, 1) if cape_row and cape_row[3] else None,
    }

    # 7. PCA diversification
    div_row = db.execute("""
        SELECT computed_date, div_index FROM diversification_index
        ORDER BY computed_date DESC LIMIT 1
    """).fetchone()
    result["pca"] = {
        "date": str(div_row[0]) if div_row else None,
        "div_index": round(float(div_row[1]), 3) if div_row and div_row[1] else None,
        "signal": "low" if div_row and div_row[1] and float(div_row[1]) < 0.40 else "normal",
    }

    return result
