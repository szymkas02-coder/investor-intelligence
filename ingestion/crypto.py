"""
ingestion/crypto.py — CoinGecko crypto market data loader

Fetches BTC and ETH daily price, market cap, and volume from CoinGecko's
free public API. Crypto is used exclusively as a risk-on/risk-off proxy
in the ML feature set — this is NOT a crypto investment tracker.

WHY crypto as a market regime feature:
- BTC/SPY rolling correlation spikes during risk-off events (both sell off)
  and collapses during risk-on (BTC outperforms as speculative asset)
- Extreme BTC drawdowns (>30% in 21d) have historically preceded or
  coincided with equity market stress — useful early warning signal
- CoinGecko free tier: 30 calls/min, no API key required for public endpoints
"""

import sys
import time
from pathlib import Path
from datetime import date, datetime

import requests
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from db.init_db import get_connection, PH

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
HISTORY_START_UNIX = int(datetime(2015, 1, 1).timestamp())

# WHY: We start from 2015 rather than 2005 because reliable BTC price data
# begins in 2013 and ETH launched in 2015. Starting earlier returns sparse
# or missing data which would create NaN gaps in the feature table. The
# btc_spy_corr_21d feature requires 21 consecutive trading days — gaps
# in early crypto history would propagate NaN forward through the rolling
# window, corrupting regime features for weeks at a time.
COINS = {
    "bitcoin":  "BTC",
    "ethereum": "ETH",
}


def get_latest_date(conn, coin_id: str) -> datetime:
    row = conn.execute(
        f"SELECT MAX(date) FROM raw_crypto WHERE coin_id = {PH}",
        [coin_id]
    ).fetchone()
    latest = row[0] if row and row[0] else None
    if latest is None:
        return datetime(2015, 1, 1)
    return datetime.combine(pd.Timestamp(latest).date(), datetime.min.time()) + \
           pd.Timedelta(days=1)


def fetch_coin_history(coin_id: str, from_ts: int) -> pd.DataFrame:
    to_ts = int(datetime.now().timestamp())
    url = f"{COINGECKO_BASE}/coins/{coin_id}/market_chart/range"
    params = {
        "vs_currency": "usd",
        "from": from_ts,
        "to": to_ts,
    }
    resp = requests.get(url, params=params, timeout=30)

    # WHY: CoinGecko returns 429 when the free rate limit (30 req/min) is
    # exceeded. We raise immediately so the caller can catch and retry with
    # a backoff rather than silently storing an empty result. An empty result
    # would look like "no new data" to incremental ingestion and suppress
    # future fetch attempts until the next full reload.
    if resp.status_code == 429:
        raise RuntimeError("CoinGecko rate limit hit (429) — wait 60s and retry")
    resp.raise_for_status()

    data = resp.json()

    # CoinGecko returns lists of [timestamp_ms, value] pairs
    prices      = data.get("prices", [])
    market_caps = data.get("market_caps", [])
    volumes     = data.get("total_volumes", [])

    if not prices:
        return pd.DataFrame()

    df_price = pd.DataFrame(prices,      columns=["ts_ms", "price_usd"])
    df_mcap  = pd.DataFrame(market_caps, columns=["ts_ms", "market_cap_usd"])
    df_vol   = pd.DataFrame(volumes,     columns=["ts_ms", "volume_usd"])

    df = df_price.merge(df_mcap, on="ts_ms").merge(df_vol, on="ts_ms")

    # WHY: CoinGecko timestamps are UTC milliseconds. We convert to date
    # (dropping time) because we want one row per calendar day aligned with
    # raw_prices. For ranges > 90 days CoinGecko automatically returns daily
    # granularity — for shorter ranges it returns hourly, which would create
    # multiple rows per day. We take the last observation per day (closing
    # price equivalent) to handle any hourly bleed-through.
    df["date"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True).dt.date
    df = df.groupby("date").last().reset_index()
    df["coin_id"] = coin_id

    return df[["date", "coin_id", "price_usd", "market_cap_usd", "volume_usd"]]


def upsert_crypto(conn, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    conn.executemany(
        f"""
        INSERT INTO raw_crypto
            (date, coin_id, price_usd, market_cap_usd, volume_usd)
        VALUES ({PH}, {PH}, {PH}, {PH}, {PH})
        ON CONFLICT (date, coin_id) DO UPDATE SET
            price_usd      = excluded.price_usd,
            market_cap_usd = excluded.market_cap_usd,
            volume_usd     = excluded.volume_usd,
            ingested_at    = now()
        """,
        df[["date", "coin_id", "price_usd", "market_cap_usd",
            "volume_usd"]].values.tolist()
    )
    return len(df)


def run(coins: dict = COINS, full_reload: bool = False) -> dict:
    conn = get_connection()
    results = {}

    for coin_id, symbol in coins.items():
        if full_reload:
            from_dt = datetime(2015, 1, 1)
        else:
            from_dt = get_latest_date(conn, coin_id)

        from_ts = int(from_dt.timestamp())
        print(f"  {symbol} ({coin_id}): fetching from {from_dt.date()} ...",
              end=" ", flush=True)
        try:
            df = fetch_coin_history(coin_id, from_ts)
            n = upsert_crypto(conn, df)
            print(f"{n} rows upserted.")
            results[coin_id] = {"rows": n, "error": None}
        except Exception as exc:
            print(f"ERROR — {exc}")
            results[coin_id] = {"rows": 0, "error": str(exc)}

        # WHY: Sleep between coins to stay within CoinGecko's 30 req/min
        # free tier limit. Two coins with one sleep is well within budget.
        time.sleep(3)

    conn.commit()
    conn.close()
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--full-reload", action="store_true")
    args = parser.parse_args()

    print("=== CoinGecko crypto ingestion ===")
    results = run(full_reload=args.full_reload)
    total = sum(r["rows"] for r in results.values())
    errors = [c for c, r in results.items() if r["error"]]
    print(f"\nDone. {total} total rows upserted.")
    if errors:
        print(f"Coins with errors: {errors}")
