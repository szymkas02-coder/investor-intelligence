"""
ml/regime_duration.py — Kaplan-Meier survival analysis for market regime duration

Treats each HMM regime episode as a "survival" problem — identical mathematics to
radioactive decay half-lives or particle lifetime distributions in physics. Each
contiguous run of the same HMM state is one "particle". We observe when it "decays"
(transitions to a different regime). Kaplan-Meier gives S(t) = P(episode still
ongoing at month t).

Uses hmm_predictions (monthly, 1880–present, unsupervised) as the episode source —
not rule-based regime_labels. This ensures the KM lookup uses the same state names
(bull / bear / consolidation) as the current regime reported on the dashboard.

HMM data goes back to 1880 (145 years of Shiller data) giving ~1,745 monthly
observations and meaningful episode counts for all three states.

Output: regime_duration_stats table with per-regime KM survival estimates.
        get_current_regime_status() queries hmm_predictions to find current
        regime age and looks up the corresponding KM survival probability.

Usage:
    python ml/regime_duration.py compute   # compute and write KM estimates
    python ml/regime_duration.py status    # show current regime age + survival prob
"""

import sys
import warnings
import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from db.init_db import get_connection

warnings.filterwarnings("ignore")


def load_regime_episodes(conn) -> pd.DataFrame:
    """
    Convert HMM monthly predictions into regime episodes.
    Uses hmm_predictions (1880–present, ~1745 rows) so episode state names match
    the dashboard regime display (bull / bear / consolidation).
    An episode = contiguous run of the same HMM state label.
    Returns DataFrame: regime, start_date, end_date, duration_months, observed.
    observed=False means the episode was censored (still ongoing at last date).
    """
    # Use only the most recent model version to avoid mixing old+new predictions
    try:
        latest_version = conn.execute(
            "SELECT model_version FROM hmm_predictions ORDER BY predicted_at DESC LIMIT 1"
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT date, state_label FROM hmm_predictions WHERE model_version = %s ORDER BY date",
            [latest_version]
        ).fetchall()
        df = pd.DataFrame(rows, columns=["date", "regime"])
    except Exception:
        df = conn.execute(
            "SELECT date, state_label AS regime FROM hmm_predictions ORDER BY date"
        ).df()

    if df.empty:
        return pd.DataFrame(columns=["regime", "start_date", "end_date", "duration_months", "observed"])

    df["date"] = pd.to_datetime(df["date"])
    # Keep all 4 HMM states as-is: bull, bear, consolidation, stagflation
    df["episode_id"] = (df["regime"] != df["regime"].shift()).cumsum()

    episodes = (
        df.groupby("episode_id")
          .agg(regime=("regime", "first"),
               start_date=("date", "min"),
               end_date=("date", "max"),
               duration_months=("regime", "count"))  # count rows = months
          .reset_index(drop=True)
    )
    episodes["duration_months"] = episodes["duration_months"].clip(lower=1).astype(float)

    # Last episode is right-censored — it has not ended yet
    episodes["observed"] = True
    episodes.iloc[-1, episodes.columns.get_loc("observed")] = False

    return episodes


def compute_km_estimates(episodes: pd.DataFrame) -> pd.DataFrame:
    """
    Fit Kaplan-Meier per regime type.
    Returns tidy DataFrame ready for bulk insert into regime_duration_stats.
    Requires lifelines>=0.27.
    """
    from lifelines import KaplanMeierFitter

    rows = []
    for regime, grp in episodes.groupby("regime"):
        if len(grp) < 2:
            print(f"  Skipping {regime}: only {len(grp)} episode(s), need >=2 for KM")
            continue

        kmf = KaplanMeierFitter()
        kmf.fit(
            durations=grp["duration_months"],
            event_observed=grp["observed"],
            label=regime,
        )

        timeline = kmf.timeline
        km_df    = kmf.survival_function_
        ci_df    = kmf.confidence_interval_survival_function_
        et       = kmf.event_table

        for t in timeline:
            s    = float(km_df.loc[t, regime])
            s_lo = float(ci_df.loc[t].iloc[0])
            s_hi = float(ci_df.loc[t].iloc[1])

            n_risk   = None
            n_events = None
            if t in et.index:
                idx = et.index.get_loc(t)
                n_risk   = int(et.iloc[idx]["at_risk"])
                n_events = int(et.iloc[idx]["observed"])

            rows.append({
                "regime":            regime,
                "duration_months":   int(t),
                "km_survival":       round(s,    4),
                "km_survival_lower": round(s_lo, 4),
                "km_survival_upper": round(s_hi, 4),
                "n_at_risk":         n_risk,
                "n_events":          n_events,
            })

    return pd.DataFrame(rows)


def write_km_estimates(conn, km_df: pd.DataFrame) -> None:
    from db.init_db import PH

    conn.execute("DELETE FROM regime_duration_stats")
    for _, row in km_df.iterrows():
        conn.execute(
            f"""
            INSERT INTO regime_duration_stats
                (regime, duration_months, km_survival, km_survival_lower,
                 km_survival_upper, n_at_risk, n_events)
            VALUES ({PH},{PH},{PH},{PH},{PH},{PH},{PH})
            ON CONFLICT (regime, duration_months) DO UPDATE SET
                km_survival       = EXCLUDED.km_survival,
                km_survival_lower = EXCLUDED.km_survival_lower,
                km_survival_upper = EXCLUDED.km_survival_upper,
                n_at_risk         = EXCLUDED.n_at_risk,
                n_events          = EXCLUDED.n_events
            """,
            [row["regime"], int(row["duration_months"]),
             row["km_survival"], row["km_survival_lower"], row["km_survival_upper"],
             row["n_at_risk"], row["n_events"]],
        )
    conn.commit()


def get_current_regime_status(conn) -> dict:
    """
    Compute current regime age using HMM predictions, then look up the
    Kaplan-Meier survival probability at that age.

    Returns dict with current_state, current_duration_months, km_survival_at_current,
    median_duration, p25_duration, p75_duration (all Optional).
    """
    try:
        latest_version = conn.execute(
            "SELECT model_version FROM hmm_predictions ORDER BY predicted_at DESC LIMIT 1"
        ).fetchone()[0]
        hmm_rows = conn.execute("""
            SELECT date, state_label
            FROM hmm_predictions
            WHERE model_version = %s
            ORDER BY date DESC
            LIMIT 90
        """, [latest_version]).fetchall()
    except Exception:
        return {}

    if not hmm_rows:
        return {}

    current_state = hmm_rows[0][1]
    latest_date = pd.Timestamp(hmm_rows[0][0])

    # Walk back to find when current regime started
    regime_start = latest_date
    for h_date, h_label in hmm_rows:
        if h_label != current_state:
            break
        regime_start = pd.Timestamp(h_date)

    current_duration = max(1, math.ceil((latest_date - regime_start).days / 30.44))

    # KM survival at current duration (nearest row ≤ current_duration)
    km_row = conn.execute(f"""
        SELECT km_survival, km_survival_lower, km_survival_upper
        FROM regime_duration_stats
        WHERE regime = '{current_state}'
          AND duration_months <= {current_duration}
        ORDER BY duration_months DESC
        LIMIT 1
    """).fetchone()

    # Derive median and percentile durations from KM table
    stats_row = conn.execute(f"""
        SELECT
            MIN(CASE WHEN km_survival <= 0.50 THEN duration_months END) AS median_dur,
            MIN(CASE WHEN km_survival <= 0.75 THEN duration_months END) AS p25_dur,
            MIN(CASE WHEN km_survival <= 0.25 THEN duration_months END) AS p75_dur
        FROM regime_duration_stats
        WHERE regime = '{current_state}'
    """).fetchone()

    return {
        "current_state":           current_state,
        "current_duration_months": current_duration,
        "km_survival_at_current":  round(float(km_row[0]), 3) if km_row and km_row[0] is not None else None,
        "km_survival_lower":       round(float(km_row[1]), 3) if km_row and km_row[1] is not None else None,
        "km_survival_upper":       round(float(km_row[2]), 3) if km_row and km_row[2] is not None else None,
        "median_duration":         int(stats_row[0]) if stats_row and stats_row[0] else None,
        "p25_duration":            int(stats_row[1]) if stats_row and stats_row[1] else None,
        "p75_duration":            int(stats_row[2]) if stats_row and stats_row[2] else None,
    }


def compute(print_summary: bool = True) -> dict:
    """Main entry point — load episodes, fit KM, write to DB. Called by pipeline."""
    conn = get_connection()
    print("Loading regime episodes...")
    episodes = load_regime_episodes(conn)

    if episodes.empty:
        print("  No regime_labels data found — skipping KM computation")
        conn.close()
        return {"episodes": 0, "km_rows": 0, "current_status": {}}

    print(f"  {len(episodes)} total episodes")

    if print_summary:
        counts = episodes["regime"].value_counts().to_dict()
        obs    = episodes[episodes["observed"]]["regime"].value_counts().to_dict()
        for regime in sorted(counts):
            grp = episodes[episodes["regime"] == regime]
            print(f"    {regime}: n={counts.get(regime,0)} "
                  f"(observed={obs.get(regime,0)}), "
                  f"median={grp['duration_months'].median():.1f}m, "
                  f"max={grp['duration_months'].max():.0f}m")

    print("Fitting Kaplan-Meier per regime type...")
    km_df = compute_km_estimates(episodes)
    print(f"  {len(km_df)} KM rows computed")

    write_km_estimates(conn, km_df)
    print("  Written to regime_duration_stats")

    status = get_current_regime_status(conn)
    conn.close()
    return {"episodes": len(episodes), "km_rows": len(km_df), "current_status": status}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["compute", "status"])
    args = parser.parse_args()

    if args.command == "compute":
        result = compute()
        print(f"\nDone. Episodes: {result['episodes']}, KM rows: {result['km_rows']}")
        cs = result["current_status"]
        if cs:
            surv = cs.get("km_survival_at_current")
            print(f"Current: {cs['current_state']} for {cs['current_duration_months']} months, "
                  f"KM survival={surv}")
    elif args.command == "status":
        conn = get_connection()
        status = get_current_regime_status(conn)
        conn.close()
        import json
        print(json.dumps(status, indent=2))
