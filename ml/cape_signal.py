"""
ml/cape_signal.py — CAPE-based 10-year forward return quantile signal

Uses Shiller data (1871-2026) to estimate distribution of 10Y forward real
returns conditional on CAPE and real long rate.

Key references:
- Campbell & Shiller (1988, 1998): CAPE explains ~40% of 10Y return variance
- Asness (2012): CAPE decile → median return table (already in decision.py)

This model goes further: fits QuantileRegressor for 10th/50th/90th pct.
Results stored in cape_forecasts table and used by the projection engine.

Usage:
    python ml/cape_signal.py train
    python ml/cape_signal.py predict
"""

import argparse
import os
import pickle
import sys
import warnings
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import QuantileRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")

ROOT     = Path(__file__).parent.parent
PKL_PATH = ROOT / "models" / "cape_signal.pkl"
SHILLER  = ROOT / "shiller.csv"

QUANTILES   = [0.10, 0.50, 0.90]
HORIZON_Y   = 10    # 10-year forward return
HORIZON_M   = HORIZON_Y * 12


def _load_full_shiller() -> pd.DataFrame:
    """Load ALL Shiller rows with features, regardless of whether 10Y return is known."""
    df = pd.read_csv(SHILLER, parse_dates=["Date"])
    df = df.rename(columns={
        "Date": "date", "SP500": "sp500",
        "Consumer Price Index": "cpi",
        "Long Interest Rate": "long_rate",
        "Real Price": "real_price", "PE10": "cape",
    })
    df = df[["date", "sp500", "cpi", "long_rate", "real_price", "cape"]].copy()
    df = df[df["sp500"] > 0].sort_values("date").reset_index(drop=True)
    df["cpi"]       = pd.to_numeric(df["cpi"], errors="coerce").ffill()
    df["long_rate"] = pd.to_numeric(df["long_rate"], errors="coerce").ffill()
    df["cape"]      = pd.to_numeric(df["cape"], errors="coerce")
    df["log_cape"]  = np.log(df["cape"].clip(lower=1))
    df["real_long_rate"] = df["long_rate"] - df["cpi"].pct_change(12).fillna(0) * 100
    return df.dropna(subset=["log_cape"])


def load_shiller() -> pd.DataFrame:
    df = pd.read_csv(SHILLER, parse_dates=["Date"])
    df = df.rename(columns={
        "Date":                 "date",
        "SP500":                "sp500",
        "Consumer Price Index": "cpi",
        "Long Interest Rate":   "long_rate",
        "Real Price":           "real_price",
        "PE10":                 "cape",
    })
    df = df[["date", "sp500", "cpi", "long_rate", "real_price", "cape"]].copy()
    df = df[df["sp500"] > 0].sort_values("date").reset_index(drop=True)

    # 10-year forward annualised real return (only known up to 2016)
    df["real_price_10y_fwd"] = df["real_price"].shift(-HORIZON_M)
    df["ret_10y_real"] = (
        (df["real_price_10y_fwd"] / df["real_price"]) ** (1 / HORIZON_Y) - 1
    )

    # Features
    df["log_cape"]       = np.log(df["cape"].clip(lower=1))
    df["real_long_rate"] = df["long_rate"] - df["cpi"].pct_change(12).fillna(0) * 100
    df["earnings_yield"] = np.where(df["cape"] > 0, 1.0 / df["cape"], np.nan)

    df = df.dropna(subset=["log_cape", "ret_10y_real"])
    return df


FEATURE_COLS = ["log_cape", "real_long_rate"]


def train():
    df = load_shiller()
    print(f"Training data: {len(df)} rows, {df['date'].min().date()} - {df['date'].max().date()}")
    print(f"(10Y forward returns available up to ~{(df['date'].max() - pd.DateOffset(years=HORIZON_Y)).date()})")

    X = df[FEATURE_COLS].fillna(0).values
    y = df["ret_10y_real"].values

    scaler = StandardScaler()
    X_s    = scaler.fit_transform(X)

    models = {}
    for q in QUANTILES:
        qr = QuantileRegressor(quantile=q, alpha=0.01, solver="highs")
        qr.fit(X_s, y)
        preds = qr.predict(X_s)
        mae   = mean_absolute_error(y, preds)
        print(f"  q={q:.2f}: MAE={mae:.4f}  coef={qr.coef_}")
        models[q] = qr

    PKL_PATH.parent.mkdir(exist_ok=True)
    with open(PKL_PATH, "wb") as f:
        pickle.dump({"models": models, "scaler": scaler,
                     "feature_cols": FEATURE_COLS}, f)
    print(f"Model saved -> {PKL_PATH}")

    # Load full shiller for prediction (including post-2016 rows without known returns)
    full_shiller = _load_full_shiller()

    # Create cape_forecasts table if needed
    con = get_connection()
    con.execute("""
        CREATE TABLE IF NOT EXISTS cape_forecasts (
            date          DATE PRIMARY KEY,
            cape          DOUBLE,
            ret_q10       DOUBLE,
            ret_q50       DOUBLE,
            ret_q90       DOUBLE,
            model_version VARCHAR,
            predicted_at  TIMESTAMPTZ DEFAULT now()
        )
    """)
    con.commit()
    con.close()

    # Write predictions for ALL Shiller rows (including post-2016 without known returns)
    _write_predictions(df, models, scaler, all_shiller=full_shiller)


def _write_predictions(df: pd.DataFrame, models: dict,
                       scaler: StandardScaler, all_shiller: pd.DataFrame = None):
    """Write CAPE forecasts for all Shiller rows, including recent ones without known returns."""
    version = f"cape_qr_{date.today().isoformat()}"
    # Apply model to full Shiller dataset (not just training rows with known returns)
    target = all_shiller if all_shiller is not None else df
    X_s     = scaler.transform(target[FEATURE_COLS].fillna(0).values)

    q10 = models[0.10].predict(X_s)
    q50 = models[0.50].predict(X_s)
    q90 = models[0.90].predict(X_s)

    con = get_connection()
    con.execute("DELETE FROM cape_forecasts WHERE model_version = %s", [version])

    for i, row in target.iterrows():
        con.execute("""
            INSERT INTO cape_forecasts
                (date, cape, ret_q10, ret_q50, ret_q90, model_version)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (date) DO UPDATE SET
                cape=excluded.cape, ret_q10=excluded.ret_q10,
                ret_q50=excluded.ret_q50, ret_q90=excluded.ret_q90,
                model_version=excluded.model_version
        """, [row["date"].date() if hasattr(row["date"], "date") else row["date"],
              float(row["cape"]),
              float(q10[i]), float(q50[i]), float(q90[i]), version])

    con.commit()
    con.close()

    # Print current signal (latest row)
    latest_i = len(target) - 1
    latest   = target.iloc[-1]
    print(f"\nCurrent CAPE signal ({latest['date'].date() if hasattr(latest['date'], 'date') else latest['date']}):")
    print(f"  CAPE         = {latest['cape']:.1f}")
    print(f"  10Y real ret : q10={q10[latest_i]*100:.1f}%  q50={q50[latest_i]*100:.1f}%  q90={q90[latest_i]*100:.1f}%")


def predict():
    if not PKL_PATH.exists():
        print("No trained model. Run: python ml/cape_signal.py train")
        sys.exit(1)

    with open(PKL_PATH, "rb") as f:
        artefacts = pickle.load(f)

    models  = artefacts["models"]
    scaler  = artefacts["scaler"]

    full = _load_full_shiller()
    _write_predictions(full, models, scaler)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["train", "predict"])
    args = parser.parse_args()
    if args.command == "train":
        train()
    else:
        predict()
