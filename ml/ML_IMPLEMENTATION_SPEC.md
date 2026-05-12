# ML Pipeline — Implementation Specification
# (Grounded in Deep Research, May 2026)

*Based on three research documents: HMM.md, CAPE Return Forecasting.md, NBER Business Cycle Regimes.md*

---

## Architecture Overview

Three independent models, each answering a different question.
Their outputs are displayed side-by-side in the frontend — no ensemble blending yet.

| Model | File | Question answered | Horizon | Ground truth |
|-------|------|-------------------|---------|--------------|
| LightGBM regime | `ml/regime.py` | What regime are we in today? | Daily | Rule-based labels (known circular — retained as baseline) |
| HMM regime | `ml/hmm_regime.py` | What latent market state are we in? | Monthly | Unsupervised — no labels needed |
| NBER recession | `ml/recession.py` | Is the US in recession? | Monthly | FRED USREC — external, non-circular |
| CAPE signal | `ml/cape_signal.py` | What is the 10Y expected return? | 10-year | Historical realized returns (Shiller 1871-2026) |

---

## Model 1 — Hidden Markov Model (ml/hmm_regime.py)

### Key decisions from literature

**Number of states: 3**
- 2 states (Hamilton 1989): too coarse for IKE monthly decisions
- 4 states (Guidolin & Timmermann 2007): requires larger dataset and careful regularization to avoid "regime flickering" — unstable with only 1,800 monthly observations
- 3 states (recommended in recent literature for retail applications): Bull / Bear / Consolidation. The "Consolidation" state prevents whipsaw exits during high-vol sideways markets — directly relevant for an IKE investor
- Use BIC to confirm 3 vs 2 vs 4 at runtime

**Model type: GaussianHMM (hmmlearn)**
- GMMHMM (mixture emissions) would be better for fat tails but needs more data
- MS-VAR (statsmodels) is gold standard for multi-asset but overkill for this use case
- GaussianHMM via `hmmlearn`: simple API, stable on monthly data, well-tested Baum-Welch

**Critical — no look-ahead bias:**
- Use **Hamilton Filter only** (forward pass) for any signal used in backtesting or the app
- The Kim Smoother (backward pass over full history) gives "perfect hindsight" — use only for sanity checking that identified regimes match known historical events
- Walk-forward retraining: fit on all data up to month T, predict state for month T+1 only

**State selection: BIC**
- BIC preferred over AIC for HMM because AIC's weaker complexity penalty selects too many states and causes "regime flickering" (state jumping too fast to be useful for monthly investing)

### Features (from shiller.csv, monthly)

```python
FEATURES = [
    "sp500_log_ret",        # log(P_t / P_{t-1}) — stationary, symmetric
    "vol_12m",              # rolling 12M std of log returns — persistent, regime-dependent
    "cape",                 # PE10 — high in late Bull, low in Recovery
    "excess_cape_yield",    # (1/CAPE) - real_10y_rate — equity vs bond attractiveness
    "cpi_mom",              # month-on-month CPI change — inflation momentum
    "long_rate",            # 10Y Treasury — discount rate proxy
]
```

Why these: all available back to 1871 in shiller.csv; each exhibits distinct statistical signatures
across Bull/Bear/Consolidation states; low collinearity between groups.

### Implementation sketch

```python
from hmmlearn.hmm import GaussianHMM
import numpy as np

# Train on pre-2000 data (in-sample); forward-filter for 2000+
model = GaussianHMM(
    n_components=3,           # confirmed by BIC
    covariance_type="full",   # allows non-spherical state distributions
    n_iter=1000,
    random_state=42
)
model.fit(X_train)            # X_train: shape (n_months, n_features)

# Forward-filter only — no backward smoothing (no look-ahead)
# hmmlearn's predict() uses Viterbi — acceptable for monthly frequency
# For probability output use predict_proba() (forward algorithm)
state_probs = model.predict_proba(X_test)  # shape (n_months, 3)
```

### State labeling

HMM states are unlabeled integers. After fitting, assign labels by inspecting:
- Mean return per state → highest = Bull, most negative = Bear, near-zero = Consolidation
- Mean volatility per state → confirms assignment

### Output to DB

Writes to `regime_predictions` with `model_version = "hmm_3state_<date>"`.
Probabilities stored as `prob_risk_on` (Bull), `prob_risk_off` (Bear), `prob_stagflation` (Consolidation), `prob_deflation = NULL`.

---

## Model 2 — NBER Recession Classifier (ml/recession.py)

### Key decisions from literature

**Ground truth: FRED USREC series**
- Monthly binary: 1 = recession, 0 = expansion
- Published by NBER Business Cycle Dating Committee — external, not derived from our features
- **Critical problem: publication lag of 6-12 months** (e.g., Dec 2007 recession announced Dec 2008)
- For training: use the full historical USREC series (lag doesn't affect historical labels, only real-time use)
- For real-time: the model predicts recession probability; if USREC hasn't been announced yet, model output IS the signal

**Class imbalance: ~15% recession months since 1945**
- Do NOT use SMOTE — it disrupts temporal ordering and miscalibrates probabilities
- Use **class weighting** (cost-sensitive learning) — preferred by literature for time-series imbalance
- After training: apply **Platt scaling** (isotonic regression) to calibrate probabilities

**Model: LightGBM with class weighting**
- XGBoost/LightGBM consistently outperforms logistic regression in published recession forecasting studies (AUC 0.98 vs 0.65 for Probit at nowcast horizon — Bianchi et al. 2024)
- Random Forest also strong; use LightGBM for consistency with existing codebase

**Validation: Walk-forward with SLIDING window**
- Expanding window (1945 to present) risks anchoring to outdated relationships (e.g., yield curve predictive power weakened during QE periods)
- Sliding 20-year window adapts to structural shifts in yield curve / macro dynamics

**Primary features (all already in daily_features):**
```python
RECESSION_FEATURES = [
    "spread_10y_3m",     # Estrella & Mishkin (1998) — single best predictor, 8-12M lead
    "spread_10y_2y",     # complementary yield curve signal
    "vix_close",         # short-term fear — 1-6M lead (Liu & Moench 2016)
    "acwi_ret_63d",      # 3M equity momentum — short-term leading indicator
    "unemployment_us",   # Sahm Rule basis: 3M MA unemployment minus 12M low > 0.5 = recession
    "fed_funds_rate",    # monetary tightening signal
    "cpi_us_yoy",        # inflation pressure on Fed
    "usdpln_vol_21d",    # PLN volatility = global risk-off proxy (EM "canary in coal mine")
]
```

**Evaluation metrics (NOT accuracy):**
- AUPRC (precision-recall) — better than AUROC for imbalanced data
- Brier Skill Score (BSS) — measures calibration of probability forecasts
- Matthews Correlation Coefficient (MCC)

### Output

Separate column in frontend: `recession_probability` (0-1, calibrated).
Stored in a new `recession_predictions` table or as additional columns in `regime_predictions`.

---

## Model 3 — CAPE Valuation Signal (ml/cape_signal.py)

### Key decisions from literature

**This model answers a different question** than the regime classifier:
- Not "what regime are we in today?" (tactical, months)
- But "what 10Y real return should I expect from this entry point?" (strategic, years)

**Core finding (Campbell & Shiller 1988, 1998):**
- CAPE explains ~30-40% of variance in 10Y forward real returns (OOS R² up to 56% with Component-CAPE alignment, Li et al. 2025)
- High CAPE → low future returns. Historically at CAPE ~33 (current): median 10Y real return ~2%
- The relationship is ordinal and robust even when the absolute level is disputed (Asness 2012)

**Known problems and mitigations:**

| Problem | Mitigation |
|---------|-----------|
| GAAP write-down bias (Siegel 2013) | Use Shiller's PE10 as-is — NIPA earnings not available in shiller.csv |
| Structural break: CAPE above historical mean since 1985 | Do NOT assume mean-reversion to 16.5; condition on real interest rate |
| US survivorship bias | Note in UI: ACWI ≠ S&P 500; use as directional signal only |
| Buyback era distortion | Use Total Return CAPE if data available; otherwise PE10 as-is |

**Model: Quantile regression (sklearn QuantileRegressor)**
- Better than OLS because it estimates the distribution of outcomes, not just the mean
- Key output: 10th / 50th / 90th percentile of 10Y forward real return given today's CAPE
- This gives the user "expected range" not a single number — more honest and actionable
- Expanding window (all data since 1871) — long history is the point of CAPE

**Features:**
```python
CAPE_FEATURES = [
    "cape",              # PE10 — primary signal
    "real_long_rate",    # long_rate - 10Y avg CPI — adjusts for interest rate regime
                         # This is the Excess CAPE Yield denominator
]
```

**Target:** SP500 10Y forward real return (computable from shiller.csv for 1871-2016, ~145 years of training data)

**Output to app:**
- Not stored in `regime_predictions` — separate `cape_forecasts` table or just computed on-demand
- Displayed as: "At current CAPE of X, historical 10Y real return: 10th pct = A%, median = B%, 90th pct = C%"
- Decile bucketing per Asness (2012): show which CAPE decile we're in and the historical return distribution for that decile

---

## Implementation Priority

Given the decision to finish the baseline app first, implement in this order:

1. **Now**: Prompts 17-20 (volatility forecaster, FX model, SHAP, backtest) → finish baseline
2. **Phase 5b-1**: `ml/hmm_regime.py` — highest ROI, uses shiller.csv already in repo, no label circularity
3. **Phase 5b-2**: `ml/cape_signal.py` — low effort, shiller.csv already available, answers strategic question
4. **Phase 5b-3**: `ml/recession.py` — requires FRED USREC ingestion (minor addition to existing FRED module)

---

## Frontend Display (future)

Instead of one regime label, show a "signal panel":

```
Current Market Signals (as of 2026-05-06)
------------------------------------------
LightGBM regime:    risk_on (72%)       [note: rule-based labels]
HMM regime:         Bull (68%)
Recession risk:     12% probability
CAPE 10Y outlook:   2.1% median real return [CAPE=33, 9th decile]

Signal agreement: MODERATE (3/4 signals positive)
```

This is honest (shows disagreement), actionable (four different dimensions), and demonstrably non-trivial to build.
