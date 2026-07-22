"""
ingestion/prices.py — yfinance historical price loader

Fetches OHLCV data for all tickers defined in TICKERS from 2005-01-01.
Inserts into raw_prices using upsert (INSERT OR REPLACE) logic.
Run directly for a full historical backfill; called by pipeline.py for
incremental updates.
"""

import sys
from pathlib import Path
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent))
from db.init_db import get_connection, DATABASE_URL

TICKERS = [
    # -------------------------------------------------------------------------
    # GLOBAL / ALL-WORLD
    # -------------------------------------------------------------------------
    "ISAC.L",     # iShares MSCI ACWI — primary all-world (LSE, from 2011)
    "VWCE.DE",    # Vanguard FTSE All-World Acc — core IKE holding (Xetra, from 2019)
    "VWRP.L",     # Vanguard FTSE All-World Dist (LSE)
    "IWDA.L",     # iShares Core MSCI World — developed only (LSE)
    "XDWD.DE",    # Xtrackers MSCI World (Xetra)
    "SPPW.DE",    # SPDR MSCI World (Xetra)
    "XMAW.DE",    # Xtrackers MSCI ACWI (Xetra)
    "IUSQ.DE",    # iShares MSCI ACWI UCITS ETF (Xetra)

    # -------------------------------------------------------------------------
    # S&P 500
    # -------------------------------------------------------------------------
    "CSPX.L",     # iShares Core S&P 500 Acc (LSE) — ML date spine
    "SXR8.DE",    # iShares Core S&P 500 Acc (Xetra)
    "VUSA.L",     # Vanguard S&P 500 Dist (LSE)
    "VUSA.DE",    # Vanguard S&P 500 (Xetra)
    "IUSA.L",     # iShares Core S&P 500 Dist (LSE)
    "SPXS.L",     # Invesco S&P 500 Acc (LSE)
    "SPYL.DE",    # SPDR S&P 500 Acc (Xetra)
    "SPYD.DE",    # Invesco S&P 500 Dist (Xetra)
    "IQQQ.DE",    # Amundi S&P 500 Swap (Xetra)
    "SPEQ.L",     # Xtrackers S&P 500 Equal Weight (LSE)
    "XDGU.DE",    # Xtrackers S&P 500 Equal Weight (Xetra)

    # -------------------------------------------------------------------------
    # NASDAQ / TECH
    # -------------------------------------------------------------------------
    "CNDX.L",     # iShares NASDAQ-100 Acc (LSE)
    "EQQQ.L",     # Invesco EQQQ NASDAQ-100 (LSE)
    "SXRV.DE",    # iShares NASDAQ-100 (Xetra)
    "QDVE.DE",    # iShares S&P 500 IT Sector (Xetra)

    # -------------------------------------------------------------------------
    # EUROPE
    # -------------------------------------------------------------------------
    "MEUD.PA",    # Amundi Core Stoxx Europe 600 (Paris)
    "VEUR.L",     # Vanguard FTSE Developed Europe (LSE)
    "IMEU.L",     # iShares Core MSCI Europe Acc (LSE)
    "EXW1.DE",    # iShares EURO STOXX 50 (Xetra)
    "EXV1.DE",    # iShares STOXX Europe 600 (Xetra)
    "EXS1.DE",    # iShares Core DAX (Xetra)

    # -------------------------------------------------------------------------
    # EMERGING MARKETS
    # -------------------------------------------------------------------------
    "EIMI.L",     # iShares Core MSCI EM IMI Acc (LSE)
    "EMIM.L",     # iShares Core MSCI EM IMI — alternative share class (LSE)
    "IEEM.L",     # iShares MSCI EM Dist (LSE)
    "VFEM.L",     # Vanguard FTSE Emerging Markets (LSE)
    "XMEU.DE",    # Xtrackers MSCI EM (Xetra)

    # -------------------------------------------------------------------------
    # FACTOR / SMART BETA
    # -------------------------------------------------------------------------
    "ZPRV.DE",    # SPDR MSCI USA Small Cap Value (Xetra)
    "ZPRX.DE",    # SPDR MSCI Europe Small Cap Value (Xetra)
    "WSML.L",     # iShares MSCI World Small Cap (LSE)
    "VHYL.L",     # Vanguard All-World High Dividend (LSE)
    "IWVL.L",     # iShares MSCI World Value Factor (LSE)

    # -------------------------------------------------------------------------
    # BONDS
    # -------------------------------------------------------------------------
    "IDTL.L",     # iShares $ Treasury 20+yr (LSE)
    "IBTM.L",     # iShares $ Treasury 7-10yr (LSE)
    "IBTS.L",     # iShares $ Treasury 1-3yr (LSE)
    "SEGA.L",     # iShares Core EUR Govt Bond (LSE)
    "IEAC.L",     # iShares Core EUR Corporate Bond (LSE)
    "ITPS.L",     # iShares $ TIPS inflation-linked (LSE)

    # -------------------------------------------------------------------------
    # GOLD / COMMODITIES
    # -------------------------------------------------------------------------
    "IGLN.L",     # iShares Physical Gold ETC (LSE)
    "EGLN.L",     # iShares Physical Gold ETC USD (LSE)
    "SGLD.L",     # Invesco Physical Gold ETC (LSE)
    "SGLN.L",     # iShares Physical Gold (alternative, LSE)

    # -------------------------------------------------------------------------
    # REAL ESTATE / OTHER
    # -------------------------------------------------------------------------
    "IPRP.L",     # iShares European Property Yield (LSE)
    "IHYU.L",     # iShares $ High Yield Corp Bond (LSE)

    # -------------------------------------------------------------------------
    # INDEX / MACRO BENCHMARKS (not investable — ML features only)
    # -------------------------------------------------------------------------
    "^VIX",       # CBOE Volatility Index
    "DX-Y.NYB",   # US Dollar Index (DXY)
    "EURUSD=X",   # EUR/USD
    "USDPLN=X",   # USD/PLN
    "^TNX",       # 10-year US Treasury yield
    "^IRX",       # 3-month T-Bill yield
]

HISTORY_START = "2005-01-01"
SOURCE = "yfinance"


# If a ticker's newest stored row is more than this many calendar days behind
# today, the incremental fetch is not just "no new trading days" — the ticker
# has a genuine gap (yfinance intermittently returns empty for LSE tickers for
# a stretch). In that case we widen the fetch window (see get_latest_date) to
# force yfinance to backfill the hole rather than perpetually starting from the
# day after the stale date and getting empty responses forever.
STALE_GAP_DAYS  = 5    # ~3-4 trading days + weekend slack
GAP_REFETCH_DAYS = 45  # how far back to re-request when a gap is detected


def get_latest_date(conn, ticker: str) -> str:
    # WHY: We check the max date already stored before fetching so that
    # incremental runs only download the missing tail. This matters because
    # yfinance full-history calls can take several seconds per ticker and
    # consume Yahoo's unofficial rate limit. The fallback to HISTORY_START
    # ensures an empty table triggers a complete backfill automatically.
    ph = "%s" if DATABASE_URL else "?"
    row = conn.execute(
        f"SELECT MAX(date) FROM raw_prices WHERE ticker = {ph} AND source = {ph}",
        [ticker, SOURCE]
    ).fetchone()
    latest = row[0] if row and row[0] else None
    if latest is None:
        return HISTORY_START

    latest_ts = pd.Timestamp(latest)
    gap_days  = (pd.Timestamp(date.today()) - latest_ts).days

    # WHY the gap re-fetch: when a ticker has fallen well behind today, starting
    # the fetch from latest+1 keeps failing if yfinance is returning empty for
    # that recent window (the self-perpetuating LSE gap that froze the vol model
    # in 2026-07). Re-requesting a wider window (upsert makes re-inserting the
    # already-stored tail a harmless no-op) gives yfinance a chance to fill the
    # hole once its data reappears.
    if gap_days > STALE_GAP_DAYS:
        return (latest_ts - timedelta(days=GAP_REFETCH_DAYS)).strftime("%Y-%m-%d")

    # Normal incremental path: fetch from the day after the latest stored date
    # to avoid re-inserting the boundary row (upsert would handle it, but
    # cleaner to skip it).
    next_day = (latest_ts + timedelta(days=1)).strftime("%Y-%m-%d")
    return next_day


def fetch_ticker(ticker: str, start: str) -> pd.DataFrame:
    end = date.today().strftime("%Y-%m-%d")
    if start >= end:
        return pd.DataFrame()
    # WHY: auto_adjust=True returns split/dividend-adjusted prices in the
    # 'Close' column and does not provide a separate 'Adj Close' column.
    # We set auto_adjust=False so that both 'Close' and 'Adj Close' are
    # available — downstream volatility calculations use adj_close to avoid
    # return spikes from dividend ex-dates distorting rolling std.
    data = yf.download(
        ticker,
        start=start,
        end=end,
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if data.empty:
        return pd.DataFrame()

    # yfinance returns MultiIndex columns when downloading a single ticker
    # with auto_adjust=False in newer versions — flatten them.
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    data = data.reset_index()
    data.columns = [c.lower().replace(" ", "_") for c in data.columns]

    # Normalise column names across yfinance versions
    rename = {
        "adj_close": "adj_close",
        "adjclose":  "adj_close",
    }
    data = data.rename(columns=rename)

    needed = ["date", "open", "high", "low", "close", "adj_close", "volume"]
    for col in needed:
        if col not in data.columns:
            data[col] = None

    data["ticker"] = ticker
    data["source"] = SOURCE
    data["date"] = pd.to_datetime(data["date"]).dt.date

    return data[["date", "ticker", "source", "open", "high", "low",
                 "close", "adj_close", "volume"]]


def upsert_prices(conn, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    # WHY: INSERT OR REPLACE (DuckDB: INSERT INTO ... ON CONFLICT DO UPDATE)
    # is used instead of plain INSERT because ingestion may run twice on the
    # same day — e.g. if a Cloud Function retries after a transient failure.
    # Plain INSERT would raise a primary key violation and abort the batch.
    # OR REPLACE semantics overwrite the existing row with identical data,
    # leaving the table in the correct state. The trade-off is that a genuine
    # data correction (Yahoo revises yesterday's close) is automatically
    # absorbed — which is desirable for raw_prices since Yahoo's corrections
    # are legitimate. We log the upsert count to raw_qc_log in pipeline.py.
    ph = "%s" if DATABASE_URL else "?"
    conn.executemany(
        f"""
        INSERT INTO raw_prices
            (date, ticker, source, open, high, low, close, adj_close, volume)
        VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
        ON CONFLICT (date, ticker, source) DO UPDATE SET
            open      = EXCLUDED.open,
            high      = EXCLUDED.high,
            low       = EXCLUDED.low,
            close     = EXCLUDED.close,
            adj_close = EXCLUDED.adj_close,
            volume    = EXCLUDED.volume,
            ingested_at = now()
        """,
        df[["date", "ticker", "source", "open", "high", "low",
            "close", "adj_close", "volume"]].values.tolist()
    )
    return len(df)


def upsert_metadata(conn, tickers: list[str]) -> None:
    """Fetch long_name and currency from yfinance info and store in ticker_metadata."""
    cur = conn.cursor() if hasattr(conn, 'cursor') else None
    for ticker in tickers:
        try:
            info = yf.Ticker(ticker).info
            name = info.get("longName") or info.get("shortName") or ticker
            # Normalise GBp (pence) → GBP; yfinance returns pence for some LSE ETFs
            raw_ccy = info.get("currency") or "USD"
            currency = "GBP" if raw_ccy.upper() in ("GBP", "GBP") else raw_ccy.upper()
            if raw_ccy == "GBp":
                currency = "GBP"
        except Exception:
            name = ticker
            currency = "USD"
        sql = """
            INSERT INTO ticker_metadata (ticker, long_name, currency, updated_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (ticker) DO UPDATE SET
                long_name  = EXCLUDED.long_name,
                currency   = EXCLUDED.currency,
                updated_at = now()
        """
        if cur:
            cur.execute(sql, [ticker, name, currency])
        else:
            conn.execute(sql, [ticker, name, currency])
    if cur:
        cur.close()


def run(tickers: list[str] = TICKERS, full_reload: bool = False) -> dict:
    conn = get_connection()
    results = {}

    for ticker in tickers:
        start = HISTORY_START if full_reload else get_latest_date(conn, ticker)
        print(f"  {ticker}: fetching from {start} ...", end=" ")
        try:
            df = fetch_ticker(ticker, start)
            n = upsert_prices(conn, df)
            print(f"{n} rows upserted.")
            results[ticker] = {"rows": n, "error": None}
        except Exception as exc:
            print(f"ERROR — {exc}")
            results[ticker] = {"rows": 0, "error": str(exc)}

    upsert_metadata(conn, [t for t in tickers if not t.startswith("^") and "=X" not in t and t != "DX-Y.NYB"])
    conn.commit()
    conn.close()
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--full-reload", action="store_true",
                        help="Ignore stored dates and reload all history")
    args = parser.parse_args()

    print("=== yfinance price ingestion ===")
    results = run(full_reload=args.full_reload)
    total = sum(r["rows"] for r in results.values())
    errors = [t for t, r in results.items() if r["error"]]
    print(f"\nDone. {total} total rows upserted.")
    if errors:
        print(f"Tickers with errors: {errors}")
