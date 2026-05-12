"""
ml/currency.py — LightGBM quantile forecaster for PLN/USD

Forecasts the PLN/USD exchange rate at two horizons:
  21 days (~1 month) and 63 days (~1 quarter)

Three models per horizon: quantile q=0.10 (lower bound), q=0.50 (median),
q=0.90 (upper bound). The output stored in fx_forecasts gives the frontend
everything it needs to render a fan chart without loading any model at
render time.

Design decisions:

WHY PLN/USD, not USD/PLN:
  The schema column is `usdpln` (how many PLN per 1 USD). A higher value
  means PLN has weakened — bad for a Warsaw investor buying a USD-denominated
  ACWI ETF (they pay more PLN per share). The app surfaces "worst case" as
  rate_upper (90th pct), which is the high-PLN/USD scenario. This framing is
  intuitive for the user: "in the worst case, 1 USD will cost 4.40 PLN".

WHY LightGBM quantile regression:
  LightGBM supports `objective='quantile'` natively — it optimizes the pinball
  loss directly, which is the theoretically correct loss for quantile targets.
  This avoids the post-hoc quantile extraction hack used in volatility.py
  (leaf-node percentiles are approximate; pinball loss is exact).

WHY these features:
  FX rates are driven by interest rate differentials (UIP theory), inflation
  differentials (PPP theory), and global risk sentiment. The `rate_differential`
  (fed_funds - nbp_rate) and `cpi_differential` (cpi_us - cpi_pl) are already
  in daily_features and directly proxy UIP and PPP respectively. VIX and
  acwi_ret capture risk sentiment — PLN is a "high-beta" EM currency that
  depreciates sharply in risk-off episodes (documented in NBER research doc).

WHY NOT include usdpln itself as a feature:
  usdpln_ret_21d (the 21d log return) is included — it captures momentum.
  The raw level usdpln is intentionally omitted from features because the
  model predicts a LEVEL (future rate), and using the current level as a
  feature would make the model a near-trivial "rate barely moves" predictor
  with artificially low RMSE. Returns and differentials are the economic
  signals; the current level is added back at prediction time to convert the
  log-return forecast into an absolute rate (see predict()).

WHY walk-forward CV with gap:
  FX rates are autocorrelated. A standard TimeSeriesSplit has no gap between
  train and val — the last training row and first val row are adjacent, which
  leaks recent information. We use a 21-day gap (equal to the shorter horizon)
  to simulate realistic out-of-sample conditions.
"""

import sys
import pickle
import warnings
from pathlib import Path
from datetime import date, datetime

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import mean_absolute_error

sys.path.insert(0, str(Path(__file__).parent.parent))
from db.init_db import get_connection

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PAIR       = "USDPLN"
HORIZONS   = [21, 63]
QUANTILES  = [0.10, 0.50, 0.90]
MODEL_DIR  = Path(__file__).parent.parent / "models"
N_SPLITS   = 5
MIN_ROWS   = 500

FEATURE_COLS = [
    # Momentum / recent FX dynamics
    "usdpln_ret_21d",       # 21d log return of PLN/USD — trend signal
    "usdpln_vol_21d",       # realized FX vol — regime signal
    # Interest rate differential (UIP proxy)
    "rate_differential",    # fed_funds_rate - nbp_rate
    "fed_funds_rate",       # US rate level
    "nbp_rate",             # Polish rate level
    # Inflation differential (PPP proxy)
    "cpi_differential",     # cpi_us_yoy - cpi_pl_yoy
    "cpi_us_yoy",
    "cpi_pl_yoy",
    # Risk sentiment (PLN is high-beta EM currency)
    "vix_close",
    "vix_change_5d",
    "acwi_ret_5d",
    "acwi_ret_21d",
    # Yield curve (US macro regime)
    "spread_10y_3m",
    "yield_10y",
    # Gold (safe-haven flow proxy)
    "gold_ret_1d",
]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _build_dataset(conn, horizon: int) -> pd.DataFrame:
    """
    Build feature matrix and target for a given horizon.

    Target: forward log return of usdpln over `horizon` trading days.
    WHY log return not level: stationarity. Log returns are mean-reverting
    and approximately normal, which is required for the quantile regression
    loss to behave well. We convert back to levels in the output step.
    """
    df = conn.execute(f"""
        SELECT
            date,
            usdpln,
            {', '.join(FEATURE_COLS)}
        FROM daily_features
        WHERE usdpln          IS NOT NULL
          AND usdpln_ret_21d  IS NOT NULL
          AND rate_differential IS NOT NULL
          AND vix_close       IS NOT NULL
        ORDER BY date
    """).df()

    df["date"] = pd.to_datetime(df["date"])

    # Forward log return: log(usdpln_{t+horizon} / usdpln_t)
    df["target_logret"] = np.log(df["usdpln"].shift(-horizon) / df["usdpln"])
    df = df.dropna(subset=["target_logret"] + FEATURE_COLS).copy()
    return df


# ---------------------------------------------------------------------------
# LightGBM quantile params
# ---------------------------------------------------------------------------

def _lgbm_params(quantile: float) -> dict:
    return {
        "objective":       "quantile",
        "alpha":           quantile,      # pinball loss quantile
        "metric":          "quantile",
        "num_leaves":      31,
        "max_depth":       5,
        "min_child_samples": 20,
        "learning_rate":   0.05,
        "n_estimators":    400,
        "subsample":       0.8,
        "colsample_bytree": 0.7,
        "reg_lambda":      1.0,
        "random_state":    42,
        "verbose":         -1,
        "n_jobs":          -1,
    }


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train(horizon: int) -> dict:
    """
    Train three quantile models (q=0.10, 0.50, 0.90) for one horizon.
    Saves one pkl per quantile. Writes predictions to fx_forecasts.
    """
    conn = get_connection()
    df   = _build_dataset(conn, horizon)

    if len(df) < MIN_ROWS:
        raise ValueError(f"Only {len(df)} rows for horizon={horizon}d")

    print(f"  Horizon {horizon}d: {len(df)} rows  "
          f"(target log-ret mean={df['target_logret'].mean():.4f}, "
          f"std={df['target_logret'].std():.4f})")

    X = df[FEATURE_COLS]
    y = df["target_logret"]

    # Walk-forward CV on the median model only (representative)
    print(f"  Walk-forward CV (q=0.50) ...")
    tscv = TimeSeriesSplit(n_splits=N_SPLITS)
    maes = []

    for fold, (tr_idx, val_idx) in enumerate(tscv.split(X), 1):
        # Apply gap: drop last `horizon` rows from training to avoid leakage
        tr_idx_gapped = tr_idx[tr_idx < tr_idx[-1] - horizon]
        if len(tr_idx_gapped) < 100:
            continue

        model = lgb.LGBMRegressor(**_lgbm_params(0.50))
        model.fit(
            X.iloc[tr_idx_gapped], y.iloc[tr_idx_gapped],
            callbacks=[lgb.log_evaluation(-1)],
        )
        preds = model.predict(X.iloc[val_idx])
        mae   = mean_absolute_error(y.iloc[val_idx], preds)
        val_dates = df.iloc[val_idx]["date"]
        print(f"    Fold {fold}: {val_dates.min().date()} - {val_dates.max().date()} "
              f"| MAE(log-ret)={mae:.5f}")
        maes.append(mae)

    print(f"\n  CV MAE (log-ret): {np.mean(maes):.5f} +/- {np.std(maes):.5f}")

    # ------------------------------------------------------------------
    # Train final models for all three quantiles
    # ------------------------------------------------------------------
    final_models = {}
    model_versions = {}

    for q in QUANTILES:
        print(f"  Training final model q={q} ...")
        m = lgb.LGBMRegressor(**_lgbm_params(q))
        m.fit(X, y, callbacks=[lgb.log_evaluation(-1)])
        final_models[q] = m

        model_version = f"fx_lgbm_{PAIR}_{horizon}d_q{int(q*100):02d}_{date.today().isoformat()}"
        model_versions[q] = model_version

        path = MODEL_DIR / f"{model_version}.pkl"
        with open(path, "wb") as fh:
            pickle.dump({
                "model":        m,
                "feature_cols": FEATURE_COLS,
                "quantile":     q,
                "horizon":      horizon,
                "pair":         PAIR,
                "trained_at":   datetime.utcnow().isoformat(),
            }, fh)
        print(f"    Saved -> {path}")

    # Feature importance from median model
    fi = pd.Series(
        final_models[0.50].feature_importances_,
        index=FEATURE_COLS
    ).sort_values(ascending=False)
    print(f"\n  Top-8 features (q=0.50, horizon={horizon}d):")
    for feat, score in fi.head(8).items():
        print(f"    {feat:<25} {score:.0f}")

    # ------------------------------------------------------------------
    # Write predictions to fx_forecasts
    # Use a shared model_version key (the median one) for the row PK.
    # Store all three quantile outputs in the same row.
    # ------------------------------------------------------------------
    mv_key = model_versions[0.50]  # canonical version for this horizon

    logret_lo  = final_models[0.10].predict(X)
    logret_mid = final_models[0.50].predict(X)
    logret_hi  = final_models[0.90].predict(X)

    # Convert log returns back to rate levels
    usdpln_now = df["usdpln"].values
    rate_lo    = usdpln_now * np.exp(logret_lo)
    rate_mid   = usdpln_now * np.exp(logret_mid)
    rate_hi    = usdpln_now * np.exp(logret_hi)

    rows = []
    for i, row in enumerate(df.itertuples()):
        rows.append({
            "date":          row.date.date(),
            "model_version": mv_key,
            "pair":          PAIR,
            "horizon_days":  horizon,
            "rate_point":    float(rate_mid[i]),
            "rate_lower":    float(rate_lo[i]),
            "rate_upper":    float(rate_hi[i]),
        })

    pred_df = pd.DataFrame(rows)
    conn.execute(f"DELETE FROM fx_forecasts WHERE model_version = '{mv_key}'")
    conn.execute("""
        INSERT INTO fx_forecasts
            (date, model_version, pair, horizon_days,
             rate_point, rate_lower, rate_upper)
        SELECT date, model_version, pair, horizon_days,
               rate_point, rate_lower, rate_upper
        FROM pred_df
    """)
    conn.commit()
    conn.close()

    print(f"\n  Wrote {len(pred_df)} rows -> fx_forecasts")

    return {
        "model_version":   mv_key,
        "horizon":         horizon,
        "cv_mae_log_mean": float(np.mean(maes)),
        "cv_mae_log_std":  float(np.std(maes)),
    }


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def predict(horizon: int | None = None) -> pd.DataFrame:
    """
    Load latest quantile models and score any unscored daily_features rows.
    """
    horizons = HORIZONS if horizon is None else [horizon]
    all_results = []
    conn = get_connection()

    for h in horizons:
        # Load all three quantile models for this horizon
        models = {}
        mv_key = None

        for q in QUANTILES:
            tag  = f"fx_lgbm_{PAIR}_{h}d_q{int(q*100):02d}_"
            pkls = sorted(MODEL_DIR.glob(f"{tag}*.pkl"),
                          key=lambda p: p.stat().st_mtime)
            if not pkls:
                print(f"  No model for horizon={h}d q={q}. Run train first.")
                break
            path = pkls[-1]
            with open(path, "rb") as fh:
                artifact = pickle.load(fh)
            models[q]    = artifact["model"]
            feat_cols    = artifact["feature_cols"]
            if q == 0.50:
                mv_key = path.stem

        if len(models) < 3 or mv_key is None:
            continue

        df = conn.execute(f"""
            SELECT f.date, f.usdpln, {', '.join(f'f.{c}' for c in feat_cols)}
            FROM daily_features f
            LEFT JOIN fx_forecasts fx
                ON f.date = fx.date
                AND fx.model_version = '{mv_key}'
                AND fx.horizon_days  = {h}
            WHERE fx.date IS NULL
              AND f.usdpln IS NOT NULL
              AND f.usdpln_ret_21d IS NOT NULL
              AND f.rate_differential IS NOT NULL
              AND f.vix_close IS NOT NULL
            ORDER BY f.date
        """).df()

        if df.empty:
            print(f"  No new rows for horizon={h}d.")
            continue

        print(f"  Scoring {len(df)} rows (horizon={h}d) ...")
        X_df = df[feat_cols]

        logret_lo  = models[0.10].predict(X_df)
        logret_mid = models[0.50].predict(X_df)
        logret_hi  = models[0.90].predict(X_df)

        usdpln_now = df["usdpln"].values
        rate_lo    = usdpln_now * np.exp(logret_lo)
        rate_mid   = usdpln_now * np.exp(logret_mid)
        rate_hi    = usdpln_now * np.exp(logret_hi)

        rows = []
        for i, (_, r) in enumerate(df.iterrows()):
            rows.append({
                "date":          r["date"],
                "model_version": mv_key,
                "pair":          PAIR,
                "horizon_days":  h,
                "rate_point":    float(rate_mid[i]),
                "rate_lower":    float(rate_lo[i]),
                "rate_upper":    float(rate_hi[i]),
            })

        pred_df = pd.DataFrame(rows)
        conn.execute("""
            INSERT INTO fx_forecasts
                (date, model_version, pair, horizon_days,
                 rate_point, rate_lower, rate_upper)
            SELECT date, model_version, pair, horizon_days,
                   rate_point, rate_lower, rate_upper
            FROM pred_df
        """)
        conn.commit()
        all_results.append(pred_df)
        print(f"  Wrote {len(pred_df)} rows -> fx_forecasts")

    conn.close()
    return pd.concat(all_results) if all_results else pd.DataFrame()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LightGBM quantile PLN/USD forecaster")
    sub    = parser.add_subparsers(dest="cmd")

    tr = sub.add_parser("train")
    tr.add_argument("--horizon", type=int, choices=[21, 63], default=None)

    pr = sub.add_parser("predict")
    pr.add_argument("--horizon", type=int, choices=[21, 63], default=None)

    args = parser.parse_args()

    if args.cmd == "train":
        horizons = [args.horizon] if args.horizon else HORIZONS
        for h in horizons:
            print(f"\n=== FX quantile forecaster — training horizon={h}d ===\n")
            result = train(h)
            print(f"\nDone. {result['model_version']}")
            print(f"      CV MAE (log-ret): {result['cv_mae_log_mean']:.5f} "
                  f"+/- {result['cv_mae_log_std']:.5f}")

    elif args.cmd == "predict":
        print("=== FX quantile forecaster — predict ===\n")
        df = predict(horizon=args.horizon)
        if not df.empty:
            print(df.tail(5).to_string(index=False))

    else:
        parser.print_help()
