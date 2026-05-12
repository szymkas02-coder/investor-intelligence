"""
ml/recession.py — NBER recession probability classifier

Ground truth: FRED USREC (monthly binary, external — not derived from our features).
Model: LightGBM with class weighting + isotonic calibration.
Validation: sliding 20-year walk-forward window.

Key references:
- Estrella & Mishkin (1998): yield spread as primary recession predictor
- Bianchi et al. (2024): LightGBM outperforms Probit for recession nowcasting
- Sahm (2019): unemployment threshold rule

Usage:
    python ml/recession.py train
    python ml/recession.py predict
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
from lightgbm import LGBMClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import (average_precision_score, brier_score_loss,
                              matthews_corrcoef, roc_auc_score)
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")

ROOT     = Path(__file__).parent.parent
PKL_PATH = ROOT / "models" / "recession.pkl"

FEATURES = [
    "spread_10y_3m",    # Estrella & Mishkin — best single predictor, 8-12M lead
    "spread_10y_2y",    # complementary yield curve signal
    "vix_close",        # fear gauge, 1-6M lead
    "acwi_ret_63d",     # 3M equity momentum
    "unemployment_us",  # Sahm rule basis
    "fed_funds_rate",   # monetary tightening
    "cpi_us_yoy",       # inflation pressure
    "usdpln_vol_21d",   # PLN vol as global risk-off proxy
]

MIN_TRAIN_YEARS = 20   # sliding window minimum


# ─── Data loading ────────────────────────────────────────────────────────────

def load_data() -> pd.DataFrame:
    con = get_connection()

    # Daily features (forward-fill monthly macro into daily)
    df = con.execute(f"""
        SELECT date, {', '.join(FEATURES)}
        FROM daily_features
        ORDER BY date
    """).df()

    # USREC — monthly, need to forward-fill to daily
    usrec = con.execute("""
        SELECT date, value AS usrec
        FROM raw_macro
        WHERE series_id = 'USREC'
        ORDER BY date
    """).df()
    con.close()

    # Forward-fill USREC to daily
    df["date"] = pd.to_datetime(df["date"])
    usrec["date"] = pd.to_datetime(usrec["date"])
    df = df.merge(usrec, on="date", how="left")
    df["usrec"] = df["usrec"].ffill()

    df = df.dropna(subset=["usrec"] + FEATURES[:4])  # need at least yield curve + VIX
    df = df.sort_values("date").reset_index(drop=True)
    print(f"Dataset: {len(df)} daily rows, {df['date'].min().date()} - {df['date'].max().date()}")
    print(f"Recession days: {df['usrec'].sum():.0f} ({df['usrec'].mean()*100:.1f}%)")
    return df


# ─── Walk-forward validation ─────────────────────────────────────────────────

def walk_forward_cv(df: pd.DataFrame, window_years: int = 20):
    results = []
    dates = df["date"]
    first_year = dates.min().year
    last_year  = dates.max().year

    for test_year in range(first_year + window_years, last_year + 1, 3):
        train_end   = pd.Timestamp(f"{test_year - 1}-12-31")
        train_start = pd.Timestamp(f"{test_year - 1 - window_years}-01-01")
        test_start  = pd.Timestamp(f"{test_year}-01-01")
        test_end    = pd.Timestamp(f"{test_year + 2}-12-31")

        train = df[(df["date"] >= train_start) & (df["date"] <= train_end)]
        test  = df[(df["date"] >= test_start)  & (df["date"] <= test_end)]

        if len(train) < 1000 or len(test) < 100:
            continue
        if train["usrec"].sum() < 50:
            continue

        X_tr = train[FEATURES].fillna(method="ffill").fillna(0).values
        y_tr = train["usrec"].astype(int).values
        X_te = test[FEATURES].fillna(method="ffill").fillna(0).values
        y_te = test["usrec"].astype(int).values

        scale = StandardScaler()
        X_tr  = scale.fit_transform(X_tr)
        X_te  = scale.transform(X_te)

        n_pos = y_tr.sum()
        n_neg = len(y_tr) - n_pos
        w     = n_neg / max(n_pos, 1)

        lgbm = LGBMClassifier(
            n_estimators=300, learning_rate=0.05, max_depth=4,
            scale_pos_weight=w, random_state=42, verbose=-1,
        )
        model = CalibratedClassifierCV(lgbm, cv=3, method="isotonic")
        model.fit(X_tr, y_tr)

        probs = model.predict_proba(X_te)[:, 1]
        auprc = average_precision_score(y_te, probs)
        auroc = roc_auc_score(y_te, probs) if y_te.sum() > 0 else np.nan
        bss   = 1 - brier_score_loss(y_te, probs) / (y_te.mean() * (1 - y_te.mean()) + 1e-9)

        results.append({"test_year": test_year, "AUPRC": auprc, "AUROC": auroc, "BSS": bss})
        print(f"  test {test_year}-{test_year+2}: AUPRC={auprc:.3f} AUROC={auroc:.3f} BSS={bss:.3f}")

    return results


# ─── Final model training ─────────────────────────────────────────────────────

def train():
    df = load_data()

    print("\nWalk-forward CV (20-year sliding window, step 3Y):")
    cv_results = walk_forward_cv(df)
    if cv_results:
        df_cv = pd.DataFrame(cv_results)
        print(f"\nMean CV: AUPRC={df_cv['AUPRC'].mean():.3f} "
              f"AUROC={df_cv['AUROC'].mean():.3f} BSS={df_cv['BSS'].mean():.3f}")

    # Fit final model on all available data
    print("\nFitting final model on full history...")
    X = df[FEATURES].fillna(method="ffill").fillna(0).values
    y = df["usrec"].astype(int).values

    scaler = StandardScaler()
    X_s    = scaler.fit_transform(X)

    n_pos = y.sum()
    n_neg = len(y) - n_pos
    w     = n_neg / max(n_pos, 1)

    lgbm = LGBMClassifier(
        n_estimators=500, learning_rate=0.03, max_depth=4,
        num_leaves=15, min_child_samples=50,
        scale_pos_weight=w, random_state=42, verbose=-1,
    )
    model = CalibratedClassifierCV(lgbm, cv=5, method="isotonic")
    model.fit(X_s, y)

    PKL_PATH.parent.mkdir(exist_ok=True)
    with open(PKL_PATH, "wb") as f:
        pickle.dump({"model": model, "scaler": scaler, "features": FEATURES}, f)
    print(f"Model saved -> {PKL_PATH}")

    # Write predictions for all dates
    probs = model.predict_proba(X_s)[:, 1]
    df    = df.copy()
    df["recession_prob"] = probs
    df["recession_pred"] = probs > 0.5

    _write_predictions(df)


def _write_predictions(df: pd.DataFrame):
    version = f"recession_lgbm_{date.today().isoformat()}"
    con = get_connection()
    con.execute(f"DELETE FROM recession_predictions WHERE model_version = '{version}'")

    for _, row in df.iterrows():
        con.execute("""
            INSERT INTO recession_predictions
                (date, model_version, recession_prob, recession_pred)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (date, model_version) DO UPDATE SET
                recession_prob = excluded.recession_prob,
                recession_pred = excluded.recession_pred
        """, [row["date"].date(), version,
              float(row["recession_prob"]), bool(row["recession_pred"])])

    con.commit()
    con.close()

    latest = df.iloc[-1]
    print(f"Predictions written ({len(df)} rows). "
          f"Latest ({latest['date'].date()}): {latest['recession_prob']:.3f}")


def predict():
    if not PKL_PATH.exists():
        print("No trained model. Run: python ml/recession.py train")
        sys.exit(1)

    with open(PKL_PATH, "rb") as f:
        artefacts = pickle.load(f)

    model   = artefacts["model"]
    scaler  = artefacts["scaler"]
    features = artefacts["features"]

    con = get_connection()
    df  = con.execute(f"SELECT date, {', '.join(features)} FROM daily_features ORDER BY date").df()
    con.close()

    df["date"] = pd.to_datetime(df["date"])
    X = df[features].fillna(method="ffill").fillna(0).values
    X_s = scaler.transform(X)

    probs = model.predict_proba(X_s)[:, 1]
    df["recession_prob"] = probs
    df["recession_pred"] = probs > 0.5
    _write_predictions(df)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["train", "predict"])
    args = parser.parse_args()
    if args.command == "train":
        train()
    else:
        predict()
