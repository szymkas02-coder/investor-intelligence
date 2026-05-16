"""
processing/features.py — Build daily_features from raw tables via DuckDB SQL

Executes feature groups sequentially, each writing to daily_features.
Run after all ingestion modules have completed.

Feature groups:
  1. Log returns and rolling volatility (window functions)
  2. Yield curve spreads and inversion days
  3. PLN-adjusted ACWI returns (join prices × FX)
  4. Forward-fill monthly/quarterly macro to daily
  5. Sentiment and crypto features
  6. Derived boolean flags and vol regime label
"""

import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).parent.parent))
from db.init_db import get_connection
from utils.logging_config import get_logger

log = get_logger(__name__)

# Primary ACWI ticker — ISAC.L used for returns/vol (starts 2011, 3x more history
# than VWCE.DE which starts 2019). VWCE.DE still used for PLN return calculation
# because it is EUR-denominated, matching the investor's actual IKE holding.
ACWI_TICKER  = "ISAC.L"   # iShares MSCI ACWI — primary (USD, LSE, from 2011)
ACWI_SOURCE  = "yfinance"
VWCE_TICKER  = "VWCE.DE"  # used only for EUR/PLN-adjusted return
SPY_TICKER   = "CSPX.L"   # S&P 500 UCITS proxy
WIG20_TICKER = "WIG20"
WIG20_SOURCE = "stooq"
GOLD_TICKER  = "IGLN.L"
TLT_TICKER   = "IDTL.L"


def run_sql(conn, sql: str, label: str = "") -> None:
    try:
        conn.execute(sql)
        if label:
            log.info("OK  %s", label)
    except Exception as exc:
        log.error("FAIL %s: %s", label, exc)
        raise


def build_features(conn=None) -> None:
    _owns_conn = conn is None
    if conn is None:
        conn = get_connection()
    today = date.today().isoformat()

    # =========================================================================
    # STEP 0 — Seed daily_features date spine from available price dates
    # WHY: We need a master date index before filling any features. We use
    # VWCE.DE trading days as the spine — it trades on Xetra business days
    # which aligns with European market conventions. Dates with no VWCE data
    # (weekends, holidays) are excluded — there are no investable decisions
    # on those days anyway.
    # =========================================================================
    log.info("Step 0: Building date spine ...")
    # WHY: Use ISAC.L (from 2011) + CSPX.L (from 2010) as the date spine.
    # ISAC.L is now the primary ACWI ticker — 3x more history than VWCE.DE.
    # Union of both ensures no trading day is missed. Both trade on LSE
    # business days so the union produces a clean daily index.
    run_sql(conn, f"""
        INSERT INTO daily_features (date)
        SELECT DISTINCT date
        FROM raw_prices
        WHERE ticker IN ('{ACWI_TICKER}', '{SPY_TICKER}')
          AND source = '{ACWI_SOURCE}'
          AND date >= '2005-01-01' AND date <= '{today}'
        ON CONFLICT (date) DO NOTHING
    """, "date spine seeded")

    # =========================================================================
    # STEP 1 — Log returns and rolling volatility
    # WHY: Log returns are used instead of simple returns because they are
    # additive over time (log(P_t/P_0) = sum of daily log returns) and
    # approximately normally distributed — both properties that LightGBM
    # and Random Forest handle better than skewed simple return distributions.
    # Rolling volatility is annualized by multiplying std by sqrt(252) —
    # 252 trading days per year is the market convention.
    # WHY window ROWS BETWEEN N PRECEDING AND CURRENT ROW: this is a
    # strictly backward-looking window — no look-ahead bias. It uses the
    # N most recent trading days available, not calendar days, so gaps
    # (holidays) don't distort the window size.
    # =========================================================================
    log.info("Step 1: Log returns and rolling volatility ...")

    run_sql(conn, f"""
        UPDATE daily_features
        SET
            acwi_ret_1d  = src.ret_1d,
            acwi_ret_5d  = src.ret_5d,
            acwi_ret_21d = src.ret_21d,
            acwi_ret_63d = src.ret_63d,
            acwi_vol_21d = src.vol_21d,
            acwi_vol_63d = src.vol_63d
        FROM (
            WITH log_rets AS (
                SELECT date,
                       LN(adj_close / LAG(adj_close, 1)  OVER (ORDER BY date)) AS ret_1d,
                       LN(adj_close / LAG(adj_close, 5)  OVER (ORDER BY date)) AS ret_5d,
                       LN(adj_close / LAG(adj_close, 21) OVER (ORDER BY date)) AS ret_21d,
                       LN(adj_close / LAG(adj_close, 63) OVER (ORDER BY date)) AS ret_63d,
                       adj_close
                FROM raw_prices
                WHERE ticker = '{ACWI_TICKER}' AND source = '{ACWI_SOURCE}'
            )
            SELECT date,
                   ret_1d, ret_5d, ret_21d, ret_63d,
                   STDDEV(ret_1d) OVER (
                       ORDER BY date ROWS BETWEEN 20 PRECEDING AND CURRENT ROW
                   ) * SQRT(252) AS vol_21d,
                   STDDEV(ret_1d) OVER (
                       ORDER BY date ROWS BETWEEN 62 PRECEDING AND CURRENT ROW
                   ) * SQRT(252) AS vol_63d
            FROM log_rets
        ) src
        WHERE daily_features.date = src.date
    """, "ACWI returns + vol")

    run_sql(conn, f"""
        UPDATE daily_features
        SET spy_ret_1d = src.ret_1d
        FROM (
            SELECT date,
                   LN(adj_close / LAG(adj_close, 1) OVER (ORDER BY date)) AS ret_1d
            FROM raw_prices
            WHERE ticker = '{SPY_TICKER}' AND source = '{ACWI_SOURCE}'
        ) src
        WHERE daily_features.date = src.date
    """, "SPY ret_1d")

    run_sql(conn, f"""
        UPDATE daily_features
        SET wig20_ret_1d = src.ret_1d
        FROM (
            SELECT date,
                   LN(adj_close / LAG(adj_close, 1) OVER (ORDER BY date)) AS ret_1d
            FROM raw_prices
            WHERE ticker = '{WIG20_TICKER}' AND source = '{WIG20_SOURCE}'
        ) src
        WHERE daily_features.date = src.date
    """, "WIG20 ret_1d")

    run_sql(conn, f"""
        UPDATE daily_features
        SET gold_ret_1d  = src.ret_1d,
            gold_ret_21d = src.ret_21d
        FROM (
            SELECT date,
                   LN(adj_close / LAG(adj_close, 1)  OVER (ORDER BY date)) AS ret_1d,
                   LN(adj_close / LAG(adj_close, 21) OVER (ORDER BY date)) AS ret_21d
            FROM raw_prices
            WHERE ticker = '{GOLD_TICKER}' AND source = '{ACWI_SOURCE}'
        ) src
        WHERE daily_features.date = src.date
    """, "Gold ret_1d + ret_21d")

    run_sql(conn, f"""
        UPDATE daily_features
        SET tlt_ret_1d = src.ret_1d
        FROM (
            SELECT date,
                   LN(adj_close / LAG(adj_close, 1) OVER (ORDER BY date)) AS ret_1d
            FROM raw_prices
            WHERE ticker = '{TLT_TICKER}' AND source = '{ACWI_SOURCE}'
        ) src
        WHERE daily_features.date = src.date
    """, "TLT ret_1d")

    run_sql(conn, """
        UPDATE daily_features
        SET vix_close     = src.close,
            vix_change_5d = src.change_5d
        FROM (
            SELECT date,
                   adj_close AS close,
                   adj_close - LAG(adj_close, 5) OVER (ORDER BY date) AS change_5d
            FROM raw_prices
            WHERE ticker = '^VIX' AND source = 'yfinance'
        ) src
        WHERE daily_features.date = src.date
    """, "VIX close + 5d change")

    run_sql(conn, """
        UPDATE daily_features
        SET dxy_close = src.adj_close
        FROM raw_prices src
        WHERE daily_features.date = src.date
          AND src.ticker = 'DX-Y.NYB' AND src.source = 'yfinance'
    """, "DXY close")

    # =========================================================================
    # STEP 2 — Yield curve
    # WHY: We source yields from FRED (DGS10, DGS2, DGS3MO) rather than
    # yfinance (^TNX, ^IRX) because FRED is the authoritative source and
    # handles weekend/holiday gaps with explicit NaN rather than carrying
    # stale prices forward silently. Spreads are computed here so the ML
    # model sees the derived signal directly — avoids recomputing in every
    # query. yield_curve_inverted is a boolean flag (10Y-3M < 0) stored
    # as a feature because inversion duration matters more than the spread
    # level for recession prediction.
    # =========================================================================
    log.info("Step 2: Yield curve ...")

    run_sql(conn, """
        UPDATE daily_features
        SET yield_10y      = y10.value,
            yield_2y       = y2.value,
            yield_3m       = y3m.value,
            spread_10y_2y  = y10.value - y2.value,
            spread_10y_3m  = y10.value - y3m.value
        FROM
            (SELECT date, value FROM raw_macro WHERE series_id = 'DGS10' AND source = 'fred') y10
        LEFT JOIN
            (SELECT date, value FROM raw_macro WHERE series_id = 'DGS2'  AND source = 'fred') y2
            ON y10.date = y2.date
        LEFT JOIN
            (SELECT date, value FROM raw_macro WHERE series_id = 'DGS3MO' AND source = 'fred') y3m
            ON y10.date = y3m.date
        WHERE daily_features.date = y10.date
    """, "Yield curve spreads")

    run_sql(conn, """
        UPDATE daily_features
        SET ecb_rate_10y = src.value
        FROM raw_macro src
        WHERE daily_features.date = src.date
          AND src.series_id = 'EA_YIELD_10Y' AND src.source = 'ecb'
    """, "ECB 10Y yield")

    run_sql(conn, """
        UPDATE daily_features
        SET yield_curve_inverted = (spread_10y_3m < 0)
        WHERE spread_10y_3m IS NOT NULL
    """, "Yield curve inversion flag")

    # =========================================================================
    # STEP 3 — PLN-adjusted ACWI returns
    # WHY: A Polish investor holding VWCE.DE experiences returns in PLN, not
    # EUR or USD. The actual return is:
    #   acwi_pln_ret = (price_eur × eurpln_t) / (price_eur_t-1 × eurpln_t-1) - 1
    # This decomposes into asset return + FX return. Storing the combined
    # PLN return is the investor's true experience — it's what drives actual
    # wealth accumulation and what the decision engine should optimize for.
    # VWCE.DE is EUR-denominated so we join with EUR/PLN from NBP.
    # =========================================================================
    log.info("Step 3: PLN-adjusted returns ...")

    run_sql(conn, """
        UPDATE daily_features
        SET acwi_pln_ret_1d  = src.ret_1d_pln,
            acwi_pln_ret_21d = src.ret_21d_pln
        FROM (
            WITH pln_series AS (
                SELECT p.date,
                       p.adj_close * f.rate AS price_pln
                FROM raw_prices p
                JOIN raw_fx f
                  ON p.date = f.date
                 AND f.base_currency = 'EUR'
                 AND f.quote_currency = 'PLN'
                 AND f.source = 'nbp'
                WHERE p.ticker = '{VWCE_TICKER}' AND p.source = 'yfinance'
            )
            SELECT date,
                   LN(price_pln / LAG(price_pln, 1)  OVER (ORDER BY date)) AS ret_1d_pln,
                   LN(price_pln / LAG(price_pln, 21) OVER (ORDER BY date)) AS ret_21d_pln
            FROM pln_series
        ) src
        WHERE daily_features.date = src.date
    """, "ACWI PLN-adjusted returns")

    run_sql(conn, """
        UPDATE daily_features
        SET usdpln         = src.rate,
            usdpln_ret_21d = src.ret_21d,
            usdpln_vol_21d = src.vol_21d
        FROM (
            WITH fx AS (
                SELECT date, rate FROM raw_fx
                WHERE base_currency = 'USD' AND quote_currency = 'PLN'
                  AND source = 'nbp'
            ),
            log_rets AS (
                SELECT date, rate,
                       LN(rate / LAG(rate, 1)  OVER (ORDER BY date)) AS log_ret_1d,
                       LN(rate / LAG(rate, 21) OVER (ORDER BY date)) AS ret_21d
                FROM fx
            )
            SELECT date, rate,
                   ret_21d,
                   STDDEV(log_ret_1d) OVER (
                       ORDER BY date ROWS BETWEEN 20 PRECEDING AND CURRENT ROW
                   ) * SQRT(252) AS vol_21d
            FROM log_rets
        ) src
        WHERE daily_features.date = src.date
    """, "USD/PLN rate + vol")

    run_sql(conn, """
        UPDATE daily_features
        SET eurpln = src.rate
        FROM raw_fx src
        WHERE daily_features.date = src.date
          AND src.base_currency = 'EUR' AND src.quote_currency = 'PLN'
          AND src.source = 'nbp'
    """, "EUR/PLN rate")

    # =========================================================================
    # STEP 4 — Forward-fill monthly/quarterly macro to daily
    # WHY: Monthly FRED series (CPI, unemployment) are published once per month
    # but we need a value for every trading day. Forward-filling assumes that
    # the last published value is the best estimate until the next release —
    # which is literally true: markets use the most recent CPI print until a
    # new one is released. We fill within a 92-day window max to avoid
    # propagating stale data across more than one quarter gap.
    # WHY LAST_VALUE(... IGNORE NULLS): DuckDB's window function with IGNORE
    # NULLS carries the most recent non-NULL value forward, equivalent to
    # pandas ffill() but computed in SQL without materializing an intermediate
    # DataFrame.
    # =========================================================================
    log.info("Step 4: Forward-filling macro to daily ...")

    # WHY two lists: some FRED series are already in % terms (UNRATE, FEDFUNDS,
    # DGS10) and can be forward-filled directly. Others are index levels
    # (CPIAUCSL, CPILFESL) and must be converted to YoY % before filling.
    # HICP_EA_YOY and CPI_PL_YOY from ECB/WorldBank are already YoY % — no
    # conversion needed. Mixing index levels with % features in the ML model
    # would give the regime classifier nonsensical features (CPI=252 vs VIX=20).

    # Series stored as index levels → convert to YoY % change before ffill
    cpi_yoy_series = [
        ("cpi_us_yoy",      "CPIAUCSL",  "fred"),
        ("cpi_core_us_yoy", "CPILFESL",  "fred"),
    ]

    for feature_col, series_id, source in cpi_yoy_series:
        run_sql(conn, f"""
            UPDATE daily_features
            SET {feature_col} = m.yoy_pct
            FROM (
                SELECT df.date AS spine_date,
                       (cur.value / prev.value - 1) * 100 AS yoy_pct
                FROM daily_features df
                JOIN raw_macro cur
                  ON cur.series_id = '{series_id}' AND cur.source = '{source}'
                 AND cur.date = (
                     SELECT MAX(date) FROM raw_macro
                     WHERE series_id = '{series_id}' AND source = '{source}'
                       AND date <= df.date
                 )
                JOIN raw_macro prev
                  ON prev.series_id = '{series_id}' AND prev.source = '{source}'
                 AND prev.date = (
                     SELECT MAX(date) FROM raw_macro
                     WHERE series_id = '{series_id}' AND source = '{source}'
                       AND date <= CAST(df.date AS DATE) - INTERVAL '12 months'
                 )
            ) m
            WHERE daily_features.date = m.spine_date
        """, f"YoY {feature_col}")

    # Series already in % terms → forward-fill directly
    macro_fills = [
        ("unemployment_us", "UNRATE",           "fred"),
        ("fed_funds_rate",  "FEDFUNDS",         "fred"),
        ("cpi_ea_yoy",      "HICP_EA_YOY",     "ecb"),
        ("cpi_pl_yoy",      "CPI_PL_YOY",      "econdb"),
        ("nbp_rate",        "IRSTCB01PLM156N",  "fred"),
        ("ecb_rate",        "ECB_MAIN_RATE",    "ecb"),
        ("hy_spread",       "BAMLH0A0HYM2",     "fred"),
    ]

    for feature_col, series_id, source in macro_fills:
        # WHY: DuckDB 1.5.2 LAST_VALUE IGNORE NULLS is unreliable for sparse
        # series (e.g. 20 annual rows joined to 3900 daily rows). We use a
        # correlated subquery instead: for each spine date, find the MAX macro
        # date that is <= spine date, then join on that date to get the value.
        # This is the correct forward-fill semantic: "use the most recently
        # published value as of each trading day."
        run_sql(conn, f"""
            UPDATE daily_features
            SET {feature_col} = m.value
            FROM (
                SELECT df.date AS spine_date,
                       m.value
                FROM daily_features df
                JOIN raw_macro m
                  ON m.series_id = '{series_id}'
                 AND m.source = '{source}'
                 AND m.date = (
                     SELECT MAX(m2.date)
                     FROM raw_macro m2
                     WHERE m2.series_id = '{series_id}'
                       AND m2.source = '{source}'
                       AND m2.date <= df.date
                 )
            ) m
            WHERE daily_features.date = m.spine_date
        """, f"ffill {feature_col}")

    # Rate and CPI differentials
    run_sql(conn, """
        UPDATE daily_features
        SET rate_differential = fed_funds_rate - nbp_rate,
            cpi_differential  = cpi_us_yoy - cpi_pl_yoy
        WHERE fed_funds_rate IS NOT NULL AND nbp_rate IS NOT NULL
    """, "Rate + CPI differentials")

    # Leading indicators for recession model (forward-fill from raw_macro)
    leading_fills = [
        ("sahm_indicator",  "SAHMREALTIME", "fred"),
        ("initial_claims",  "ICSA",         "fred"),
        ("housing_permits", "PERMIT",        "fred"),
    ]
    for feature_col, series_id, source in leading_fills:
        run_sql(conn, f"""
            UPDATE daily_features
            SET {feature_col} = m.value
            FROM (
                SELECT df.date AS spine_date, m.value
                FROM daily_features df
                JOIN raw_macro m
                  ON m.series_id = '{series_id}' AND m.source = '{source}'
                 AND m.date = (
                     SELECT MAX(m2.date) FROM raw_macro m2
                     WHERE m2.series_id = '{series_id}' AND m2.source = '{source}'
                       AND m2.date <= df.date
                 )
            ) m
            WHERE daily_features.date = m.spine_date
        """, f"ffill {feature_col}")

    # INDPRO: industrial production YoY % change (index level → compute YoY)
    run_sql(conn, """
        UPDATE daily_features
        SET indpro = curr.yoy
        FROM (
            SELECT df.date AS spine_date,
                   (curr_val.value / prev_val.value - 1.0) * 100 AS yoy
            FROM daily_features df
            JOIN raw_macro curr_val
              ON curr_val.series_id = 'INDPRO' AND curr_val.source = 'fred'
             AND curr_val.date = (
                 SELECT MAX(m.date) FROM raw_macro m
                 WHERE m.series_id = 'INDPRO' AND m.source = 'fred' AND m.date <= df.date
             )
            JOIN raw_macro prev_val
              ON prev_val.series_id = 'INDPRO' AND prev_val.source = 'fred'
             AND prev_val.date = (
                 SELECT MAX(m.date) FROM raw_macro m
                 WHERE m.series_id = 'INDPRO' AND m.source = 'fred'
                   AND m.date <= df.date - INTERVAL '12 months'
             )
            WHERE curr_val.value > 0 AND prev_val.value > 0
        ) curr
        WHERE daily_features.date = curr.spine_date
    """, "ffill indpro YoY")

    # GDP (quarterly → daily ffill)
    run_sql(conn, """
        UPDATE daily_features
        SET gdp_us_yoy = m.value
        FROM (
            SELECT df.date AS spine_date, m.value
            FROM daily_features df
            JOIN raw_macro m
              ON m.series_id = 'GDP' AND m.source = 'fred'
             AND m.date = (
                 SELECT MAX(m2.date) FROM raw_macro m2
                 WHERE m2.series_id = 'GDP' AND m2.source = 'fred'
                   AND m2.date <= df.date
             )
        ) m
        WHERE daily_features.date = m.spine_date
    """, "ffill GDP quarterly")

    # SP500 P/E (quarterly → daily ffill)
    run_sql(conn, """
        UPDATE daily_features
        SET sp500_pe_ratio = pe.value
        FROM (
            SELECT df.date AS spine_date, m.value
            FROM daily_features df
            JOIN raw_fundamentals m
              ON m.ticker = 'SP500' AND m.metric = 'PE_RATIO'
             AND m.date = (
                 SELECT MAX(m2.date) FROM raw_fundamentals m2
                 WHERE m2.ticker = 'SP500' AND m2.metric = 'PE_RATIO'
                   AND m2.date <= df.date
             )
        ) pe
        WHERE daily_features.date = pe.spine_date
    """, "ffill SP500 P/E")

    run_sql(conn, """
        UPDATE daily_features
        SET sp500_earnings_yield = 1.0 / sp500_pe_ratio
        WHERE sp500_pe_ratio IS NOT NULL AND sp500_pe_ratio > 0
    """, "SP500 earnings yield")

    # =========================================================================
    # STEP 5 — Sentiment
    # =========================================================================
    log.info("Step 5: Sentiment features ...")

    run_sql(conn, """
        UPDATE daily_features
        SET finnhub_sentiment = src.score
        FROM (
            SELECT date, AVG(score) AS score
            FROM raw_sentiment
            WHERE source = 'finnhub'
            GROUP BY date
        ) src
        WHERE daily_features.date = src.date
    """, "Finnhub sentiment")

    # =========================================================================
    # STEP 6 — Vol regime label
    # WHY: We bucket realized volatility into 'low'/'medium'/'high' as a
    # categorical feature alongside the continuous vol value. Tree models
    # can use the bucket directly without needing to learn the threshold
    # themselves — encoding domain knowledge (vol>20% is historically
    # associated with risk-off conditions) as a feature improves split quality.
    # =========================================================================
    log.info("Step 6: Derived flags ...")

    run_sql(conn, """
        UPDATE daily_features
        SET vol_regime = CASE
            WHEN acwi_vol_21d < 0.12 THEN 'low'
            WHEN acwi_vol_21d < 0.20 THEN 'medium'
            ELSE 'high'
        END
        WHERE acwi_vol_21d IS NOT NULL
    """, "Vol regime label")

    conn.commit()
    if _owns_conn:
        conn.close()


def report(conn=None) -> None:
    """Print coverage stats for daily_features."""
    close_after = conn is None
    if conn is None:
        conn = get_connection()

    result = conn.execute("""
        SELECT
            COUNT(*)                                            AS total_rows,
            MIN(date)                                          AS first_date,
            MAX(date)                                          AS last_date,
            COUNT(acwi_ret_1d)                                 AS acwi_ret,
            COUNT(vix_close)                                   AS vix,
            COUNT(yield_10y)                                   AS yield_10y,
            COUNT(usdpln)                                      AS usdpln,
            COUNT(cpi_us_yoy)                                  AS cpi_us,
            COUNT(cpi_pl_yoy)                                  AS cpi_pl,
            COUNT(nbp_rate)                                    AS nbp_rate,
            COUNT(acwi_pln_ret_1d)                             AS acwi_pln,
            COUNT(sp500_pe_ratio)                              AS pe_ratio,
            COUNT(finnhub_sentiment)                           AS sentiment
        FROM daily_features
    """).fetchone()

    labels = [
        "total_rows", "first_date", "last_date",
        "acwi_ret_1d", "vix_close", "yield_10y", "usdpln",
        "cpi_us_yoy", "cpi_pl_yoy", "nbp_rate",
        "acwi_pln_ret_1d", "sp500_pe_ratio", "finnhub_sentiment",
    ]
    log.info("daily_features coverage:")
    for label, val in zip(labels, result):
        log.info("  %-25s %s", label, val)

    if close_after:
        conn.close()


if __name__ == "__main__":
    log.info("=== Building daily_features ===")
    build_features()
    report()
    log.info("Done.")
