"""
ml/volatility.py — Random Forest realized volatility forecaster

Forecasts annualized realized volatility for VWCE.DE (ACWI proxy) at two
horizons: 21 days (~1 month) and 63 days (~1 quarter).

Design decisions:
- Target: forward realized vol, not implied vol (no VIX-like data for VWCE).
  Defined as annualized std of daily log returns over the next N days.
  This is what the investor actually experiences, not a market expectation.

- HAR-RV features: the Heterogeneous Autoregressive Realized Variance model
  (Corsi 2009) is the academic benchmark for vol forecasting. It uses lagged
  realized vol at three frequencies (daily, weekly, monthly) as features.
  These capture the well-documented long-memory property of volatility — past
  vol predicts future vol better than any macro variable at short horizons.
  Random Forest wraps HAR-RV: it keeps the three lag features but can exploit
  non-linear interactions with macro/regime context that linear HAR cannot.

- Two separate models: one per horizon. Horizon 21d and 63d have different
  dynamics — the 63d model up-weights the monthly lag more; training them
  separately lets the forest discover the right weighting automatically.

- Confidence interval via quantile forests: sklearn's RandomForestRegressor
  does not natively support quantile output, but we can compute the 10th/90th
  percentile of leaf-node predictions across all trees. This gives an honest
  interval rather than a parametric assumption.

- Walk-forward CV: same principle as regime.py — no random splits on time
  series data.

- Output: writes to volatility_forecasts (date, model_version, ticker,
  horizon_days, vol_forecast, vol_lower, vol_upper).
"""

import sys
import pickle
import warnings
from pathlib import Path
from datetime import date, datetime

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import mean_squared_error, mean_absolute_error

sys.path.insert(0, str(Path(__file__).parent.parent))
from db.init_db import get_connection

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TICKER       = "VWCE.DE"
HORIZONS     = [21, 63]
MODEL_DIR    = Path(__file__).parent.parent / "models"
N_SPLITS     = 5
MIN_ROWS     = 500

# HAR-RV lags (trading days)
LAG_1D  = 1
LAG_5D  = 5
LAG_21D = 21

# Macro features that add context beyond pure HAR-RV lags
MACRO_FEATURES = [
    "vix_close",          # fear index — most correlated with near-term vol
    "vix_change_5d",      # VIX momentum
    "spread_10y_3m",      # yield curve: inversion -> vol regime shift
    "acwi_ret_5d",        # recent return: sharp drops -> vol clustering
    "acwi_ret_21d",
    "usdpln_vol_21d",     # PLN vol: local risk premium
    "cpi_us_yoy",         # macro regime context
    "fed_funds_rate",
]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _build_features(conn, horizon: int) -> pd.DataFrame:
    """
    Build feature matrix and target for a given forecast horizon.

    HAR-RV features: realized vol lagged 1d, 5d (weekly avg), 21d (monthly avg).
    Target: forward realized vol = annualized std of log returns over next
            `horizon` trading days.

    WHY annualized std: Vol is always quoted annualized (multiply daily std by
    sqrt(252)) so the model output is interpretable in the same units as VIX
    and options implied vol, which range 10-80%.
    """
    df = conn.execute(f"""
        SELECT
            date,
            -- HAR-RV features: lagged realized vol at 3 frequencies
            -- acwi_vol_21d is already computed in daily_features as ann. vol
            -- We reconstruct 1d and 5d rolling vols via the raw returns
            acwi_vol_21d                                    AS vol_21d,
            -- 5d realized vol: approximate from acwi_vol_21d scaled by sqrt(5/21)
            -- WHY: we don't store acwi_vol_5d in schema; this is a reasonable
            -- proxy. Could add acwi_vol_5d to features.py in a future pass.
            acwi_vol_21d * SQRT(5.0/21.0)                  AS vol_5d_approx,
            ABS(acwi_ret_1d) * SQRT(252.0)                 AS vol_1d_proxy,
            acwi_vol_63d                                    AS vol_63d,
            {', '.join(MACRO_FEATURES)}
        FROM daily_features
        WHERE acwi_vol_21d IS NOT NULL
          AND acwi_ret_1d  IS NOT NULL
        ORDER BY date
    """).df()

    df["date"] = pd.to_datetime(df["date"])

    # -----------------------------------------------------------------------
    # Forward realized vol target
    # Computed as: std of daily log returns over next `horizon` days * sqrt(252)
    # We approximate this from acwi_vol_21d shifted forward by horizon days.
    # WHY shift: at date T, the model must predict vol from T+1 to T+horizon,
    # using only information available at T. Shifting the vol column forward
    # by `horizon` rows aligns the target with the correct prediction window.
    # This is a simplification — ideal would be to compute realized vol from
    # raw price series, but acwi_vol_21d is already stored and avoids re-joining
    # the raw prices table.
    # -----------------------------------------------------------------------
    if horizon == 21:
        df["target"] = df["vol_21d"].shift(-horizon)
    else:
        df["target"] = df["vol_63d"].shift(-horizon)

    df = df.dropna(subset=["target"] + MACRO_FEATURES).copy()
    return df


FEATURE_COLS = [
    "vol_21d", "vol_5d_approx", "vol_1d_proxy", "vol_63d",
] + MACRO_FEATURES


# ---------------------------------------------------------------------------
# Quantile prediction from forest leaf nodes
# ---------------------------------------------------------------------------

def _forest_quantiles(model: RandomForestRegressor,
                      X: pd.DataFrame,
                      quantiles=(0.10, 0.90)) -> tuple[np.ndarray, np.ndarray]:
    """
    Extract per-sample quantile predictions from a fitted RandomForest.

    Each tree predicts a leaf value; the distribution of leaf values across
    all trees gives a non-parametric predictive interval. This is the standard
    approach for RF quantile estimation when quantile RF is not available.
    """
    leaf_preds = np.array([tree.predict(X) for tree in model.estimators_])
    # leaf_preds shape: (n_trees, n_samples)
    q_lo = np.percentile(leaf_preds, quantiles[0] * 100, axis=0)
    q_hi = np.percentile(leaf_preds, quantiles[1] * 100, axis=0)
    return q_lo, q_hi


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train(horizon: int) -> dict:
    """
    Train Random Forest vol forecaster for a single horizon (21 or 63 days).
    Returns metrics dict and saves pkl to models/.
    """
    conn = get_connection()
    df   = _build_features(conn, horizon)

    if len(df) < MIN_ROWS:
        raise ValueError(f"Only {len(df)} rows for horizon={horizon}d — need {MIN_ROWS}+")

    print(f"  Horizon {horizon}d: {len(df)} rows, "
          f"target vol mean={df['target'].mean():.3f}, "
          f"std={df['target'].std():.3f}")

    X = df[FEATURE_COLS].values
    y = df["target"].values

    # ------------------------------------------------------------------
    # Walk-forward CV
    # ------------------------------------------------------------------
    tscv   = TimeSeriesSplit(n_splits=N_SPLITS)
    rmses, maes = [], []

    for fold, (tr_idx, val_idx) in enumerate(tscv.split(X), 1):
        rf = RandomForestRegressor(
            n_estimators=300,
            max_depth=8,
            min_samples_leaf=10,
            max_features=0.6,
            random_state=42,
            n_jobs=-1,
        )
        rf.fit(X[tr_idx], y[tr_idx])
        preds    = rf.predict(X[val_idx])
        rmse     = np.sqrt(mean_squared_error(y[val_idx], preds))
        mae      = mean_absolute_error(y[val_idx], preds)
        val_dates = df.iloc[val_idx]["date"]
        print(f"    Fold {fold}: {val_dates.min().date()} - {val_dates.max().date()} "
              f"| RMSE={rmse:.4f}  MAE={mae:.4f}")
        rmses.append(rmse)
        maes.append(mae)

    print(f"\n  CV RMSE: {np.mean(rmses):.4f} +/- {np.std(rmses):.4f}")
    print(f"  CV MAE:  {np.mean(maes):.4f} +/- {np.std(maes):.4f}")

    # ------------------------------------------------------------------
    # Final model on all data
    # ------------------------------------------------------------------
    final_rf = RandomForestRegressor(
        n_estimators=500,
        max_depth=8,
        min_samples_leaf=10,
        max_features=0.6,
        random_state=42,
        n_jobs=-1,
    )
    final_rf.fit(X, y)

    # Feature importance
    fi = pd.Series(final_rf.feature_importances_, index=FEATURE_COLS).sort_values(ascending=False)
    print(f"\n  Top-8 features (horizon={horizon}d):")
    for feat, score in fi.head(8).items():
        print(f"    {feat:<25} {score:.4f}")

    # ------------------------------------------------------------------
    # Save artifact
    # ------------------------------------------------------------------
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model_version = f"vol_rf_{horizon}d_{date.today().isoformat()}"
    path = MODEL_DIR / f"{model_version}.pkl"
    with open(path, "wb") as fh:
        pickle.dump({
            "model":        final_rf,
            "feature_cols": FEATURE_COLS,
            "horizon":      horizon,
            "ticker":       TICKER,
            "trained_at":   datetime.utcnow().isoformat(),
        }, fh)
    print(f"\n  Saved -> {path}")

    # ------------------------------------------------------------------
    # Write predictions for all rows to volatility_forecasts
    # ------------------------------------------------------------------
    print("  Writing predictions to volatility_forecasts ...")
    X_df   = df[FEATURE_COLS]
    preds  = final_rf.predict(X_df)
    q_lo, q_hi = _forest_quantiles(final_rf, X_df)

    rows = []
    for i, row in enumerate(df.itertuples()):
        rows.append({
            "date":          row.date.date(),
            "model_version": model_version,
            "ticker":        TICKER,
            "horizon_days":  horizon,
            "vol_forecast":  float(preds[i]),
            "vol_lower":     float(q_lo[i]),
            "vol_upper":     float(q_hi[i]),
        })

    pred_df = pd.DataFrame(rows)
    conn.execute(f"""
        DELETE FROM volatility_forecasts
        WHERE model_version = '{model_version}'
    """)
    conn.execute("""
        INSERT INTO volatility_forecasts
            (date, model_version, ticker, horizon_days,
             vol_forecast, vol_lower, vol_upper)
        SELECT date, model_version, ticker, horizon_days,
               vol_forecast, vol_lower, vol_upper
        FROM pred_df
    """)
    conn.commit()
    conn.close()

    return {
        "model_version": model_version,
        "horizon":       horizon,
        "cv_rmse_mean":  float(np.mean(rmses)),
        "cv_rmse_std":   float(np.std(rmses)),
        "cv_mae_mean":   float(np.mean(maes)),
        "artifact_path": str(path),
    }


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def predict(horizon: int | None = None) -> pd.DataFrame:
    """
    Load latest model(s) and score any daily_features rows not yet predicted.
    If horizon is None, runs both 21d and 63d.
    """
    horizons = HORIZONS if horizon is None else [horizon]
    all_results = []

    conn = get_connection()

    for h in horizons:
        pkls = sorted(
            MODEL_DIR.glob(f"vol_rf_{h}d_*.pkl"),
            key=lambda p: p.stat().st_mtime
        )
        if not pkls:
            print(f"  No model found for horizon={h}d. Run train first.")
            continue

        path = pkls[-1]
        with open(path, "rb") as fh:
            artifact = pickle.load(fh)

        model         = artifact["model"]
        feat_cols     = artifact["feature_cols"]
        model_version = path.stem

        df = conn.execute(f"""
            SELECT s.date, {', '.join(f's.{c}' for c in feat_cols)}
            FROM (
                SELECT
                    date,
                    acwi_vol_21d                             AS vol_21d,
                    acwi_vol_21d * SQRT(5.0/21.0)           AS vol_5d_approx,
                    ABS(acwi_ret_1d) * SQRT(252.0)          AS vol_1d_proxy,
                    acwi_vol_63d                             AS vol_63d,
                    {', '.join(MACRO_FEATURES)}
                FROM daily_features
                WHERE acwi_vol_21d IS NOT NULL
                  AND acwi_ret_1d  IS NOT NULL
            ) s
            LEFT JOIN volatility_forecasts vf
                ON s.date = vf.date
                AND vf.model_version = '{model_version}'
                AND vf.horizon_days  = {h}
            WHERE vf.date IS NULL
            ORDER BY s.date
        """).df()

        if df.empty:
            print(f"  No new rows to score for horizon={h}d.")
            continue

        print(f"  Scoring {len(df)} new rows (horizon={h}d) ...")
        X_df   = df[feat_cols]
        preds  = model.predict(X_df)
        q_lo, q_hi = _forest_quantiles(model, X_df)

        rows = []
        for i, row in enumerate(df.iterrows()):
            _, r = row
            rows.append({
                "date":          r["date"],
                "model_version": model_version,
                "ticker":        TICKER,
                "horizon_days":  h,
                "vol_forecast":  float(preds[i]),
                "vol_lower":     float(q_lo[i]),
                "vol_upper":     float(q_hi[i]),
            })

        pred_df = pd.DataFrame(rows)
        conn.execute("""
            INSERT INTO volatility_forecasts
                (date, model_version, ticker, horizon_days,
                 vol_forecast, vol_lower, vol_upper)
            SELECT date, model_version, ticker, horizon_days,
                   vol_forecast, vol_lower, vol_upper
            FROM pred_df
        """)
        conn.commit()
        all_results.append(pred_df)
        print(f"  Wrote {len(pred_df)} predictions -> volatility_forecasts")

    conn.close()
    return pd.concat(all_results) if all_results else pd.DataFrame()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Random Forest volatility forecaster")
    sub    = parser.add_subparsers(dest="cmd")

    tr = sub.add_parser("train", help="Train models for both horizons")
    tr.add_argument("--horizon", type=int, choices=[21, 63], default=None,
                    help="Train only one horizon (default: both)")

    pr = sub.add_parser("predict", help="Score new dates")
    pr.add_argument("--horizon", type=int, choices=[21, 63], default=None)

    args = parser.parse_args()

    if args.cmd == "train":
        horizons = [args.horizon] if args.horizon else HORIZONS
        for h in horizons:
            print(f"\n=== Volatility forecaster — training horizon={h}d ===\n")
            result = train(h)
            print(f"\nDone. model_version={result['model_version']}")
            print(f"      CV RMSE: {result['cv_rmse_mean']:.4f} +/- {result['cv_rmse_std']:.4f}")

    elif args.cmd == "predict":
        print("=== Volatility forecaster — predict ===\n")
        df = predict(horizon=args.horizon)
        if not df.empty:
            print(df.tail(5).to_string(index=False))

    else:
        parser.print_help()
