"""
backend/hmm_utils.py — HMM state probability resolution

The hmm_predictions table stores prob_bull, prob_bear, prob_consolidation but NOT
prob_stagflation. When the HMM is in the stagflation state, all three stored
probabilities underflow to ~10^-60 because the model's forward algorithm assigns
essentially all probability mass to the stagflation state, which isn't stored.

Resolution rules:
  - If state_label == 'stagflation': set prob_stagflation=0.99, others=0.003
  - If state_label == 'bear': set prob_bear=0.99 if all stored values underflow
  - If state_label == 'bull': set prob_bull=0.99 if underflow
  - If state_label == 'consolidation': set prob_consolidation=0.99 if underflow
  - Otherwise use stored values (normalised to sum to 1)

Stagflation HMM state characteristics (from model means, standardised space):
  ret=-0.055 (negative!), vol=+1.38 (highest of all states), CAPE=+0.27 (elevated),
  excess_cape_yield=-0.42 (expensive). This is the high-vol stress state —
  captures 2008 GFC, COVID, 2022 inflation shock. NOT equivalent to consolidation.
"""


def resolve_hmm_probs(state_label: str, p_bull_raw: float, p_bear_raw: float,
                      p_cons_raw: float) -> tuple[str, float, float, float, float]:
    """
    Returns (state, prob_bull, prob_bear, prob_consolidation, prob_stagflation).
    All four probabilities sum to 1.0.
    """
    state = state_label or "consolidation"

    p_bull = float(p_bull_raw or 0)
    p_bear = float(p_bear_raw or 0)
    p_cons = float(p_cons_raw or 0)
    total  = p_bull + p_bear + p_cons

    if state == "stagflation":
        # Stagflation state: high-vol stress. prob_stagflation is not stored in DB
        # but is ~0.99 when state_label = stagflation.
        return "stagflation", 0.003, 0.003, 0.003, 0.99
    elif total < 0.01:
        # Underflow for non-stagflation states: assign confidence to active state
        p_bull = 0.99 if state == "bull" else 0.003
        p_bear = 0.99 if state == "bear" else 0.003
        p_cons = 0.99 if state == "consolidation" else 0.003
        return state, round(p_bull, 4), round(p_bear, 4), round(p_cons, 4), 0.003
    else:
        # Renormalise
        p_bull /= total
        p_bear /= total
        p_cons /= total
        return state, round(p_bull, 4), round(p_bear, 4), round(p_cons, 4), 0.0
