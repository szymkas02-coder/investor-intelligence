"""
ml/correlation_pca.py — Rolling PCA correlation structure across market regimes

Computes a rolling 63-day correlation matrix of key assets and applies PCA.
Stores regime-conditional snapshots to correlation_stats and diversification_index.

Physics analogy: identical to EOF (Empirical Orthogonal Function) analysis in
atmospheric science. PC1 is the "market beta" mode — the fraction of total
variance it explains measures how synchronised all assets are.
  - Risk-off regimes: correlations spike, PC1 → high, diversification collapses
  - Risk-on regimes: PC1 is smaller, each asset follows its own dynamics

Diversification index = 1 - PC1_explained_variance
Higher = better diversification (typical risk-on: ~0.4, risk-off crisis: ~0.1)

Usage:
    python ml/correlation_pca.py compute   # compute and write to DB
    python ml/correlation_pca.py snapshot  # print latest snapshot as JSON
"""

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).parent.parent))
from db.init_db import get_connection, PH

warnings.filterwarnings("ignore")

WINDOW_DAYS = 63   # 3-month rolling window

RETURN_COLS = [
    "acwi_ret_1d",
    "gold_ret_1d",
    "tlt_ret_1d",
    "usdpln_ret_21d",
    "vix_change_5d",
]

_ASSET_LABELS = {
    "acwi_ret_1d":    "ACWI",
    "gold_ret_1d":    "GOLD",
    "tlt_ret_1d":     "BONDS",
    "usdpln_ret_21d": "USD",
    "vix_change_5d":  "VIX",
}

# All pairs (10 for 5 assets) — needed so /ml/pca/current-heatmap can render
# a complete matrix instead of one row.
PAIR_MAP = {}
for i, a in enumerate(RETURN_COLS):
    for b in RETURN_COLS[i + 1:]:
        PAIR_MAP[(a, b)] = f"{_ASSET_LABELS[a]}-{_ASSET_LABELS[b]}"


def load_daily_returns(conn) -> pd.DataFrame:
    cols = ", ".join(RETURN_COLS)
    try:
        rows = conn.execute(f"""
            SELECT date, {cols}
            FROM daily_features
            WHERE acwi_ret_1d IS NOT NULL
            ORDER BY date
        """).fetchall()
        df = pd.DataFrame(rows, columns=["date"] + RETURN_COLS)
    except Exception:
        df = conn.execute(f"""
            SELECT date, {cols}
            FROM daily_features
            WHERE acwi_ret_1d IS NOT NULL
            ORDER BY date
        """).df()

    df["date"] = pd.to_datetime(df["date"])
    return df


def load_hmm_labels(conn) -> pd.DataFrame:
    try:
        rows = conn.execute("""
            SELECT date, state_label FROM hmm_predictions ORDER BY date
        """).fetchall()
        df = pd.DataFrame(rows, columns=["date", "state_label"])
    except Exception:
        df = conn.execute("""
            SELECT date, state_label FROM hmm_predictions ORDER BY date
        """).df()

    df["date"] = pd.to_datetime(df["date"])
    return df


def compute_rolling_pca(returns_df: pd.DataFrame) -> pd.DataFrame:
    """
    For each date t, compute rolling 63d correlation PCA and pairwise correlations.
    Returns DataFrame with date, div_index, pc1_explained, plus key pair correlations.
    """
    n = len(returns_df)
    results = []
    skipped = 0

    for i in range(WINDOW_DAYS, n):
        window = returns_df.iloc[i - WINDOW_DAYS: i][RETURN_COLS].dropna()
        if len(window) < WINDOW_DAYS // 2:
            skipped += 1
            continue

        date_t = returns_df.iloc[i]["date"]

        X = StandardScaler().fit_transform(window)
        n_components = min(len(RETURN_COLS), len(window))
        pca = PCA(n_components=n_components)
        pca.fit(X)
        pc1_var = float(pca.explained_variance_ratio_[0])
        div_idx = round(1.0 - pc1_var, 4)

        corr_matrix = window.corr()
        row = {
            "date":          date_t,
            "div_index":     div_idx,
            "pc1_explained": round(pc1_var, 4),
            "n_assets":      len(RETURN_COLS),
        }
        for (c1, c2), pair_name in PAIR_MAP.items():
            row[pair_name] = round(float(corr_matrix.loc[c1, c2]), 3) if c1 in corr_matrix and c2 in corr_matrix else None

        results.append(row)

    if skipped > 0:
        print(f"  Skipped {skipped} windows (too many NaNs)")

    return pd.DataFrame(results)


def write_results(conn, pca_df: pd.DataFrame, hmm_df: pd.DataFrame) -> None:
    # Merge with HMM labels — use nearest preceding HMM date (monthly data)
    hmm_df = hmm_df.sort_values("date")
    pca_df = pca_df.sort_values("date")
    merged = pd.merge_asof(pca_df, hmm_df, on="date", direction="backward")
    merged["regime"] = merged["state_label"].fillna("unknown")

    pair_cols = list(PAIR_MAP.values())

    # Write diversification index
    conn.execute("DELETE FROM diversification_index")
    for _, row in merged.iterrows():
        conn.execute(
            f"""
            INSERT INTO diversification_index
                (computed_date, regime, div_index, pc1_explained, n_assets)
            VALUES ({PH},{PH},{PH},{PH},{PH})
            ON CONFLICT (computed_date) DO UPDATE SET
                regime        = EXCLUDED.regime,
                div_index     = EXCLUDED.div_index,
                pc1_explained = EXCLUDED.pc1_explained
            """,
            [row["date"].date(), row["regime"],
             row["div_index"], row["pc1_explained"], int(row["n_assets"])],
        )

    # Write pairwise correlations
    conn.execute(f"DELETE FROM correlation_stats WHERE window_days = {WINDOW_DAYS}")
    for _, row in merged.iterrows():
        for pair in pair_cols:
            if pair in row and row[pair] is not None and not (isinstance(row[pair], float) and np.isnan(row[pair])):
                conn.execute(
                    f"""
                    INSERT INTO correlation_stats
                        (computed_date, regime, asset_pair, window_days, correlation)
                    VALUES ({PH},{PH},{PH},{PH},{PH})
                    ON CONFLICT (computed_date, asset_pair, window_days) DO UPDATE SET
                        correlation = EXCLUDED.correlation,
                        regime      = EXCLUDED.regime
                    """,
                    [row["date"].date(), row["regime"], pair, WINDOW_DAYS, float(row[pair])],
                )

    conn.commit()
    print(f"  Wrote {len(merged)} diversification_index rows")
    print(f"  Wrote pairwise correlations for {len(pair_cols)} pairs")


def get_current_snapshot(conn) -> dict:
    """Returns the latest correlation snapshot for the API."""
    div_row = conn.execute("""
        SELECT computed_date, regime, div_index, pc1_explained
        FROM diversification_index
        ORDER BY computed_date DESC
        LIMIT 1
    """).fetchone()

    if not div_row:
        return {}

    latest_date = str(div_row[0])
    corr_rows = conn.execute(f"""
        SELECT asset_pair, correlation
        FROM correlation_stats
        WHERE computed_date = '{latest_date}'
          AND window_days = {WINDOW_DAYS}
        ORDER BY asset_pair
    """).fetchall()

    return {
        "computed_date":          latest_date,
        "regime":                 div_row[1],
        "diversification_index":  round(float(div_row[2]), 3) if div_row[2] is not None else None,
        "pc1_explained":          round(float(div_row[3]), 3) if div_row[3] is not None else None,
        "top_correlations": [
            {"pair": r[0], "r": round(float(r[1]), 3)}
            for r in corr_rows
            if r[1] is not None
        ],
    }


def compute() -> dict:
    """Main entry point — load returns, compute rolling PCA, write to DB."""
    conn = get_connection()
    print("Loading daily returns...")
    returns_df = load_daily_returns(conn)
    print(f"  {len(returns_df)} rows")

    if len(returns_df) < WINDOW_DAYS + 10:
        print(f"  Not enough data (need >{WINDOW_DAYS} rows) — skipping")
        conn.close()
        return {"pca_rows": 0, "current_snapshot": {}}

    print("Loading HMM labels...")
    hmm_df = load_hmm_labels(conn)
    print(f"  {len(hmm_df)} HMM rows")

    print(f"Computing rolling PCA (window={WINDOW_DAYS}d)...")
    pca_df = compute_rolling_pca(returns_df)
    print(f"  {len(pca_df)} PCA rows computed")

    write_results(conn, pca_df, hmm_df)
    snapshot = get_current_snapshot(conn)
    conn.close()

    return {"pca_rows": len(pca_df), "current_snapshot": snapshot}


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["compute", "snapshot"])
    args = parser.parse_args()

    if args.command == "compute":
        result = compute()
        print(f"\nDone. PCA rows: {result['pca_rows']}")
        snap = result["current_snapshot"]
        if snap:
            print(f"Current: regime={snap.get('regime')}, "
                  f"div_index={snap.get('diversification_index')} "
                  f"(pc1={snap.get('pc1_explained')})")
    elif args.command == "snapshot":
        conn = get_connection()
        print(json.dumps(get_current_snapshot(conn), indent=2))
        conn.close()
