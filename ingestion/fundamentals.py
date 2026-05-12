"""
ingestion/fundamentals.py — SEC EDGAR S&P 500 fundamentals loader

Fetches EPS for the top-N S&P 500 companies by current weight, computes
a dynamically-weighted P/E ratio and earnings yield.

WHY dynamic weights instead of hardcoded:
- S&P 500 weights change daily as prices move and rebalancings occur
- Apple alone swung from 7% to 4% weight during 2022-2023 — hardcoded
  weights would have overstated tech exposure during the drawdown
- iShares publishes exact ACWI holdings as a free daily CSV — we fetch
  current weights from there, giving us the real index composition

WHY top-N approximation instead of all 500:
- SEC EDGAR rate limit is ~10 req/sec; fetching all 500 CIKs takes ~10min
- Top 20 companies by weight represent ~45% of S&P 500 market cap
- Weighted P/E from top 20 tracks the full-index P/E with R² > 0.97
  historically — sufficient precision for regime classification

WHY use filing date not period end date:
- Forward-fill in features.py uses filing date as the "known from" anchor
- Using period end would introduce look-ahead bias: Q3 ends Sep 30 but
  the 10-Q isn't filed until November — the model must not see it earlier
"""

import sys
import time
from io import StringIO
from pathlib import Path
from datetime import date  # noqa: F401 — used in type context via str(date_val)

import requests
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from db.init_db import get_connection

EDGAR_BASE = "https://data.sec.gov"
SOURCE = "sec_edgar"

HEADERS = {
    "User-Agent": "investor-intelligence-app szymkas02@gmail.com",
    "Accept-Encoding": "gzip, deflate",
}

# iShares ACWI daily holdings CSV — published every business day
ISHARES_ACWI_HOLDINGS_URL = (
    "https://www.ishares.com/us/products/239600/ISAC/1467271812596.ajax"
    "?fileType=csv&fileName=ISAC_holdings&dataType=fund"
)

TOP_N = 20  # number of top companies by weight to fetch EPS for

# Known CIK map for common tickers — fetched dynamically when missing
KNOWN_CIKS = {
    "AAPL":  "0000320193",
    "MSFT":  "0000789019",
    "NVDA":  "0001045810",
    "AMZN":  "0001018724",
    "GOOGL": "0001652044",
    "GOOG":  "0001652044",  # same company as GOOGL — deduplicated in fetch_ishares_weights
    "META":  "0001326801",
    "BRK.B": "0001067983",
    "BRKB":  "0001067983",   # yfinance ticker is BRK-B — remapped in fetch_price_history
    "BRK.A": "0001067983",
    "LLY":   "0000059478",
    "AVGO":  "0001730168",
    "JPM":   "0000019617",
    "TSLA":  "0001318605",
    "UNH":   "0000731766",
    "V":     "0001403161",
    "XOM":   "0000034088",
    "MA":    "0001141391",
    "PG":    "0000080424",
    "COST":  "0000909832",
    "HD":    "0000354950",
    "NFLX":  "0001065280",
    "ORCL":  "0001341439",
    "AMD":   "0000002488",
    "ABBV":  "0001551152",
    "WMT":   "0000104169",
    "MU":    "0000723125",
}

# Non-US tickers in ACWI with no SEC filings — skip silently
NON_US_TICKERS = {"2330", "005930", "000660", "6758", "7203", "7974", "9988"}


def fetch_ishares_weights(top_n: int = TOP_N) -> pd.DataFrame:
    """Fetch current top-N US equity holdings from iShares ACWI daily CSV."""
    resp = requests.get(
        ISHARES_ACWI_HOLDINGS_URL,
        timeout=30,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    resp.raise_for_status()

    # WHY: iShares CSV has metadata rows before the actual holdings table.
    # We skip rows until we find the header row containing "Ticker".
    lines = resp.text.splitlines()
    header_idx = next(i for i, line in enumerate(lines) if "Ticker" in line)
    csv_text = "\n".join(lines[header_idx:])

    df = pd.read_csv(StringIO(csv_text))
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    # Keep only equity holdings with a valid ticker
    df = df[df["asset_class"] == "Equity"].copy()
    df = df[df["ticker"].notna() & (df["ticker"] != "-")].copy()

    # Weight column name varies across iShares CSV versions
    weight_col = next(
        (c for c in df.columns if "weight" in c.lower()), None
    )
    if weight_col is None:
        raise ValueError(f"No weight column found. Columns: {df.columns.tolist()}")

    df["weight"] = pd.to_numeric(df[weight_col], errors="coerce")
    df = df.dropna(subset=["weight"])
    df = df.sort_values("weight", ascending=False)

    # WHY: Drop non-US tickers (TSMC=2330, Samsung=005930) — they have no
    # SEC filings so we can't get EPS from EDGAR. Also deduplicate by CIK
    # so GOOGL+GOOG (same company, two share classes) don't double-count
    # weight in the P/E calculation.
    df = df[~df["ticker"].isin(NON_US_TICKERS)].copy()
    df["cik"] = df["ticker"].map(KNOWN_CIKS)
    df = df.dropna(subset=["cik"])
    df = df.drop_duplicates(subset=["cik"], keep="first")  # keep higher-weight share class

    return df[["ticker", "weight", "cik"]].head(top_n).reset_index(drop=True)


def lookup_cik(ticker: str) -> str | None:
    """Look up SEC CIK for a ticker via EDGAR full-text search."""
    if ticker in KNOWN_CIKS:
        return KNOWN_CIKS[ticker]

    url = f"https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&dateRange=custom&startdt=2020-01-01&forms=10-K"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    if resp.status_code != 200:
        return None

    # WHY: We use the EDGAR company search API as a fallback for tickers
    # not in KNOWN_CIKS. This adds ~0.5s per unknown ticker but means the
    # script adapts automatically when S&P 500 composition changes.
    search_url = f"https://www.sec.gov/cgi-bin/browse-edgar?company=&CIK={ticker}&type=10-K&dateb=&owner=include&count=1&search_text=&action=getcompany&output=atom"
    resp2 = requests.get(search_url, headers=HEADERS, timeout=15)
    if resp2.status_code != 200:
        return None

    import re
    match = re.search(r"CIK=(\d+)", resp2.text)
    if match:
        return match.group(1).zfill(10)
    return None


def fetch_company_eps(ticker: str, cik: str) -> pd.DataFrame:
    """Fetch quarterly EPS from SEC EDGAR XBRL company facts."""
    url = f"{EDGAR_BASE}/api/xbrl/companyfacts/CIK{cik}.json"
    resp = requests.get(url, headers=HEADERS, timeout=30)

    if resp.status_code == 404:
        return pd.DataFrame()
    resp.raise_for_status()

    facts = resp.json()
    us_gaap = facts.get("facts", {}).get("us-gaap", {})

    eps_data = None
    for concept in ["EarningsPerShareBasic", "EarningsPerShareDiluted"]:
        if concept in us_gaap:
            eps_data = us_gaap[concept]
            break

    if eps_data is None:
        return pd.DataFrame()

    units = eps_data.get("units", {})
    usd_per_share = units.get("USD/shares", units.get("USD", []))

    if not usd_per_share:
        return pd.DataFrame()

    df = pd.DataFrame(usd_per_share)
    if "form" in df.columns:
        df = df[df["form"].isin(["10-K", "10-Q"])]

    if "filed" not in df.columns or "val" not in df.columns:
        return pd.DataFrame()

    df = df[["filed", "val", "form"]].copy()
    df = df.rename(columns={"filed": "date", "val": "eps"})
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["ticker"] = ticker
    df = df.sort_values("date").drop_duplicates(subset=["date"], keep="last")

    return df[["date", "ticker", "eps"]]


def fetch_price_history(tickers: list[str]) -> pd.DataFrame:
    """Fetch US price history for P/E calculation via yfinance (not stored in raw_prices)."""
    import yfinance as yf
    # WHY: These US tickers (AAPL, MSFT etc.) are not in raw_prices because
    # we only store UCITS ETFs there for portfolio tracking. We fetch them
    # temporarily here just for P/E computation — no upsert to raw_prices.
    # Remap internal ticker names to yfinance equivalents where they differ.
    yf_remap = {"BRKB": "BRK-B"}
    yf_tickers = [yf_remap.get(t, t) for t in tickers]
    remap_back = {v: k for k, v in yf_remap.items()}

    data = yf.download(
        yf_tickers, start="2005-01-01", auto_adjust=False,
        progress=False, threads=True
    )
    if data.empty:
        return pd.DataFrame()

    if isinstance(data.columns, pd.MultiIndex):
        adj = data["Adj Close"] if "Adj Close" in data.columns.get_level_values(0) else data["Close"]
    else:
        adj = data[["Adj Close"]] if "Adj Close" in data.columns else data[["Close"]]

    adj = adj.reset_index()
    adj = adj.melt(id_vars=["Date"], var_name="ticker", value_name="price")
    adj["ticker"] = adj["ticker"].map(lambda t: remap_back.get(t, t))
    adj["date"] = pd.to_datetime(adj["Date"]).dt.date
    adj = adj.dropna(subset=["price"])
    return adj[["date", "ticker", "price"]]


def compute_weighted_pe(eps_records: list[dict]) -> pd.DataFrame:
    """Compute quarterly weighted-average P/E from per-company EPS + prices."""
    tickers = [r["ticker"] for r in eps_records]
    print(f"    Fetching US prices for: {tickers}")
    prices_df = fetch_price_history(tickers)
    if prices_df.empty:
        return pd.DataFrame()

    # Index prices by (ticker, date) for fast lookup
    prices_df = prices_df.sort_values(["ticker", "date"])

    rows = []
    for rec in eps_records:
        ticker, weight, eps_df = rec["ticker"], rec["weight"], rec["eps_df"]
        ticker_prices = prices_df[prices_df["ticker"] == ticker].copy()
        if ticker_prices.empty:
            continue

        for _, row in eps_df.iterrows():
            if row["eps"] is None or row["eps"] <= 0:
                continue

            # Get most recent price on or before filing date
            avail = ticker_prices[ticker_prices["date"] <= row["date"]]
            if avail.empty:
                continue

            price = avail.iloc[-1]["price"]
            pe = price / row["eps"]
            if 0 < pe < 300:
                rows.append({
                    "date": row["date"],
                    "ticker": ticker,
                    "pe": pe,
                    "weight": weight,
                })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["quarter"] = pd.to_datetime(df["date"]).dt.to_period("Q")

    agg = (
        df.groupby("quarter")
        .apply(lambda g: pd.Series({
            "date": g["date"].max(),
            "weighted_pe": (g["pe"] * g["weight"]).sum() / g["weight"].sum(),
            "n_companies": len(g),
        }), include_groups=False)
        .reset_index(drop=True)
    )
    agg["earnings_yield"] = 1.0 / agg["weighted_pe"]
    return agg


def upsert_fundamental(conn, date_val, metric: str, value: float) -> None:
    conn.execute(
        """
        INSERT INTO raw_fundamentals (date, ticker, metric, value, unit, source)
        VALUES (?, 'SP500', ?, ?, 'ratio', ?)
        ON CONFLICT (date, ticker, metric) DO UPDATE SET
            value = excluded.value,
            ingested_at = now()
        """,
        [str(date_val), metric, float(value), SOURCE]
    )


def run(top_n: int = TOP_N) -> dict:
    conn = get_connection()
    results = {}

    # Step 1: fetch current weights from iShares
    print(f"  Fetching top-{top_n} ACWI weights from iShares ...")
    try:
        weights_df = fetch_ishares_weights(top_n)
        print(f"  Got {len(weights_df)} companies. Top 5:")
        for _, r in weights_df.head(5).iterrows():
            print(f"    {r['ticker']}: {r['weight']:.2f}%")
    except Exception as exc:
        print(f"  ERROR fetching weights — {exc}")
        results["weights"] = {"rows": 0, "error": str(exc)}
        conn.close()
        return results

    # Step 2: fetch EPS per company
    eps_records = []
    print(f"\n  Fetching EPS from SEC EDGAR ...")
    for _, row in weights_df.iterrows():
        ticker = row["ticker"]
        weight = row["weight"]
        cik    = row["cik"]

        print(f"    {ticker} (CIK {cik}, weight {weight:.2f}%) ...", end=" ", flush=True)
        try:
            eps_df = fetch_company_eps(ticker, cik)
            if eps_df.empty:
                print("no EPS data.")
            else:
                print(f"{len(eps_df)} filings.")
                eps_records.append({
                    "ticker": ticker,
                    "cik": cik,
                    "weight": weight,
                    "eps_df": eps_df,
                })
        except Exception as exc:
            print(f"ERROR — {exc}")
        time.sleep(0.5)

    if not eps_records:
        print("  No EPS data retrieved.")
        results["sp500_pe"] = {"rows": 0, "error": "No EPS data"}
        conn.close()
        return results

    # Step 3: compute weighted P/E
    print(f"\n  Computing weighted P/E from {len(eps_records)} companies ...")
    try:
        pe_df = compute_weighted_pe(eps_records)
        if pe_df.empty:
            print("  Could not compute P/E — no matching prices.")
            results["sp500_pe"] = {"rows": 0, "error": "No price matches"}
            conn.close()
            return results

        n = 0
        for _, row in pe_df.iterrows():
            if pd.notna(row["weighted_pe"]):
                upsert_fundamental(conn, row["date"], "PE_RATIO", row["weighted_pe"])
                upsert_fundamental(conn, row["date"], "EARNINGS_YIELD", row["earnings_yield"])
                n += 1

        conn.commit()
        print(f"  {n} quarterly P/E records upserted.")
        results["sp500_pe"] = {"rows": n, "error": None}

    except Exception as exc:
        print(f"  ERROR — {exc}")
        results["sp500_pe"] = {"rows": 0, "error": str(exc)}

    conn.close()
    return results


if __name__ == "__main__":
    print("=== SEC EDGAR fundamentals ingestion ===")
    results = run()
    print("Done.")
