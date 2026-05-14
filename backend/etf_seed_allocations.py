"""
backend/etf_seed_allocations.py — Seed ETF region/sector allocations

Approximate values from iShares/Vanguard factsheets (public knowledge).
Used to populate etf_allocations table on startup via run_migrations().

TEACHING NOTE:
  These weights come from ETF factsheets — each ETF publishes what % of its
  holdings are in each country/sector. VWCE.DE tracks MSCI ACWI (All Country
  World Index), so ~65% of your money is in US stocks, ~15% in Europe, etc.
  This is useful for checking whether your portfolio is already diversified
  or if you have a concentration in one region.
"""

# Allocation data: ticker -> {regions: {...}, sectors: {...}}
# Weights are floats that sum to 1.0 (or very close — minor rounding ok)
ETF_ALLOCATIONS = {
    "VWCE.DE": {
        "regions": {
            "North America": 0.65,
            "Europe":        0.15,
            "Asia Pacific":  0.12,
            "Emerging Markets": 0.08,
        },
        "sectors": {
            "Technology":             0.24,
            "Financials":             0.16,
            "Healthcare":             0.12,
            "Consumer Discretionary": 0.11,
            "Industrials":            0.10,
            "Communication Services": 0.08,
            "Consumer Staples":       0.07,
            "Energy":                 0.05,
            "Materials":              0.04,
            "Utilities":              0.02,
            "Real Estate":            0.01,
        },
    },
    "ISAC.L": {
        # Same underlying index as VWCE.DE (MSCI ACWI)
        "regions": {
            "North America": 0.65,
            "Europe":        0.15,
            "Asia Pacific":  0.12,
            "Emerging Markets": 0.08,
        },
        "sectors": {
            "Technology":             0.24,
            "Financials":             0.16,
            "Healthcare":             0.12,
            "Consumer Discretionary": 0.11,
            "Industrials":            0.10,
            "Communication Services": 0.08,
            "Consumer Staples":       0.07,
            "Energy":                 0.05,
            "Materials":              0.04,
            "Utilities":              0.02,
            "Real Estate":            0.01,
        },
    },
    "IUSQ.DE": {
        # MSCI World — developed markets only (no EM)
        "regions": {
            "North America": 0.72,
            "Europe":        0.17,
            "Asia Pacific":  0.11,
        },
        "sectors": {
            "Technology":             0.25,
            "Financials":             0.16,
            "Healthcare":             0.13,
            "Consumer Discretionary": 0.11,
            "Industrials":            0.11,
            "Communication Services": 0.08,
            "Consumer Staples":       0.07,
            "Energy":                 0.05,
            "Materials":              0.03,
            "Utilities":              0.01,
        },
    },
    "XNAS.DE": {
        # Nasdaq-100 — tech-heavy, almost entirely US
        "regions": {
            "North America": 0.98,
            "Other":         0.02,
        },
        "sectors": {
            "Technology":             0.58,
            "Communication Services": 0.17,
            "Consumer Discretionary": 0.14,
            "Healthcare":             0.06,
            "Industrials":            0.03,
            "Other":                  0.02,
        },
    },
    "SPPW.DE": {
        # S&P 500 — US large-cap only
        "regions": {
            "North America": 1.00,
        },
        "sectors": {
            "Technology":             0.31,
            "Financials":             0.14,
            "Healthcare":             0.12,
            "Consumer Discretionary": 0.10,
            "Industrials":            0.09,
            "Communication Services": 0.09,
            "Consumer Staples":       0.06,
            "Energy":                 0.04,
            "Materials":              0.03,
            "Utilities":              0.02,
        },
    },
}


def seed_etf_allocations(conn):
    """Upsert ETF allocation seed data into etf_allocations table.

    Safe to call on every startup — uses INSERT ... ON CONFLICT DO UPDATE
    so it won't duplicate rows, but WILL refresh weights if we change them.
    """
    for ticker, data in ETF_ALLOCATIONS.items():
        for alloc_type, weights in (("region", data["regions"]), ("sector", data["sectors"])):
            for label, weight in weights.items():
                conn.execute("""
                    INSERT INTO etf_allocations (ticker, allocation_type, label, weight)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (ticker, allocation_type, label)
                    DO UPDATE SET weight = EXCLUDED.weight, updated_at = NOW()
                """, [ticker, alloc_type, label, weight])
