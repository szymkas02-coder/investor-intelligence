# Portfolio Projection Model

*Last updated: 2026-05-06*

---

## Overview

The long-term projection in `/decision/projection` uses a **Monte Carlo simulation** driven by an **ensemble of three independent return signals**. The ensemble was designed to address the key failure of the original model, which used only the US CAPE decile and produced implausibly low return estimates (~0.5% real) for a globally diversified portfolio when US valuations are high.

The target instrument is **VWCE.DE** — a UCITS ETF tracking the MSCI ACWI index, approximately:
- 60% US large-cap equities
- 30% developed ex-US equities
- 10% emerging markets

---

## Ensemble Components

### Component 1 — US CAPE Signal (weight: 30%)

**Source:** Asness, C. (2012). *"An Old Friend: The Stock Market's Shiller P/E."* AQR Capital Management.

The Shiller CAPE (Cyclically Adjusted P/E) is divided into 10 deciles based on historical US data (1926–2024). Each decile maps to a median annualised real return and standard deviation:

| Decile | CAPE range    | Median real return | Std  |
|--------|---------------|--------------------|------|
| 1      | < 9.6         | 10.3%              | 6.0% |
| 2      | 9.6 – 11.6   | 9.0%               | 5.5% |
| 3      | 11.6 – 13.6  | 8.2%               | 5.8% |
| 4      | 13.6 – 15.6  | 7.5%               | 5.5% |
| 5      | 15.6 – 17.3  | 6.8%               | 6.0% |
| 6      | 17.3 – 19.4  | 6.2%               | 5.8% |
| 7      | 19.4 – 21.1  | 5.6%               | 6.2% |
| 8      | 21.1 – 25.1  | 4.0%               | 6.5% |
| 9      | 25.1+         | 0.9%               | 6.8% |
| 10     | highest       | 0.5%               | 7.2% |

**Important limitation:** This is a US-only estimate. We intentionally do not geographically adjust the CAPE signal because ex-US CAPE data is not yet in the pipeline at sufficient quality. This signal is therefore US-centric and should be interpreted accordingly. When US CAPE is very high (decile 9–10), this signal will be pessimistic for VWCE, which is only 60% US.

**Future improvement:** Add non-US CAPE (MSCI EAFE CAPE, EM CAPE) and blend geographically. Data sources: StarCapital, Research Affiliates.

---

### Component 2 — Long-run Historical Base Rate (weight: 50%)

**Source:** Dimson, E., Marsh, P., & Staunton, M. (2025). *Global Investment Returns Yearbook 2025.* UBS/London Business School. 125 years of data, 1900–2024, 23 markets.

Key figures from the 2025 Yearbook:
- **World equities:** 5.2% real p.a. (annualised, 1900–2024)
- **US equities:** 6.6% real p.a.
- **Ex-US equities:** 4.3% real p.a.

For VWCE (ACWI, ~60% US / ~40% ex-US), the blended DMS estimate is:

```
0.60 × 6.6% + 0.40 × 4.3% = 5.72% real
```

Cross-checked against **Vanguard Capital Markets Model (VCMM) Q1 2026** forward estimates:
- Ex-US developed nominal ~7.7% → real ~5.2% (at 2.5% inflation)
- Emerging markets nominal ~7.5% → real ~5.0%
- Blended forward estimate: ~5.0–5.5% real

**Base rate adopted: 5.5% real** — conservative midpoint between the 125-year DMS historical average (5.7%) and Vanguard's forward-looking model (~5.1%). This gives the anchor the highest weight (50%) because it is the most robust estimate — derived from the longest available dataset across the most markets.

**Standard deviation adopted: 15.0%** — DMS reports ~17% cross-country annual volatility for individual equity markets. For a globally diversified 40+ country portfolio, we apply a diversification reduction to 15%.

---

### Component 3 — Momentum / Valuation Adjustment (weight: 20%)

**Source:** Live data from `daily_features` table.

Two signals are combined into a small real-time nudge:

1. **ACWI 63-day return** — captures medium-term momentum. A strongly positive 63d return nudges the estimate up slightly (momentum persistence); a strongly negative one nudges down.
2. **S&P 500 earnings yield** (`sp500_earnings_yield = 1 / CAPE`) — when earnings yield is above 5% (cheap market), the adjustment is positive; below 5% (expensive), it is negative.

```python
momentum_adj = acwi_ret_63d * 0.5 + (earnings_yield - 0.05) * 0.3
momentum_adj = clip(momentum_adj, -1.5%, +1.5%)
```

The momentum return fed into the ensemble is `base_rate + momentum_adj`. The cap of ±1.5% ensures this component cannot dominate the ensemble.

---

## Ensemble Combination

```python
ensemble_median = 0.30 × cape_return + 0.50 × base_rate + 0.20 × momentum_return
```

The ensemble standard deviation is computed via weighted quadrature:

```python
ensemble_std = sqrt(0.30² × cape_std² + 0.50² × 15%² + 0.20² × 15%²)
```

A **dispersion penalty** is added: if the three components disagree significantly, the std is widened proportionally to the maximum pairwise signal spread × 0.3. This reflects genuine uncertainty when signals conflict.

---

## Monte Carlo Simulation

- **Paths:** 10,000
- **Distribution:** Normal shocks, `r_monthly ~ N(ensemble_median/12, ensemble_std/√12)`
- **Each month:** `portfolio = portfolio × (1 + r_monthly) + monthly_contribution`
- **Output:** 10th / 50th / 90th percentile terminal values, recorded annually

All returns are **real (inflation-adjusted)**. The output does not include inflation, taxes, or transaction costs.

---

## Known Limitations

1. **No ex-US CAPE** — the CAPE signal is US-only. When ex-US markets are cheap relative to the US, the CAPE component underestimates VWCE returns.
2. **Normal shocks** — real equity returns are fat-tailed and negatively skewed. A log-normal or Student-t shock distribution would be more accurate.
3. **Fixed distribution over time** — the return distribution does not shift within the simulation as CAPE changes. A regime-switching model would be more realistic for 20–30 year horizons.
4. **PLN not modelled** — all returns are in the ETF's base currency (EUR/USD). PLN/EUR FX risk over long horizons is not captured.

---

## Future Improvements

- Add MSCI EAFE CAPE and EM CAPE for geographic blending (StarCapital API or Research Affiliates)
- Switch to log-normal or Student-t return shocks
- Regime-conditional return distributions (link to HMM regime model)
- PLN/EUR long-run FX adjustment (PPP-based)
