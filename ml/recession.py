"""
ml/recession.py — NBER recession probability classifier

Ground truth: FRED USREC (monthly binary, external — not derived from our features).
Model: LightGBM with class weighting + isotonic calibration.

Training data: extended back to ~1960 via direct FRED API pull (monthly).
This gives ~7 recessions (1960, 1969, 1973, 1980, 1990, 2001, 2008, 2020)
instead of just COVID from the 2012-present daily_features window.

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
import requests
from lightgbm import LGBMClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import (average_precision_score, brier_score_loss,
                              roc_auc_score)
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")

ROOT     = Path(__file__).parent.parent
PKL_PATH = ROOT / "models" / "recession.pkl"

sys.path.insert(0, str(ROOT))

# Load .env
_env_path = ROOT / ".env"
if _env_path.exists():
    for _line in _env_path.read_text().splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from db.init_db import get_connection, PH

# Core features available from 1960 via FRED monthly
FEATURES_CORE = [
    "spread_10y_3m",    # Estrella & Mishkin — best single predictor, 8-12M lead
    "spread_10y_2y",    # complementary yield curve signal
    "unemployment_us",  # Sahm rule basis
    "fed_funds_rate",   # monetary tightening
    "cpi_us_yoy",       # inflation pressure
    "indpro",           # Industrial production YoY — LEI component
]

# Extended features only available from ~2000+ (NaN-filled for older rows)
FEATURES_EXTENDED = [
    "vix_close",        # VIX starts 1990
    "housing_permits",  # Housing permits starts 1959 (monthly)
    "sahm_indicator",   # Sahm rule — real-time, starts 2000
    "initial_claims",   # Initial jobless claims — starts 1967
]

FEATURES = FEATURES_CORE + FEATURES_EXTENDED

# FRED series to fetch for extended history (monthly)
FRED_EXTENDED_SERIES = {
    "GS10":    "yield_10y",          # 10Y Treasury — from 1953
    "TB3MS":   "yield_3m",           # 3M T-bill — from 1934
    "GS2":     "yield_2y",           # 2Y Treasury — from 1976
    "FEDFUNDS":"fed_funds_rate",      # Fed funds — from 1954
    "UNRATE":  "unemployment_us",     # Unemployment — from 1948
    "CPIAUCSL":"cpi_level",           # CPI level — from 1947
    "INDPRO":  "indpro_level",        # Industrial production — from 1919
    "VIXCLS":  "vix_close",           # VIX — from 1990
    "PERMIT":  "housing_permits",     # Housing permits — from 1960
    "ICSA":    "initial_claims_raw",  # Initial claims weekly (will resample)
    "SAHMREALTIME": "sahm_indicator", # Sahm rule — from 2000
    "USREC":   "usrec",               # NBER recession — from 1854
}

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
HISTORY_START = "1960-01-01"


def _fetch_fred(series_id: str, start: str = HISTORY_START) -> pd.Series:
    key = os.environ.get("FRED_API_KEY", "")
    if not key:
        raise EnvironmentError("FRED_API_KEY not set")
    r = requests.get(FRED_BASE, params={
        "series_id": series_id, "observation_start": start,
        "api_key": key, "file_type": "json",
    }, timeout=30)
    r.raise_for_status()
    obs = r.json().get("observations", [])
    s = pd.Series(
        {o["date"]: float(o["value"]) for o in obs if o["value"] != "."},
        name=series_id,
    )
    s.index = pd.to_datetime(s.index)
    return s


# ─── Data loading — extended history from FRED ───────────────────────────────

def load_data_extended() -> pd.DataFrame:
    """Build monthly training dataset from 1960 using direct FRED API calls."""
    print("  Fetching extended history from FRED (~1960-present, monthly)...")
    series = {}
    for fred_id, col in FRED_EXTENDED_SERIES.items():
        try:
            s = _fetch_fred(fred_id)
            # Resample weekly series (ICSA) to monthly mean
            if fred_id == "ICSA":
                s = s.resample("MS").mean()
            else:
                s = s.resample("MS").last()
            series[col] = s
            print(f"    {fred_id}: {len(s)} rows, {s.index.min().date()} - {s.index.max().date()}")
        except Exception as e:
            print(f"    {fred_id}: FAILED ({e})")

    df = pd.DataFrame(series).sort_index()
    df.index.name = "date"
    df = df.reset_index()

    # Derived features
    df["spread_10y_3m"] = df["yield_10y"] - df["yield_3m"]
    df["spread_10y_2y"] = df.get("yield_2y", pd.Series(dtype=float)) - df["yield_3m"] \
        if "yield_2y" in df.columns else np.nan
    df["cpi_us_yoy"] = df["cpi_level"].pct_change(12) * 100
    df["indpro"] = df["indpro_level"].pct_change(12) * 100  # YoY%
    df["initial_claims"] = df.get("initial_claims_raw", np.nan)

    # Ensure all FEATURES columns exist
    for f in FEATURES:
        if f not in df.columns:
            df[f] = np.nan

    df = df.dropna(subset=["usrec", "spread_10y_3m", "unemployment_us"])
    df = df.sort_values("date").reset_index(drop=True)
    print(f"  Extended dataset: {len(df)} monthly rows, "
          f"{df['date'].min().date()} - {df['date'].max().date()}")
    print(f"  Recession months: {df['usrec'].sum():.0f} ({df['usrec'].mean()*100:.1f}%)")
    return df


def load_data() -> pd.DataFrame:
    """Load daily data from daily_features for predict() calls only."""
    con = get_connection()

    existing = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'daily_features'"
    ).fetchall()}
    features = [f for f in FEATURES if f in existing]

    df = con.execute(f"""
        SELECT date, {', '.join(features)}
        FROM daily_features
        ORDER BY date
    """).df()

    usrec = con.execute("""
        SELECT date, value AS usrec
        FROM raw_macro
        WHERE series_id = 'USREC'
        ORDER BY date
    """).df()
    con.close()

    df["date"] = pd.to_datetime(df["date"])
    usrec["date"] = pd.to_datetime(usrec["date"])
    df = df.merge(usrec, on="date", how="left")
    df["usrec"] = df["usrec"].ffill()

    for f in FEATURES:
        if f not in df.columns:
            df[f] = np.nan

    df = df.dropna(subset=["spread_10y_3m"])
    df = df.sort_values("date").reset_index(drop=True)
    print(f"Dataset: {len(df)} daily rows, {df['date'].min().date()} - {df['date'].max().date()}")
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

        if len(train) < 120 or len(test) < 12:   # monthly rows (was 1000/100 for daily)
            continue
        if train["usrec"].sum() < 10:
            continue

        X_tr = train[FEATURES].ffill().fillna(0).values
        y_tr = train["usrec"].astype(int).values
        X_te = test[FEATURES].ffill().fillna(0).values
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
        auprc = average_precision_score(y_te, probs) if y_te.sum() > 0 else np.nan
        auroc = roc_auc_score(y_te, probs) if y_te.sum() > 0 and y_te.sum() < len(y_te) else np.nan
        bss   = 1 - brier_score_loss(y_te, probs) / (y_te.mean() * (1 - y_te.mean()) + 1e-9)

        results.append({"test_year": test_year, "AUPRC": auprc, "AUROC": auroc, "BSS": bss})
        print(f"  test {test_year}-{test_year+2}: AUPRC={auprc:.3f} AUROC={auroc:.3f} BSS={bss:.3f}")

    return results


# ─── Final model training ─────────────────────────────────────────────────────

def train():
    print("Loading extended training data from FRED (1960-present, monthly)...")
    df = load_data_extended()

    print("\nWalk-forward CV (20-year sliding window, step 3Y):")
    cv_results = walk_forward_cv(df)
    if cv_results:
        df_cv = pd.DataFrame(cv_results)
        valid = df_cv.dropna()
        if len(valid):
            print(f"\nMean CV: AUPRC={valid['AUPRC'].mean():.3f} "
                  f"AUROC={valid['AUROC'].mean():.3f} BSS={valid['BSS'].mean():.3f}")

    # Fit final model on full extended history (monthly)
    print("\nFitting final model on full history...")
    X = df[FEATURES].ffill().fillna(0).values
    y = df["usrec"].astype(int).values

    scaler = StandardScaler()
    X_s    = scaler.fit_transform(X)

    n_pos = y.sum()
    n_neg = len(y) - n_pos
    w     = n_neg / max(n_pos, 1)

    lgbm = LGBMClassifier(
        n_estimators=500, learning_rate=0.03, max_depth=4,
        num_leaves=15, min_child_samples=5,
        scale_pos_weight=w, random_state=42, verbose=-1,
    )
    model = CalibratedClassifierCV(lgbm, cv=5, method="isotonic")
    model.fit(X_s, y)

    # Store feature importances for chart endpoint
    base_lgbm = model.calibrated_classifiers_[0].estimator
    importances = dict(zip(FEATURES, base_lgbm.feature_importances_))

    PKL_PATH.parent.mkdir(exist_ok=True)
    with open(PKL_PATH, "wb") as f:
        pickle.dump({
            "model": model, "scaler": scaler, "features": FEATURES,
            "importances": importances,
            "cv_results": cv_results if cv_results else [],
            "training_start": str(df["date"].min().date()),
            "n_recession_months": int(y.sum()),
            "n_total_months": len(y),
        }, f)
    print(f"Model saved -> {PKL_PATH}")
    print(f"  Feature importances: {sorted(importances.items(), key=lambda x: -x[1])[:5]}")

    # Write predictions for all extended-history monthly rows
    probs = model.predict_proba(X_s)[:, 1]
    df    = df.copy()
    df["recession_prob"] = probs
    df["recession_pred"] = probs > 0.5

    _write_predictions(df)

    # Also score current daily_features rows (for dashboard/decision endpoints)
    print("\nScoring current daily_features rows...")
    df_daily = load_data()
    X_d = df_daily[FEATURES].ffill().fillna(0).values
    X_d_s = scaler.transform(X_d)
    probs_d = model.predict_proba(X_d_s)[:, 1]
    df_daily = df_daily.copy()
    df_daily["recession_prob"] = probs_d
    df_daily["recession_pred"] = probs_d > 0.5
    _write_predictions(df_daily)


def _write_predictions(df: pd.DataFrame):
    version = f"recession_lgbm_{date.today().isoformat()}"
    con = get_connection()
    con.execute(f"DELETE FROM recession_predictions WHERE model_version = '{version}'")

    for _, row in df.iterrows():
        con.execute(f"""
            INSERT INTO recession_predictions
                (date, model_version, recession_prob, recession_pred)
            VALUES ({PH}, {PH}, {PH}, {PH})
            ON CONFLICT (date, model_version) DO UPDATE SET
                recession_prob = excluded.recession_prob,
                recession_pred = excluded.recession_pred
        """, [row["date"].date() if hasattr(row["date"], "date") else row["date"],
              version, float(row["recession_prob"]), bool(row["recession_pred"])])

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
    X = df[features].ffill().fillna(0).values
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
