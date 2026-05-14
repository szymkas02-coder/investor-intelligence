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

    # --- Gold / commodity ETFs ---
    # Physical gold ETFs have no region or sector exposure —
    # they hold physical gold bullion only.
    "EGLN.L": {
        "commodities": {"Gold": 1.0},
    },
    "SGLN.DE": {
        "commodities": {"Gold": 1.0},
    },
    "IGLN.L": {
        "commodities": {"Gold": 1.0},
    },
    "PHAU.DE": {
        "commodities": {"Gold": 1.0},
    },
    "VZLD.DE": {
        "commodities": {"Gold": 1.0},
    },

    # --- Additional equity ETFs ---
    "EIMI.L": {
        # iShares Core MSCI EM IMI — Emerging Markets only
        "regions": {
            "China":    0.27,
            "India":    0.20,
            "Taiwan":   0.16,
            "Korea":    0.12,
            "Brazil":   0.06,
            "Other_EM": 0.19,
        },
        "sectors": {
            "Technology":             0.22,
            "Financials":             0.22,
            "Consumer Discretionary": 0.14,
            "Communication Services": 0.10,
            "Industrials":            0.07,
            "Materials":              0.07,
            "Energy":                 0.06,
            "Consumer Staples":       0.05,
            "Healthcare":             0.04,
            "Utilities":              0.02,
            "Real Estate":            0.01,
        },
    },
    "CSPX.L": {
        # iShares Core S&P 500 — same underlying index as SPPW.DE
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
    "IWDA.L": {
        # iShares Core MSCI World — same underlying index as IUSQ.DE (developed markets only)
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
    "VUSA.L": {
        # Vanguard S&P 500 — same underlying index as SPPW.DE
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
    "VAGF.L": {
        # Vanguard Global Aggregate Bond ETF
        # Note: for bond ETFs, "sectors" means bond types (not equity sectors)
        "regions": {
            "North America":    0.43,
            "Europe":           0.30,
            "Asia Pacific":     0.18,
            "Emerging Markets": 0.09,
        },
        "sectors": {
            "Government":  0.50,
            "Corporate":   0.30,
            "Securitized": 0.12,
            "Other":       0.08,
        },
    },
    "AGGH.L": {
        # iShares Core Global Aggregate Bond — same profile as VAGF.L
        "regions": {
            "North America":    0.43,
            "Europe":           0.30,
            "Asia Pacific":     0.18,
            "Emerging Markets": 0.09,
        },
        "sectors": {
            "Government":  0.50,
            "Corporate":   0.30,
            "Securitized": 0.12,
            "Other":       0.08,
        },
    },
    "ZPRV.DE": {
        # SPDR MSCI USA Small Cap Value Weighted — US small-cap value
        "regions": {
            "North America": 1.00,
        },
        "sectors": {
            "Financials":             0.22,
            "Industrials":            0.18,
            "Consumer Discretionary": 0.14,
            "Technology":             0.12,
            "Healthcare":             0.10,
            "Materials":              0.07,
            "Energy":                 0.07,
            "Consumer Staples":       0.05,
            "Real Estate":            0.03,
            "Utilities":              0.02,
        },
    },
    "ZPRX.DE": {
        # SPDR MSCI Europe Small Cap Value Weighted — European small-cap value
        "regions": {
            "Europe": 1.00,
        },
        "sectors": {
            "Industrials":            0.22,
            "Financials":             0.19,
            "Consumer Discretionary": 0.14,
            "Materials":              0.12,
            "Technology":             0.08,
            "Consumer Staples":       0.07,
            "Healthcare":             0.07,
            "Energy":                 0.05,
            "Real Estate":            0.04,
            "Utilities":              0.02,
        },
    },
    "IBTM.L": {
        # iShares $ Treasury Bond 7-10yr — US government bonds only
        "regions": {
            "North America": 1.00,
        },
        "sectors": {
            "Government": 1.00,
        },
    },
    "IDTL.L": {
        # iShares $ Treasury Bond 20+yr — US long-duration government bonds
        "regions": {
            "North America": 1.00,
        },
        "sectors": {
            "Government": 1.00,
        },
    },
}


def seed_etf_allocations(conn):
    """Upsert ETF allocation seed data into etf_allocations table.

    Safe to call on every startup — uses INSERT ... ON CONFLICT DO UPDATE
    so it won't duplicate rows, but WILL refresh weights if we change them.

    Supports three allocation_type values: 'region', 'sector', 'commodity'.
    Gold/commodity ETFs only have a 'commodity' entry; equity ETFs have
    'region' + 'sector'. Bond ETFs have 'region' + 'sector' (where sectors
    represent bond types: Government, Corporate, Securitized, etc.).
    """
    # Map dict key name → allocation_type stored in DB
    _KEY_TO_TYPE = {
        "regions":    "region",
        "sectors":    "sector",
        "commodities": "commodity",
    }
    for ticker, data in ETF_ALLOCATIONS.items():
        for dict_key, alloc_type in _KEY_TO_TYPE.items():
            weights = data.get(dict_key)
            if not weights:
                continue
            for label, weight in weights.items():
                conn.execute("""
                    INSERT INTO etf_allocations (ticker, allocation_type, label, weight)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (ticker, allocation_type, label)
                    DO UPDATE SET weight = EXCLUDED.weight, updated_at = NOW()
                """, [ticker, alloc_type, label, weight])
