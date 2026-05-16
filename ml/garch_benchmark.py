"""
ml/garch_benchmark.py — GARCH(1,1) vs RF volatility benchmark

Walk-forward out-of-sample comparison on 21d annualised vol forecast.
Results inform whether RF should be replaced or blended with GARCH.

Usage:
    python ml/garch_benchmark.py
"""
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pickle

warnings.filterwarnings("ignore")

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from db.init_db import get_connection

TRAIN_DAYS = 504   # 2Y rolling window
STEP       = 21    # predict 21 trading days at a time


def run():
    try:
        from arch import arch_model
    except ImportError:
        print("Install arch: pip install arch")
        return

    conn = get_connection()
    df = conn.execute(
        "SELECT date, acwi_ret_1d FROM daily_features "
        "WHERE acwi_ret_1d IS NOT NULL ORDER BY date"
    ).df()

    # Load RF artefacts
    # Find most recent 21d RF vol model (naming: vol_rf_21d_<date>.pkl)
    candidates = sorted(ROOT.glob("models/vol_rf_21d_*.pkl"), reverse=True)
    if not candidates:
        print("No RF 21d vol model found. Run: python ml/volatility.py train")
        return
    pkl_path = candidates[0]
    print(f"Using model: {pkl_path.name}")
    if not pkl_path.exists():
        print("No RF model found. Run: python ml/volatility.py train")
        return

    with open(pkl_path, "rb") as f:
        artefacts = pickle.load(f)
    rf_model    = artefacts["model"]
    rf_features = artefacts["feature_cols"]
    scaler      = None  # vol model uses raw features (no scaler)

    # Build same HAR-RV features used during RF training (see ml/volatility.py)
    df_feat = conn.execute(
        "SELECT date, "
        "acwi_vol_21d AS vol_21d, "
        "acwi_vol_21d * SQRT(5.0/21.0) AS vol_5d_approx, "
        "ABS(acwi_ret_1d) * SQRT(252.0) AS vol_1d_proxy, "
        "acwi_vol_63d AS vol_63d, "
        "vix_close, vix_change_5d, spread_10y_3m, acwi_ret_5d, acwi_ret_21d, "
        "usdpln_vol_21d, cpi_us_yoy, fed_funds_rate "
        "FROM daily_features WHERE acwi_vol_21d IS NOT NULL "
        "AND acwi_ret_1d IS NOT NULL ORDER BY date"
    ).df()
    conn.close()

    df["date"]      = pd.to_datetime(df["date"])
    df_feat["date"] = pd.to_datetime(df_feat["date"])
    df_all = df.merge(df_feat, on="date", how="inner").sort_values("date").reset_index(drop=True)
    print(f"Data: {len(df_all)} rows  {df_all.date.min().date()} — {df_all.date.max().date()}")

    actuals, garch_preds, rf_preds = [], [], []

    for i in range(TRAIN_DAYS, len(df_all) - STEP, STEP):
        train     = df_all.iloc[i - TRAIN_DAYS : i]
        future    = df_all.iloc[i : i + STEP]["acwi_ret_1d"].values
        if len(future) < STEP:
            break

        actual_vol = np.std(future) * np.sqrt(252)
        actuals.append(actual_vol)

        # GARCH(1,1)
        try:
            rets = train["acwi_ret_1d"].values * 100
            gm   = arch_model(rets, vol="Garch", p=1, q=1, dist="normal", rescale=False)
            res  = gm.fit(disp="off", show_warning=False)
            fc   = res.forecast(horizon=STEP, reindex=False)
            garch_preds.append(np.sqrt(fc.variance.values[-1].mean()) * np.sqrt(252) / 100)
        except Exception:
            garch_preds.append(np.nan)

        # RF
        try:
            X = df_all.iloc[i][rf_features].fillna(0).values.reshape(1, -1)
            rf_preds.append(rf_model.predict(X)[0])
        except Exception:
            rf_preds.append(np.nan)

    a = np.array(actuals)
    g = np.array(garch_preds)
    r = np.array(rf_preds)
    mask = ~(np.isnan(g) | np.isnan(r) | np.isnan(a))
    a, g, r = a[mask], g[mask], r[mask]

    rmse_g = np.sqrt(np.mean((g - a) ** 2))
    rmse_r = np.sqrt(np.mean((r - a) ** 2))
    mae_g  = np.mean(np.abs(g - a))
    mae_r  = np.mean(np.abs(r - a))

    print(f"\nWalk-forward results ({len(a)} windows × 21d):")
    print(f"  GARCH(1,1) : RMSE={rmse_g:.4f}  MAE={mae_g:.4f}")
    print(f"  RF (21d)   : RMSE={rmse_r:.4f}  MAE={mae_r:.4f}")
    winner = "GARCH" if rmse_g < rmse_r else "RF"
    ratio  = rmse_r / rmse_g if rmse_g > 0 else float("inf")
    print(f"  Winner (RMSE): {winner}  (RF/GARCH ratio = {ratio:.3f})")
    if abs(ratio - 1) < 0.05:
        print("  → Performance essentially tied (<5% difference).")
    elif winner == "GARCH":
        print(f"  GARCH beats RF by {(1-1/ratio)*100:.1f}%. Consider replacing or blending.")
    else:
        print(f"  RF beats GARCH by {(ratio-1)*100:.1f}%. RF with HAR-RV features justified.")


if __name__ == "__main__":
    run()
