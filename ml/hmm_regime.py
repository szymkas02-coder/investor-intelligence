"""
ml/hmm_regime.py — 3-state Hidden Markov Model regime detector

Trained on Shiller monthly data (1871-2026, ~1,800 observations).
No label circularity — unsupervised learning discovers latent states.

States: Bull / Bear / Consolidation (confirmed by BIC vs 2 and 4 states)

Key design decisions:
- Train on pre-2000 data, forward-filter only for 2000+ (no look-ahead bias)
- GaussianHMM with full covariance (hmmlearn)
- States labelled post-hoc by mean return (Bull = highest, Bear = most negative)
- Probabilities stored in hmm_predictions table (separate from regime_predictions)

Usage:
    python ml/hmm_regime.py train    # fit model, save pkl, write predictions
    python ml/hmm_regime.py predict  # load pkl, write latest prediction only
"""

import argparse
import os
import pickle
import sys
import warnings
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).parent.parent))
from db.init_db import get_connection  # noqa: E402

warnings.filterwarnings("ignore")

ROOT     = Path(__file__).parent.parent
PKL_PATH = ROOT / "models" / "hmm_regime.pkl"
SHILLER  = ROOT / "shiller.csv"

TRAIN_CUTOFF = "2000-01-01"
N_STATES     = 3
N_ITER       = 2000
RANDOM_STATE = 42


# ─── Feature engineering from Shiller CSV ────────────────────────────────────

def load_shiller_features() -> pd.DataFrame:
    df = pd.read_csv(SHILLER, parse_dates=["Date"])
    df = df.rename(columns={
        "Date":                    "date",
        "SP500":                   "sp500",
        "Consumer Price Index":    "cpi",
        "Long Interest Rate":      "long_rate",
        "Earnings":                "earnings",
        "PE10":                    "cape",
    })
    df = df[["date", "sp500", "cpi", "long_rate", "earnings", "cape"]].copy()
    df = df[df["sp500"] > 0].copy()
    df = df.sort_values("date").reset_index(drop=True)

    # Log monthly return (stationary, symmetric)
    df["sp500_log_ret"] = np.log(df["sp500"] / df["sp500"].shift(1))

    # 12-month rolling volatility (regime-dependent persistence)
    df["vol_12m"] = df["sp500_log_ret"].rolling(12).std()

    # CPI month-on-month change (inflation momentum)
    df["cpi_mom"] = df["cpi"].pct_change()

    # Earnings yield = 1/CAPE (when CAPE > 0)
    df["earnings_yield"] = np.where(df["cape"] > 0, 1.0 / df["cape"], np.nan)

    # Excess CAPE yield = earnings_yield - real long rate
    # (equity vs bond attractiveness)
    df["real_long_rate"] = df["long_rate"] - df["cpi"].pct_change(12) * 100
    df["excess_cape_yield"] = df["earnings_yield"] - df["real_long_rate"] / 100

    df = df.dropna(subset=["sp500_log_ret", "vol_12m", "cpi_mom",
                            "earnings_yield", "excess_cape_yield", "long_rate"])
    return df


FEATURE_COLS = [
    "sp500_log_ret", "vol_12m", "cape",
    "excess_cape_yield", "cpi_mom", "long_rate",
]


# ─── BIC model selection ─────────────────────────────────────────────────────

def bic(model, X):
    log_likelihood = model.score(X) * len(X)
    n_params = (model.n_components ** 2 - model.n_components +   # transition
                model.n_components * X.shape[1] +                # means
                model.n_components * X.shape[1] ** 2)            # covariance
    return -2 * log_likelihood + n_params * np.log(len(X))


def fit_with_bic(X_train: np.ndarray, n_range=(2, 3, 4)) -> GaussianHMM:
    best_bic, best_model = np.inf, None
    for n in n_range:
        m = GaussianHMM(n_components=n, covariance_type="full",
                        n_iter=N_ITER, random_state=RANDOM_STATE)
        m.fit(X_train)
        b = bic(m, X_train)
        print(f"  n_states={n}: BIC={b:.1f}, log-likelihood={m.score(X_train):.4f}")
        if b < best_bic:
            best_bic, best_model = b, m
    print(f"  -> Selected n_states={best_model.n_components} (BIC={best_bic:.1f})")
    return best_model


# ─── State labelling ─────────────────────────────────────────────────────────

def label_states(model: GaussianHMM, feature_cols: list) -> dict[int, str]:
    """Map integer state → Bull/Bear/Consolidation by mean return."""
    ret_idx = feature_cols.index("sp500_log_ret")
    means   = model.means_[:, ret_idx]
    order   = np.argsort(means)[::-1]   # highest return first
    labels  = {}
    names   = {0: "bull", 1: "consolidation", 2: "bear"}
    if model.n_components == 2:
        names = {0: "bull", 1: "bear"}
    elif model.n_components == 4:
        names = {0: "bull", 1: "consolidation", 2: "stagflation", 3: "bear"}
    for rank, state in enumerate(order):
        labels[state] = names.get(rank, f"state_{rank}")
    return labels


# ─── Training ────────────────────────────────────────────────────────────────

def train():
    print("Loading Shiller data...")
    df = load_shiller_features()
    print(f"  {len(df)} monthly rows, {df['date'].min().date()} – {df['date'].max().date()}")

    X_all    = df[FEATURE_COLS].values
    scaler   = StandardScaler()
    X_scaled = scaler.fit_transform(X_all)

    train_mask = df["date"] < TRAIN_CUTOFF
    X_train    = X_scaled[train_mask]
    print(f"  Training on pre-2000: {train_mask.sum()} rows")

    print(f"\nFitting HMM (BIC selection over n_states=2,3,4)...")
    model = fit_with_bic(X_train)

    state_labels = label_states(model, FEATURE_COLS)
    print(f"  State labels: {state_labels}")

    # Forward-filter full history (no backward smoothing = no look-ahead)
    state_probs = model.predict_proba(X_scaled)   # (n, n_states)
    state_pred  = model.predict(X_scaled)          # Viterbi path

    df = df.copy()
    df["state_pred"]  = state_pred
    df["state_label"] = [state_labels[s] for s in state_pred]
    for i in range(model.n_components):
        df[f"prob_state_{i}"] = state_probs[:, i]

    # Save artifacts
    PKL_PATH.parent.mkdir(exist_ok=True)
    with open(PKL_PATH, "wb") as f:
        pickle.dump({"model": model, "scaler": scaler,
                     "state_labels": state_labels,
                     "feature_cols": FEATURE_COLS}, f)
    print(f"\nModel saved -> {PKL_PATH}")

    # Write to DB
    _write_predictions(df, model, state_labels)
    print("Predictions written to hmm_predictions.")


def _write_predictions(df: pd.DataFrame, model: GaussianHMM,
                       state_labels: dict[int, str]):
    version = f"hmm_{model.n_components}state_{date.today().isoformat()}"
    con = get_connection()

    con.execute(f"DELETE FROM hmm_predictions WHERE model_version = '{version}'")

    n = model.n_components
    bull_idx  = next((k for k, v in state_labels.items() if v == "bull"),  0)
    bear_idx  = next((k for k, v in state_labels.items() if v == "bear"),  1)
    cons_idx  = next((k for k, v in state_labels.items() if v in ("consolidation", "stagflation")), 2)

    for _, row in df.iterrows():
        p_bull = float(row.get(f"prob_state_{bull_idx}", 0))
        p_bear = float(row.get(f"prob_state_{bear_idx}", 0))
        p_cons = float(row.get(f"prob_state_{cons_idx}", 0))
        con.execute("""
            INSERT INTO hmm_predictions
                (date, model_version, state_pred, state_label,
                 prob_bull, prob_bear, prob_consolidation)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (date, model_version) DO UPDATE SET
                state_pred = excluded.state_pred,
                state_label = excluded.state_label,
                prob_bull = excluded.prob_bull,
                prob_bear = excluded.prob_bear,
                prob_consolidation = excluded.prob_consolidation
        """, [row["date"].date() if hasattr(row["date"], "date") else row["date"],
              version, int(row["state_pred"]), row["state_label"],
              p_bull, p_bear, p_cons])

    con.commit()
    con.close()

    # Print regime distribution
    print(f"\nRegime distribution (model_version={version}):")
    counts = df["state_label"].value_counts()
    for label, cnt in counts.items():
        print(f"  {label:20s}: {cnt:4d} ({cnt/len(df)*100:.1f}%)")


# ─── Predict (load saved model, write latest) ─────────────────────────────────

def predict():
    if not PKL_PATH.exists():
        print("No trained model found. Run: python ml/hmm_regime.py train")
        sys.exit(1)

    with open(PKL_PATH, "rb") as f:
        artefacts = pickle.load(f)

    model        = artefacts["model"]
    scaler       = artefacts["scaler"]
    state_labels = artefacts["state_labels"]

    df       = load_shiller_features()
    X_scaled = scaler.transform(df[FEATURE_COLS].values)
    state_probs = model.predict_proba(X_scaled)
    state_pred  = model.predict(X_scaled)

    df = df.copy()
    df["state_pred"]  = state_pred
    df["state_label"] = [state_labels[s] for s in state_pred]
    for i in range(model.n_components):
        df[f"prob_state_{i}"] = state_probs[:, i]

    _write_predictions(df, model, state_labels)
    latest = df.iloc[-1]
    print(f"Latest ({latest['date'].date()}): {latest['state_label']} "
          f"(bull={latest.get('prob_state_0', 0):.2f})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["train", "predict"])
    args = parser.parse_args()
    if args.command == "train":
        train()
    else:
        predict()
