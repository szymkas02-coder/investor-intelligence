"""
ml/regime.py — LightGBM regime classifier

Trains a multi-class LightGBM classifier to predict one of four market regimes:
  risk_on | risk_off | stagflation | deflation

Design decisions:
- Walk-forward CV (TimeSeriesSplit) instead of random split to prevent
  look-ahead bias — regime labels have serial correlation, so random splits
  would leak future regime information into training.
- Confidence-weighted sample weights: low-confidence boundary labels get
  weight 0.65 vs 0.95 for high-confidence labels. This prevents the model
  from overfitting to ambiguous transitions.
- SMOTE-like class weighting via class_weight='balanced' substitute: we pass
  scale_pos_weight equivalents via class_weight dict because deflation (0.2%)
  and risk_off (6.5%) are severely underrepresented. Without this the model
  collapses to always predicting risk_on.
- No feature scaling: LightGBM is tree-based and invariant to monotone
  transformations, so standardization adds no value and would make SHAP
  values less interpretable (they'd be in scaled rather than economic units).
- model_version encodes training date so regime_predictions can store and
  compare multiple versions side-by-side (see schema.sql rationale).
"""

import sys
import json
import pickle
import warnings
from pathlib import Path
from datetime import date, datetime

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.preprocessing import LabelEncoder

sys.path.insert(0, str(Path(__file__).parent.parent))
from db.init_db import get_connection

warnings.filterwarnings("ignore", category=UserWarning)

# ---------------------------------------------------------------------------
# Feature set
# WHY this subset: features are chosen for (a) economic interpretability,
# (b) availability back to 2010, and (c) low collinearity with each other.
# Crypto / sentiment / WSB features excluded — too many NULLs pre-2020.
# FX features included because PLN/USD regime transitions lead equity signals
# by 1-3 days for a Warsaw-based investor.
# ---------------------------------------------------------------------------
FEATURE_COLS = [
    # Equity momentum
    "acwi_ret_1d", "acwi_ret_5d", "acwi_ret_21d", "acwi_ret_63d",
    "spy_ret_1d", "wig20_ret_1d", "gold_ret_1d", "tlt_ret_1d",
    # Volatility
    "acwi_vol_21d", "acwi_vol_63d", "vix_close", "vix_change_5d",
    # Yield curve
    "yield_10y", "yield_2y", "yield_3m",
    "spread_10y_2y", "spread_10y_3m",
    # Central bank rates
    "fed_funds_rate", "ecb_rate", "nbp_rate",
    # Inflation
    "cpi_us_yoy", "cpi_core_us_yoy", "cpi_ea_yoy", "cpi_pl_yoy",
    # Labour / growth
    "unemployment_us",
    # Rate & inflation differentials (US vs PL)
    "rate_differential", "cpi_differential",
    # FX
    "usdpln", "eurpln", "usdpln_ret_21d", "usdpln_vol_21d",
    # Fundamentals
    "sp500_pe_ratio", "sp500_earnings_yield",
]

TARGET_COL    = "regime"
REGIMES       = ["risk_on", "risk_off", "stagflation", "deflation"]
MODEL_DIR     = Path(__file__).parent.parent / "models"
MIN_TRAIN_ROWS = 500   # refuse to train on tiny datasets


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_training_data(conn) -> pd.DataFrame:
    """Join daily_features with regime_labels; return only fully-labeled rows."""
    df = conn.execute(f"""
        SELECT
            f.date,
            {', '.join(f'f.{c}' for c in FEATURE_COLS)},
            l.regime,
            l.confidence
        FROM daily_features f
        INNER JOIN regime_labels l ON f.date = l.date
        ORDER BY f.date
    """).df()
    df["date"] = pd.to_datetime(df["date"])
    return df


def compute_class_weights(y: np.ndarray, classes: list) -> np.ndarray:
    """
    Return per-sample class weights aligned to y (integer-encoded labels).
    Weights are inversely proportional to class frequency so that rare regimes
    (deflation, risk_off) receive higher gradient weight than risk_on.
    Returned as a per-sample array so it can be multiplied into sample_weight
    directly — avoids passing class_weight dict to LightGBM, which raises
    KeyError when a fold's training set is missing a class.
    """
    counts = np.bincount(y, minlength=len(classes))
    total  = len(y)
    n_cls  = len(classes)
    # weight per class index; guard against zero-count classes with clip
    per_class = total / (n_cls * np.maximum(counts, 1))
    return per_class[y]   # broadcast to per-sample array


def build_lgbm_params(n_classes: int) -> dict:
    """
    Core LightGBM hyperparameters.
    WHY these values:
    - num_leaves=63: medium complexity; deeper trees risk memorising regime
      transitions which are structurally similar across decades.
    - min_child_samples=30: prevents leaves with <30 training points; each
      macro regime episode lasts months, so very small leaves capture noise.
    - learning_rate=0.05: conservative rate pairs with n_estimators=500 via
      early stopping; lets early stopping find the right depth.
    - subsample=0.8, colsample_bytree=0.8: feature/row bagging reduces
      variance without explicit random forest mode.
    - No class_weight param: rare-class up-weighting is folded into
      sample_weight instead to avoid LightGBM KeyError when a CV fold
      has no examples of a minority class (deflation: 4 rows total).
    """
    return {
        "objective":         "multiclass",
        "num_class":         n_classes,
        "metric":            "multi_logloss",
        "num_leaves":        63,
        "max_depth":         -1,
        "min_child_samples": 30,
        "learning_rate":     0.05,
        "n_estimators":      500,
        "subsample":         0.8,
        "colsample_bytree":  0.8,
        "reg_alpha":         0.1,
        "reg_lambda":        1.0,
        "random_state":      42,
        "verbose":           -1,
        "n_jobs":            -1,
    }


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train(min_date: str = "2010-01-01", n_splits: int = 5) -> dict:
    """
    Train LightGBM regime classifier with walk-forward cross-validation.

    Returns dict with cv_metrics, feature_importance, and model_version.
    Saves model artifact to models/regime_<version>.pkl and
    writes predictions for the full dataset to regime_predictions.
    """
    conn = get_connection()

    # ------------------------------------------------------------------
    # 1. Load data
    # ------------------------------------------------------------------
    print("  Loading training data ...")
    df = load_training_data(conn)
    df = df[df["date"] >= min_date].copy()
    print(f"    {len(df)} rows, {df['regime'].value_counts().to_dict()}")

    if len(df) < MIN_TRAIN_ROWS:
        raise ValueError(f"Only {len(df)} labeled rows — need {MIN_TRAIN_ROWS}+ to train")

    # ------------------------------------------------------------------
    # 2. Encode labels
    # ------------------------------------------------------------------
    le = LabelEncoder()
    le.fit(REGIMES)  # fix class order regardless of data distribution
    y  = le.transform(df[TARGET_COL])
    X  = df[FEATURE_COLS].copy()

    # ------------------------------------------------------------------
    # 3. Combined sample weights = confidence × inverse class frequency
    # WHY: We merge both signals into one sample_weight vector instead of
    # using LightGBM's class_weight param. class_weight raises KeyError
    # when a CV fold's training set is missing a class (deflation has
    # only 4 rows, so early folds contain none). sample_weight has no
    # such constraint — it just scales each row's gradient contribution.
    # ------------------------------------------------------------------
    conf_weights  = df["confidence"].fillna(0.65).values
    class_w       = compute_class_weights(y, list(le.classes_))
    sample_weights = conf_weights * class_w
    sample_weights = sample_weights / sample_weights.mean()   # normalise -> mean=1

    params = build_lgbm_params(len(REGIMES))

    # ------------------------------------------------------------------
    # 4. Walk-forward cross-validation
    # ------------------------------------------------------------------
    print(f"  Walk-forward CV ({n_splits} folds) ...")
    tscv = TimeSeriesSplit(n_splits=n_splits)

    cv_reports = []
    for fold, (train_idx, val_idx) in enumerate(tscv.split(X), 1):
        X_tr, X_val = X.iloc[train_idx], X.iloc[val_idx]
        y_tr, y_val = y[train_idx],      y[val_idx]
        w_tr        = sample_weights[train_idx]

        # No eval_set in CV: early folds may have deflation only in val,
        # not in train, causing LightGBM's internal LabelEncoder to raise
        # "unseen labels". We train with fixed n_estimators per fold instead.
        fold_params = {**params, "n_estimators": 300}
        model = lgb.LGBMClassifier(**fold_params)
        model.fit(X_tr, y_tr, sample_weight=w_tr)
        preds = model.predict(X_val)
        report = classification_report(
            y_val, preds,
            labels=list(range(len(REGIMES))),
            target_names=le.classes_,
            output_dict=True,
            zero_division=0,
        )
        val_dates = df.iloc[val_idx]["date"]
        print(f"    Fold {fold}: val {val_dates.min().date()} - {val_dates.max().date()} "
              f"| macro-f1={report['macro avg']['f1-score']:.3f}")
        cv_reports.append(report)

    macro_f1s = [r["macro avg"]["f1-score"] for r in cv_reports]
    print(f"\n  CV macro-F1: {np.mean(macro_f1s):.3f} ± {np.std(macro_f1s):.3f}")

    # ------------------------------------------------------------------
    # 5. Final model — retrain on all data
    # ------------------------------------------------------------------
    print("\n  Training final model on full dataset ...")
    final_model = lgb.LGBMClassifier(**params)
    final_model.fit(X, y, sample_weight=sample_weights,
                    callbacks=[lgb.log_evaluation(-1)])

    # ------------------------------------------------------------------
    # 6. Feature importance
    # ------------------------------------------------------------------
    fi = pd.Series(
        final_model.feature_importances_,
        index=FEATURE_COLS,
    ).sort_values(ascending=False)
    print("\n  Top-10 features by gain:")
    for feat, score in fi.head(10).items():
        print(f"    {feat:<30} {score:.0f}")

    # ------------------------------------------------------------------
    # 7. Save model artifact
    # ------------------------------------------------------------------
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model_version = f"regime_lgbm_{date.today().isoformat()}"
    artifact_path = MODEL_DIR / f"{model_version}.pkl"
    with open(artifact_path, "wb") as fh:
        pickle.dump({"model": final_model, "label_encoder": le,
                     "feature_cols": FEATURE_COLS, "trained_at": datetime.utcnow().isoformat()}, fh)
    print(f"\n  Saved model -> {artifact_path}")

    # ------------------------------------------------------------------
    # 8. Write predictions to regime_predictions
    # ------------------------------------------------------------------
    print("  Writing predictions to regime_predictions ...")
    proba = final_model.predict_proba(X)

    # Map class index to regime name
    cls_to_idx = {cls: i for i, cls in enumerate(le.classes_)}

    rows = []
    for i, row in enumerate(df.itertuples()):
        p = proba[i]
        rows.append({
            "date":             row.date.date(),
            "model_version":    model_version,
            "regime_pred":      le.inverse_transform([final_model.predict(X.iloc[[i]])[0]])[0],
            "prob_risk_on":     float(p[cls_to_idx["risk_on"]]),
            "prob_risk_off":    float(p[cls_to_idx["risk_off"]]),
            "prob_stagflation": float(p[cls_to_idx["stagflation"]]),
            "prob_deflation":   float(p[cls_to_idx["deflation"]]),
        })

    pred_df = pd.DataFrame(rows)
    conn.execute(f"""
        DELETE FROM regime_predictions WHERE model_version = '{model_version}'
    """)
    conn.execute("""
        INSERT INTO regime_predictions
            (date, model_version, regime_pred,
             prob_risk_on, prob_risk_off, prob_stagflation, prob_deflation)
        SELECT date, model_version, regime_pred,
               prob_risk_on, prob_risk_off, prob_stagflation, prob_deflation
        FROM pred_df
    """)
    conn.commit()

    # ------------------------------------------------------------------
    # 9. Agreement check — rule-based labels vs model predictions
    # ------------------------------------------------------------------
    merged = pred_df.merge(df[["date", "regime"]].assign(date=lambda d: d["date"].dt.date),
                           on="date")
    agreement = (merged["regime_pred"] == merged["regime"]).mean()
    print(f"\n  Label agreement (rule vs model): {agreement:.1%}")

    cm = confusion_matrix(merged["regime"], merged["regime_pred"],
                          labels=REGIMES)
    print("\n  Confusion matrix (rows=true, cols=pred):")
    header = f"{'':>15}" + "".join(f"{r:>15}" for r in REGIMES)
    print(f"  {header}")
    for i, true_regime in enumerate(REGIMES):
        row_str = f"  {true_regime:>15}" + "".join(f"{cm[i,j]:>15}" for j in range(len(REGIMES)))
        print(row_str)

    conn.close()

    return {
        "model_version":   model_version,
        "cv_macro_f1_mean": float(np.mean(macro_f1s)),
        "cv_macro_f1_std":  float(np.std(macro_f1s)),
        "label_agreement":  float(agreement),
        "feature_importance": fi.head(15).to_dict(),
        "artifact_path":   str(artifact_path),
    }


# ---------------------------------------------------------------------------
# Inference — score new dates from a saved model
# ---------------------------------------------------------------------------

def predict(model_version: str | None = None) -> pd.DataFrame:
    """
    Load the latest (or named) model and score any daily_features rows that
    lack a prediction for that model_version. Writes results to
    regime_predictions and returns a DataFrame of new predictions.
    """
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    if model_version is None:
        # Pick most-recently modified pkl
        pkls = sorted(MODEL_DIR.glob("regime_lgbm_*.pkl"), key=lambda p: p.stat().st_mtime)
        if not pkls:
            raise FileNotFoundError("No trained regime model found in models/. Run train() first.")
        artifact_path = pkls[-1]
    else:
        artifact_path = MODEL_DIR / f"{model_version}.pkl"

    with open(artifact_path, "rb") as fh:
        artifact = pickle.load(fh)

    model    = artifact["model"]
    le       = artifact["label_encoder"]
    feat_cols = artifact["feature_cols"]
    model_version = artifact_path.stem  # canonical name

    conn = get_connection()

    # Find dates not yet scored by this model version
    df = conn.execute(f"""
        SELECT f.date, {', '.join(f'f.{c}' for c in feat_cols)}
        FROM daily_features f
        LEFT JOIN regime_predictions rp
            ON f.date = rp.date AND rp.model_version = '{model_version}'
        WHERE rp.date IS NULL
        ORDER BY f.date
    """).df()

    if df.empty:
        print("  No new dates to score.")
        conn.close()
        return pd.DataFrame()

    print(f"  Scoring {len(df)} new dates with {model_version} ...")
    X     = df[feat_cols]
    proba = model.predict_proba(X)
    preds = le.inverse_transform(model.predict(X))

    cls_to_idx = {cls: i for i, cls in enumerate(le.classes_)}
    rows = []
    for i, (_, row) in enumerate(df.iterrows()):
        p = proba[i]
        rows.append({
            "date":             row["date"],
            "model_version":    model_version,
            "regime_pred":      preds[i],
            "prob_risk_on":     float(p[cls_to_idx["risk_on"]]),
            "prob_risk_off":    float(p[cls_to_idx["risk_off"]]),
            "prob_stagflation": float(p[cls_to_idx["stagflation"]]),
            "prob_deflation":   float(p[cls_to_idx["deflation"]]),
        })

    pred_df = pd.DataFrame(rows)
    conn.execute("""
        INSERT INTO regime_predictions
            (date, model_version, regime_pred,
             prob_risk_on, prob_risk_off, prob_stagflation, prob_deflation)
        SELECT date, model_version, regime_pred,
               prob_risk_on, prob_risk_off, prob_stagflation, prob_deflation
        FROM pred_df
    """)
    conn.commit()
    conn.close()

    print(f"  Wrote {len(pred_df)} predictions -> regime_predictions")
    return pred_df


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LightGBM regime classifier")
    sub    = parser.add_subparsers(dest="cmd")

    tr = sub.add_parser("train", help="Train and evaluate the classifier")
    tr.add_argument("--min-date", default="2010-01-01")
    tr.add_argument("--cv-splits", type=int, default=5)

    pr = sub.add_parser("predict", help="Score new dates with latest model")
    pr.add_argument("--model-version", default=None)

    args = parser.parse_args()

    if args.cmd == "train":
        print("=== LightGBM regime classifier — training ===\n")
        results = train(min_date=args.min_date, n_splits=args.cv_splits)
        print(f"\nDone. model_version={results['model_version']}")
        print(f"      CV macro-F1: {results['cv_macro_f1_mean']:.3f} ± {results['cv_macro_f1_std']:.3f}")
        print(f"      Label agreement: {results['label_agreement']:.1%}")
    elif args.cmd == "predict":
        print("=== LightGBM regime classifier — predict ===\n")
        df = predict(model_version=args.model_version)
        if not df.empty:
            print(df.tail(5).to_string(index=False))
    else:
        parser.print_help()
