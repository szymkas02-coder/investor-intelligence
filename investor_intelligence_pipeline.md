# Investor Intelligence System — Project Pipeline

**Goal:** Build a full end-to-end personal investment intelligence platform covering data ingestion, SQL warehousing, cloud infrastructure, ML modeling, React frontend, and Google OAuth authentication. Grounded in personal investment relevance (IKE/ACWI ETF strategy, PLN exposure, Polish market) and serves as a structured learning vehicle for SQL, cloud, and production ML.

**Primary learning targets:** SQL (DuckDB), cloud infrastructure (GCP free tier), financial data engineering.
**Secondary:** Regime classification ML, volatility forecasting, currency risk modeling, React + FastAPI full-stack.
**Optional extensions:** Portfolio optimizer integration, multi-user support, mobile-responsive design.

---

## Philosophy

**"Help a long-term passive investor make fewer bad decisions, not more frequent ones."**

This app is fundamentally different from typical finance dashboards that maximize engagement through constant alerts and stock tips. The goal is the opposite: give enough context to act confidently when action is warranted, and clearly signal when the right move is to do nothing.

**The app is for:**
- Monthly IKE contribution decisions — lump sum now, or spread it?
- Rebalancing checks — has my allocation drifted enough to act?
- Macro context — what environment am I investing into right now?
- Long-term projection — am I on track given my contribution pace?
- Post-decision review — was my timing good or did I just get lucky?

**The app is explicitly not for:**
- Stock picking or individual company analysis
- Short-term price prediction or trading signals
- Crypto trading
- Anything that encourages checking more than once a month

This distinction is intentional and should be visible in the UI: *"Designed for monthly decisions, not daily ones."*

---

## Architecture Overview

```
Data Sources (12 APIs — all free or free tier)
    │
    ├── yfinance              (ETFs, indices, bonds, gold — no key)
    ├── FRED API              (US + global macro: CPI, GDP, yield curve, Fed rate)
    ├── NBP API               (PLN/USD/EUR official exchange rates — no key)
    ├── ECB SDW API           (EUR macro: HICP, ECB rate, EA yield curve — no key)
    ├── Econdb                (Polish macro: CPI, unemployment, GDP, NBP rate — no key)
    ├── Frankfurter           (historical FX cross rates — no key)
    ├── Finnhub               (news sentiment, economic calendar — apiKey)
    ├── SEC EDGAR             (US company fundamentals, S&P500 P/E — no key)
    ├── STOOQ                 (Polish/European historical market data — no key)
    ├── CoinGecko             (BTC/ETH as risk-on proxy — no key)
    ├── WallStreetBets API    (Reddit retail sentiment — no key)
    └── pytrends              (Google Trends — search-based sentiment — no key)
    │
    ▼
Ingestion Layer (Python, GCP Cloud Functions, scheduled via Cloud Scheduler)
    │
    ▼
Storage Layer (DuckDB — local dev + GCP Cloud Storage backup as Parquet)
    │
    ├── Raw tables            (one per source, append-only, never modified)
    ├── Processed tables      (aligned, QC-filtered, feature-engineered)
    └── User tables           (portfolio positions, transactions, preferences)
    │
    ▼
ML Intelligence Layer
    │
    ├── Regime Classifier     (LightGBM — risk-on / risk-off / stagflation / deflation)
    ├── Volatility Forecaster (Random Forest — 21-day realized vol for ACWI)
    └── Currency Risk Model   (LightGBM quantile — PLN/USD 63-day expected range)
    │
    ▼
Backend (FastAPI — REST API with JWT auth)
    │
    ▼
Frontend (React + Vite + Recharts — deployed on GCP Cloud Run)
    │
    ├── [Public]  Macro Overview      (yield curve, CPI, regime badge)
    ├── [Public]  Market Context      (volatility, sentiment, economic calendar)
    ├── [Auth]    Decision Center     (should I invest this month?)
    ├── [Auth]    My Portfolio        (positions, P&L, FX decomposition)
    ├── [Auth]    Contribution Log    (transaction history, IKE tracker)
    ├── [Auth]    Scenario Planner    (what-if analysis, long-term projection)
    └── [Auth]    Historical Explorer (SQL-backed, filterable)
```

---

## Data Sources — Full Catalog

### 1. yfinance
**What:** Unofficial Yahoo Finance wrapper. Price, volume, dividends for virtually any ticker.
**Auth:** None.

| Ticker | Asset | Why |
|--------|-------|-----|
| `ACWI` | iShares MSCI ACWI ETF | Core IKE holding |
| `VWCE.DE` | Vanguard FTSE All-World (EUR) | European ACWI equivalent |
| `SPY` | S&P 500 ETF | US benchmark |
| `^GSPC` | S&P 500 index | Index level |
| `^VIX` | CBOE Volatility Index | Fear gauge |
| `^WIG` | WIG broad market index | Polish market |
| `TLT` | iShares 20+ Year Treasury ETF | Long bonds |
| `SHY` | iShares 1-3 Year Treasury ETF | Short bonds |
| `GLD` | SPDR Gold ETF | Gold |
| `DX-Y.NYB` | US Dollar Index (DXY) | USD strength |
| `EURUSD=X` | EUR/USD | EUR exposure |
| `USDPLN=X` | USD/PLN | Direct PLN risk |
| `^TNX` | 10-year Treasury yield | Yield curve anchor |
| `^IRX` | 3-month T-Bill yield | Short end of curve |

**Notes:** Cache aggressively. Pull full historical data once; append incrementally.

---

### 2. FRED API (Federal Reserve Bank of St. Louis)
**What:** Gold standard for US and international macro data. 800,000+ series.
**Auth:** apiKey (free, register at fred.stlouisfed.org)

| Series ID | Description | Frequency |
|-----------|-------------|-----------|
| `CPIAUCSL` | US CPI All Items | Monthly |
| `CPILFESL` | US Core CPI (ex food/energy) | Monthly |
| `UNRATE` | US Unemployment Rate | Monthly |
| `GDP` | US GDP | Quarterly |
| `FEDFUNDS` | Fed Funds Rate | Monthly |
| `DGS10` | 10-Year Treasury Yield | Daily |
| `DGS2` | 2-Year Treasury Yield | Daily |
| `DGS3MO` | 3-Month Treasury Yield | Daily |
| `T10Y2Y` | 10Y-2Y Spread (yield curve) | Daily |
| `T10Y3M` | 10Y-3M Spread (recession signal) | Daily |
| `BAMLH0A0HYM2` | High Yield Spread (credit risk) | Daily |
| `UMCSENT` | U Michigan Consumer Sentiment | Monthly |
| `VIXCLS` | VIX closing price | Daily |
| `DTWEXBGS` | USD trade-weighted index | Daily |

---

### 3. NBP API (National Bank of Poland)
**What:** Official Polish central bank REST API. Exchange rates.
**Auth:** None. CORS enabled. Reliable and stable.
**Base URL:** `http://api.nbp.pl/api/`

| Endpoint | Data |
|----------|------|
| `/exchangerates/rates/a/usd/{start}/{end}/` | USD/PLN historical |
| `/exchangerates/rates/a/eur/{start}/{end}/` | EUR/PLN historical |
| `/exchangerates/tables/a/` | All Table A currencies |

**Notes:** Max 93-day range per request — loop over years.

---

### 4. ECB Statistical Data Warehouse (SDW) API
**What:** European Central Bank official data.
**Auth:** None.
**Base URL:** `https://data-api.ecb.europa.eu/service/data/`

| Dataset | Series Key | Description |
|---------|-----------|-------------|
| `ICP` | `M.U2.N.000000.4.ANR` | EA HICP inflation (YoY) |
| `FM` | `B.U2.EUR.4F.KR.MRR_FR.LEV` | ECB Main Refinancing Rate |
| `YC` | `B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y` | EA 10Y sovereign yield |
| `YC` | `B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y` | EA 2Y sovereign yield |

---

### 5. Econdb
**What:** Global macro aggregator — covers Poland (GUS-sourced).
**Auth:** None.
**Base URL:** `https://www.econdb.com/api/series/`

| Ticker | Description |
|--------|-------------|
| `CPIPLPOL` | Poland CPI |
| `UNRATEPOL` | Poland Unemployment |
| `GDPPOL` | Poland GDP |
| `IRATEPOL` | Poland NBP Reference Rate |

---

### 6. Frankfurter API
**What:** ECB-sourced exchange rates with full history. Clean, no key needed.
**Auth:** None.
**Base URL:** `https://api.frankfurter.app/`

```
GET https://api.frankfurter.app/2005-01-01..2025-12-31?from=USD&to=PLN
```

**Notes:** Complements NBP with EUR-centric rates for PLN/EUR/USD triangulation.

---

### 7. Finnhub
**What:** News sentiment, earnings calendar, economic events.
**Auth:** apiKey (free tier: 60 calls/minute)
**Base URL:** `https://finnhub.io/api/v1/`

| Endpoint | Data |
|----------|------|
| `/news?category=general` | Market news feed |
| `/calendar/earnings` | Earnings calendar |
| `/calendar/economic` | Economic events (FOMC, CPI release dates) |
| `/news-sentiment?symbol=ACWI` | Sentiment score |

---

### 8. SEC EDGAR
**What:** US public company filings and aggregate fundamentals.
**Auth:** None. Set User-Agent header with email.
**Base URL:** `https://data.sec.gov/`

| Endpoint | Data |
|----------|------|
| `/api/xbrl/companyfacts/CIK{cik}.json` | Structured financials |
| `/api/xbrl/frames/us-gaap/EPS/USD/CY2024Q4I.json` | Cross-company snapshots |

**Notes:** Used for S&P 500 aggregate P/E ratio and earnings yield.

---

### 9. STOOQ
**What:** Polish/European historical market data.
**Auth:** None.
**Base URL:** `https://stooq.com/q/d/l/`

| Ticker | Asset |
|--------|-------|
| `wig20` | WIG20 index |
| `wig` | WIG broad market |
| `usdpln` | USD/PLN |
| `eurpln` | EUR/PLN |
| `dax` | German DAX |

```python
url = "https://stooq.com/q/d/l/?s=wig20&i=d"
df = pd.read_csv(url)
```

**Notes:** More reliable than yfinance for Polish tickers. No rate limiting observed.

---

### 10. CoinGecko
**What:** Cryptocurrency market data — BTC/ETH as risk-on proxies only.
**Auth:** None (30 calls/min).
**Base URL:** `https://api.coingecko.com/api/v3/`

```
GET /coins/bitcoin/market_chart?vs_currency=usd&days=1825
```

**Notes:** BTC/SPY rolling correlation is a useful regime feature. This is NOT a crypto dashboard — crypto is a market sentiment proxy only.

---

### 11. WallStreetBets Sentiment API
**What:** Reddit WSB mention counts and sentiment scores.
**Auth:** None.
**Base URL:** `https://dashboard.nbshare.io/apps/reddit/api/`

**Notes:** Useful as contrarian indicator only. Extreme retail bullishness historically precedes corrections. Low weight in ML features.

---

### 12. pytrends (Google Trends)
**What:** Search interest over time for keywords.
**Auth:** None.

```python
from pytrends.request import TrendReq
pytrends = TrendReq()
pytrends.build_payload(["recession", "stock market crash", "buy stocks", "ETF invest"])
df = pytrends.interest_over_time()
```

**Notes:** Weekly granularity only. "Recession" search spikes lead actual downturns by 2–4 weeks.

---

## Schema Design (DuckDB)

### Raw Tables (append-only, never modified)

```sql
-- Price/volume data from yfinance and STOOQ
CREATE TABLE raw_prices (
    date            DATE        NOT NULL,
    ticker          VARCHAR     NOT NULL,
    source          VARCHAR     NOT NULL,
    open            DOUBLE,
    high            DOUBLE,
    low             DOUBLE,
    close           DOUBLE,
    adj_close       DOUBLE,
    volume          BIGINT,
    ingested_at     TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (date, ticker, source)
);

-- Macro indicators from FRED, ECB SDW, Econdb
CREATE TABLE raw_macro (
    date            DATE        NOT NULL,
    series_id       VARCHAR     NOT NULL,
    source          VARCHAR     NOT NULL,   -- 'fred', 'ecb', 'econdb'
    value           DOUBLE,
    frequency       VARCHAR,                -- 'daily', 'monthly', 'quarterly'
    ingested_at     TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (date, series_id, source)
);

-- Exchange rates from NBP, Frankfurter
CREATE TABLE raw_fx (
    date            DATE        NOT NULL,
    base_currency   VARCHAR     NOT NULL,
    quote_currency  VARCHAR     NOT NULL,
    rate            DOUBLE      NOT NULL,
    source          VARCHAR     NOT NULL,   -- 'nbp', 'frankfurter'
    ingested_at     TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (date, base_currency, quote_currency, source)
);

-- Sentiment signals from Finnhub, WSB, pytrends
CREATE TABLE raw_sentiment (
    date            DATE        NOT NULL,
    source          VARCHAR     NOT NULL,   -- 'finnhub', 'wsb', 'gtrends'
    ticker          VARCHAR,
    keyword         VARCHAR,
    score           DOUBLE,
    buzz            DOUBLE,
    metadata        JSON,
    ingested_at     TIMESTAMPTZ DEFAULT now()
);

-- SEC EDGAR fundamentals
CREATE TABLE raw_fundamentals (
    date            DATE        NOT NULL,
    ticker          VARCHAR     NOT NULL,
    metric          VARCHAR     NOT NULL,   -- 'EPS', 'PE', 'earnings_yield'
    value           DOUBLE,
    unit            VARCHAR,
    source          VARCHAR     DEFAULT 'sec_edgar',
    ingested_at     TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (date, ticker, metric)
);

-- Crypto from CoinGecko
CREATE TABLE raw_crypto (
    date            DATE        NOT NULL,
    coin_id         VARCHAR     NOT NULL,   -- 'bitcoin', 'ethereum'
    price_usd       DOUBLE,
    market_cap_usd  DOUBLE,
    volume_usd      DOUBLE,
    ingested_at     TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (date, coin_id)
);

-- Economic calendar from Finnhub
CREATE TABLE raw_calendar_events (
    date            DATE        NOT NULL,
    event_name      VARCHAR     NOT NULL,
    country         VARCHAR,
    importance      VARCHAR,                -- 'high', 'medium', 'low'
    actual          DOUBLE,
    estimate        DOUBLE,
    ingested_at     TIMESTAMPTZ DEFAULT now()
);

-- QC log
CREATE TABLE raw_qc_log (
    checked_at      TIMESTAMPTZ DEFAULT now(),
    check_name      VARCHAR     NOT NULL,
    table_name      VARCHAR     NOT NULL,
    issue_count     INTEGER,
    details         VARCHAR
);
```

### Processed / Analytical Tables

```sql
-- Master daily feature table (ML input)
CREATE TABLE daily_features (
    date                    DATE    PRIMARY KEY,

    -- Price returns (log returns)
    acwi_ret_1d             DOUBLE,
    acwi_ret_5d             DOUBLE,
    acwi_ret_21d            DOUBLE,
    acwi_ret_63d            DOUBLE,
    spy_ret_1d              DOUBLE,
    wig20_ret_1d            DOUBLE,
    gold_ret_1d             DOUBLE,
    tlt_ret_1d              DOUBLE,

    -- Volatility
    acwi_vol_21d            DOUBLE,
    acwi_vol_63d            DOUBLE,
    vix_close               DOUBLE,
    vix_change_5d           DOUBLE,

    -- Yield curve
    yield_10y               DOUBLE,
    yield_2y                DOUBLE,
    yield_3m                DOUBLE,
    spread_10y_2y           DOUBLE,
    spread_10y_3m           DOUBLE,
    ecb_rate_10y            DOUBLE,

    -- Macro (forward-filled from monthly/quarterly)
    cpi_us_yoy              DOUBLE,
    cpi_core_us_yoy         DOUBLE,
    cpi_ea_yoy              DOUBLE,
    cpi_pl_yoy              DOUBLE,
    unemployment_us         DOUBLE,
    fed_funds_rate          DOUBLE,
    ecb_rate                DOUBLE,
    nbp_rate                DOUBLE,
    gdp_us_yoy              DOUBLE,
    rate_differential       DOUBLE,        -- fed_funds_rate - nbp_rate
    cpi_differential        DOUBLE,        -- cpi_us_yoy - cpi_pl_yoy

    -- FX (PLN exposure)
    usdpln                  DOUBLE,
    eurpln                  DOUBLE,
    usdpln_ret_21d          DOUBLE,
    usdpln_vol_21d          DOUBLE,
    dxy_close               DOUBLE,

    -- Credit / risk
    hy_spread               DOUBLE,
    btc_ret_21d             DOUBLE,
    btc_spy_corr_21d        DOUBLE,

    -- Sentiment
    finnhub_sentiment       DOUBLE,
    wsb_bullish_ratio       DOUBLE,
    gtrends_recession       DOUBLE,
    gtrends_invest          DOUBLE,

    -- Fundamentals (quarterly, forward-filled)
    sp500_pe_ratio          DOUBLE,
    sp500_earnings_yield    DOUBLE,

    -- Derived
    acwi_pln_ret_1d         DOUBLE,
    acwi_pln_ret_21d        DOUBLE,
    yield_curve_inverted    BOOLEAN,
    vol_regime              VARCHAR,       -- 'low' / 'medium' / 'high'

    updated_at              TIMESTAMPTZ DEFAULT now()
);

-- Regime labels (ground truth for ML training)
CREATE TABLE regime_labels (
    date            DATE    PRIMARY KEY,
    regime          VARCHAR NOT NULL,      -- 'risk_on', 'risk_off', 'stagflation', 'deflation'
    label_source    VARCHAR,               -- 'rule_based', 'manual'
    confidence      DOUBLE,
    notes           VARCHAR
);

-- Regime predictions (ML output)
CREATE TABLE regime_predictions (
    date                DATE        NOT NULL,
    model_version       VARCHAR     NOT NULL,
    regime_pred         VARCHAR     NOT NULL,
    prob_risk_on        DOUBLE,
    prob_risk_off       DOUBLE,
    prob_stagflation    DOUBLE,
    prob_deflation      DOUBLE,
    predicted_at        TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (date, model_version)
);

-- Volatility forecasts
CREATE TABLE volatility_forecasts (
    date            DATE        NOT NULL,
    model_version   VARCHAR     NOT NULL,
    ticker          VARCHAR     NOT NULL,
    horizon_days    INTEGER     NOT NULL,
    vol_forecast    DOUBLE,
    vol_lower       DOUBLE,
    vol_upper       DOUBLE,
    predicted_at    TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (date, model_version, ticker, horizon_days)
);

-- PLN/USD currency risk forecasts
CREATE TABLE fx_forecasts (
    date            DATE        NOT NULL,
    model_version   VARCHAR     NOT NULL,
    pair            VARCHAR     NOT NULL,
    horizon_days    INTEGER     NOT NULL,
    rate_point      DOUBLE,
    rate_lower      DOUBLE,                -- 10th percentile
    rate_upper      DOUBLE,                -- 90th percentile
    predicted_at    TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (date, model_version, pair, horizon_days)
);

-- Model evaluation log
CREATE TABLE model_eval_log (
    eval_date           DATE        NOT NULL,
    model_name          VARCHAR     NOT NULL,
    metric              VARCHAR     NOT NULL,
    value               DOUBLE,
    eval_window_days    INTEGER,
    PRIMARY KEY (eval_date, model_name, metric)
);
```

### User Tables (portfolio + auth)

```sql
-- User accounts (Google OAuth)
CREATE TABLE users (
    user_id         VARCHAR     PRIMARY KEY,  -- Google OAuth sub
    email           VARCHAR     NOT NULL,
    display_name    VARCHAR,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- Portfolio positions (what user holds)
CREATE TABLE user_positions (
    user_id         VARCHAR     NOT NULL,
    ticker          VARCHAR     NOT NULL,
    shares          DOUBLE      NOT NULL,
    avg_cost_pln    DOUBLE      NOT NULL,   -- weighted average cost in PLN
    avg_cost_usdpln DOUBLE,                 -- USD/PLN rate at average cost
    account_type    VARCHAR     DEFAULT 'IKE',  -- 'IKE', 'IKZE', 'regular'
    opened_at       DATE        NOT NULL,
    updated_at      TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (user_id, ticker, account_type)
);

-- Transaction log (every buy/sell/dividend)
CREATE TABLE user_transactions (
    transaction_id  VARCHAR     PRIMARY KEY,
    user_id         VARCHAR     NOT NULL,
    ticker          VARCHAR     NOT NULL,
    date            DATE        NOT NULL,
    type            VARCHAR     NOT NULL,   -- 'buy', 'sell', 'dividend'
    shares          DOUBLE      NOT NULL,
    price_pln       DOUBLE      NOT NULL,
    usdpln_rate     DOUBLE,
    account_type    VARCHAR     DEFAULT 'IKE',
    notes           VARCHAR,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- IKE annual contribution tracker
CREATE TABLE ike_contributions (
    user_id         VARCHAR     NOT NULL,
    year            INTEGER     NOT NULL,
    contributed_pln DOUBLE      DEFAULT 0,
    limit_pln       DOUBLE,                 -- annual IKE limit for that year
    PRIMARY KEY (user_id, year)
);

-- Investment preferences
CREATE TABLE user_preferences (
    user_id                 VARCHAR PRIMARY KEY,
    risk_tolerance          VARCHAR,    -- 'conservative', 'moderate', 'aggressive'
    investment_horizon_yrs  INTEGER,
    monthly_budget_pln      DOUBLE,
    target_allocation       JSON,       -- e.g. {"ACWI": 0.8, "GLD": 0.2}
    updated_at              TIMESTAMPTZ DEFAULT now()
);

-- Decision log (recommendations + what user actually did)
CREATE TABLE decision_log (
    decision_id     VARCHAR     PRIMARY KEY,
    user_id         VARCHAR     NOT NULL,
    date            DATE        NOT NULL,
    regime_at_time  VARCHAR,
    vol_at_time     DOUBLE,
    usdpln_at_time  DOUBLE,
    recommendation  VARCHAR,            -- 'lump_sum', 'dca', 'hold', 'rebalance'
    rationale       JSON,
    user_action     VARCHAR,
    created_at      TIMESTAMPTZ DEFAULT now()
);
```

### Key SQL Queries to Learn Through This Project

```sql
-- 1. Rolling 21-day realized volatility (annualized)
SELECT date, ticker,
       STDDEV(log_return) OVER (
           PARTITION BY ticker
           ORDER BY date
           ROWS BETWEEN 20 PRECEDING AND CURRENT ROW
       ) * SQRT(252) AS realized_vol_21d
FROM (
    SELECT date, ticker,
           LN(adj_close / LAG(adj_close) OVER (
               PARTITION BY ticker ORDER BY date
           )) AS log_return
    FROM raw_prices
);

-- 2. Yield curve inversion detection
SELECT date,
       yield_10y - yield_3m AS spread_10y3m,
       CASE WHEN yield_10y - yield_3m < 0 THEN TRUE ELSE FALSE END AS inverted,
       COUNT(*) FILTER (WHERE yield_10y - yield_3m < 0)
           OVER (ORDER BY date ROWS BETWEEN 62 PRECEDING AND CURRENT ROW)
           AS inversion_days_63d
FROM daily_features;

-- 3. ACWI return in PLN terms (actual investor experience)
SELECT p.date,
       p.adj_close * f.rate AS acwi_pln,
       LN(p.adj_close * f.rate /
          LAG(p.adj_close * f.rate, 21) OVER (ORDER BY p.date))
                            AS acwi_pln_ret_21d
FROM raw_prices p
JOIN raw_fx f
  ON p.date = f.date
 AND f.base_currency = 'USD' AND f.quote_currency = 'PLN'
WHERE p.ticker = 'ACWI';

-- 4. Rule-based regime labeling (ML training labels)
SELECT date,
       CASE
           WHEN cpi_us_yoy > 3.5 AND spread_10y_2y > 0   THEN 'stagflation'
           WHEN cpi_us_yoy > 3.5 AND spread_10y_2y < 0   THEN 'risk_off'
           WHEN spread_10y_3m < -0.5 AND vix_close > 25  THEN 'risk_off'
           WHEN vix_close < 18 AND acwi_ret_63d > 0.05   THEN 'risk_on'
           WHEN cpi_us_yoy < 1.5 AND acwi_ret_63d < -0.05 THEN 'deflation'
           ELSE 'risk_on'
       END AS regime_rule_based
FROM daily_features;

-- 5. Rolling BTC-SPY correlation (risk-on proxy)
WITH returns AS (
    SELECT date, ticker,
           LN(adj_close / LAG(adj_close) OVER (PARTITION BY ticker ORDER BY date)) AS ret
    FROM raw_prices WHERE ticker IN ('SPY', 'BTC-USD')
),
pivoted AS (
    SELECT date,
           MAX(ret) FILTER (WHERE ticker = 'SPY')     AS spy_ret,
           MAX(ret) FILTER (WHERE ticker = 'BTC-USD') AS btc_ret
    FROM returns GROUP BY date
)
SELECT date,
       CORR(spy_ret, btc_ret) OVER (
           ORDER BY date ROWS BETWEEN 20 PRECEDING AND CURRENT ROW
       ) AS btc_spy_corr_21d
FROM pivoted;

-- 6. FX decomposition of portfolio P&L
-- total_pnl = asset_pnl + fx_pnl
SELECT user_id, ticker,
       shares * (current_price_usd - avg_cost_pln / avg_cost_usdpln)
           * current_usdpln                            AS asset_pnl_pln,
       shares * (avg_cost_pln / avg_cost_usdpln)
           * (current_usdpln - avg_cost_usdpln)        AS fx_pnl_pln
FROM user_positions
JOIN (SELECT adj_close AS current_price_usd, ticker
      FROM raw_prices WHERE date = CURRENT_DATE) prices USING (ticker)
JOIN (SELECT rate AS current_usdpln FROM raw_fx
      WHERE date = CURRENT_DATE
        AND base_currency = 'USD' AND quote_currency = 'PLN') fx ON TRUE;

-- 7. Regime-conditional return statistics
SELECT r.regime,
       COUNT(*)                                          AS trading_days,
       AVG(f.acwi_ret_1d) * 252                         AS annualized_return,
       STDDEV(f.acwi_ret_1d) * SQRT(252)                AS annualized_vol,
       AVG(f.acwi_ret_1d) /
           NULLIF(STDDEV(f.acwi_ret_1d), 0) * SQRT(252) AS sharpe,
       MIN(f.acwi_ret_1d)                               AS worst_day
FROM daily_features f
JOIN regime_labels r USING (date)
GROUP BY r.regime
ORDER BY annualized_return DESC;

-- 8. IKE contribution headroom
SELECT user_id, year,
       limit_pln - contributed_pln       AS remaining_pln,
       contributed_pln / limit_pln * 100 AS pct_used
FROM ike_contributions
WHERE year = EXTRACT(YEAR FROM CURRENT_DATE);

-- 9. QC: detect stale data
SELECT 'raw_prices' AS table_name,
       MAX(date)    AS latest_date,
       CURRENT_DATE - MAX(date) AS days_behind
FROM raw_prices WHERE ticker = 'ACWI';
```

---

## Phase 3 — Cloud Infrastructure (GCP Free Tier)

### GCP Services

| Service | Purpose | Free tier |
|---------|---------|-----------|
| Cloud Functions (Gen 2) | Run ingestion on schedule | 2M invocations/month |
| Cloud Scheduler | Cron triggers | 3 jobs free |
| Cloud Storage | DuckDB Parquet backup, model artifacts | 5 GB free |
| Cloud Run | Host backend + frontend | 2M requests/month |
| Secret Manager | Store API keys | 6 secrets free |
| Identity Platform | Google OAuth | 10K MAU free |

### Scheduling Strategy

```yaml
- name: daily-prices       # after US market close
  schedule: "0 22 * * 1-5"
  timezone: Europe/Warsaw

- name: daily-macro        # overnight FRED updates
  schedule: "0 8 * * *"
  timezone: Europe/Warsaw

- name: daily-sentiment
  schedule: "0 20 * * 1-5"
  timezone: Europe/Warsaw

- name: weekly-fundamentals  # SEC EDGAR
  schedule: "0 10 * * 0"
  timezone: Europe/Warsaw

- name: daily-ml           # after all ingestion complete
  schedule: "0 23 * * 1-5"
  timezone: Europe/Warsaw
```

---

## Phase 4 — ML Intelligence Layer

### Model 1: Regime Classifier

**Task:** Classify market into `risk_on` / `risk_off` / `stagflation` / `deflation`.
**Labels:** Rule-based SQL, manually reviewed for 2008 GFC, 2020 COVID, 2022 inflation shock.
**Model:** LightGBM multiclass. Nested CV: outer 5-fold TimeSeriesSplit + inner 3-fold HPO.
Same architecture as master's thesis Random Forest — directly transferable skill.
**Output:** Regime label + class probabilities + SHAP values.

| Feature group | Variables |
|---|---|
| Yield curve | `spread_10y_2y`, `spread_10y_3m`, `inversion_days_63d` |
| Inflation | `cpi_us_yoy`, `cpi_core_us_yoy`, `cpi_ea_yoy`, `cpi_differential` |
| Risk | `vix_close`, `vix_change_5d`, `hy_spread`, `acwi_vol_21d` |
| Momentum | `acwi_ret_21d`, `acwi_ret_63d`, `gold_ret_1d`, `tlt_ret_1d` |
| Sentiment | `finnhub_sentiment`, `wsb_bullish_ratio`, `gtrends_recession` |
| Crypto proxy | `btc_ret_21d`, `btc_spy_corr_21d` |
| FX | `dxy_close`, `usdpln`, `rate_differential` |

### Model 2: Volatility Forecaster

**Task:** Predict 21-day realized volatility for ACWI (annualized).
**Target:** `acwi_vol_21d` shifted 21 days forward.
**Model:** Random Forest regressor. Evaluation: MAE, RMSE on TimeSeriesSplit folds.
**Decision use:** vol > 20% → DCA suggested; vol < 15% → lump sum favorable.

### Model 3: PLN/USD Currency Risk Model

**Task:** Predict 63-day range (10th–90th percentile) for USD/PLN.
**Model:** LightGBM with `objective='quantile'`.
**Features:** Current USD/PLN, EUR/PLN, DXY, NBP rate, Fed rate, rate differential, CPI differential.
**Decision use:** If 90th percentile > 4.30, consider EUR-hedged ETF instead of USD-denominated.

---

## Phase 5 — Backend (FastAPI)

### API Endpoints

```
Public (no auth required):
  GET /features?start=&end=           → daily_features time range
  GET /regime/latest                  → current regime + probabilities
  GET /regime/history?start=&end=     → regime labels over time
  GET /volatility?ticker=&horizon=    → volatility forecast with bands
  GET /fx/forecast?pair=&horizon=     → PLN/USD fan chart data

Protected (JWT required):
  GET  /portfolio/positions           → holdings with live PLN value
  GET  /portfolio/pnl                 → P&L with FX decomposition
  GET  /portfolio/ike?year=           → IKE contribution tracker
  GET  /portfolio/performance         → returns vs ACWI benchmark
  POST /portfolio/transaction         → log a buy/sell event
  POST /portfolio/preferences         → save risk tolerance, budget
  GET  /decisions/current             → recommendation + plain rationale
  POST /decisions/log                 → log what user actually decided
  GET  /projection?monthly_pln=&years=&scenario=  → growth projection

Auth:
  GET  /auth/login                    → redirect to Google OAuth
  GET  /auth/callback                 → exchange code for JWT
  GET  /auth/me                       → current user info from token
```

### Decision Engine (rule-based — intentionally not ML)

```python
def generate_recommendation(regime, vol_forecast, usdpln_upper,
                             ike_remaining, budget):
    # Core action
    if regime in ('risk_off', 'stagflation') or vol_forecast > 0.22:
        action = 'dca'
    elif regime == 'risk_on' and vol_forecast < 0.15:
        action = 'lump_sum'
    else:
        action = 'dca'  # default to cautious

    # Plain-language rationale
    rationale = []
    if regime == 'risk_off':
        rationale.append("Market regime is RISK OFF — historically poor lump sum timing.")
    if vol_forecast > 0.22:
        rationale.append(f"Predicted volatility {vol_forecast:.0%} is elevated (>22%).")
    if usdpln_upper > 4.30:
        rationale.append(f"PLN/USD 90th percentile {usdpln_upper:.2f} — wide FX uncertainty.")
    if ike_remaining < budget:
        rationale.append(f"Only {ike_remaining:.0f} PLN left in IKE limit this year.")

    return {"recommendation": action, "rationale": rationale}
```

---

## Phase 6 — Frontend (React + Vite)

### Pages

**1. Macro Overview** (public)
- Yield curve shape: 3M / 2Y / 10Y spot plot (Recharts)
- CPI trend: US, EA, PL on one chart
- Regime badge: `RISK ON 🟢` / `RISK OFF 🔴` / `STAGFLATION 🟡` / `DEFLATION 🔵`
- Regime probability bar chart
- Google Trends: "recession" vs "buy stocks" contrarian signal

**2. Decision Center** (auth) — the most important screen
- Single clear signal: `INVEST NOW` / `DCA OVER 3 MONTHS` / `HOLD`
- Plain-language rationale — no jargon, no charts on this screen
- IKE headroom indicator (PLN remaining this year)
- Button to log what you actually decided

**3. My Portfolio** (auth)
- Holdings table: ticker, shares, avg cost PLN, current value PLN
- P&L with FX decomposition (asset component vs currency component)
- Allocation pie chart vs target allocation
- Rebalancing alert if any position drifts > 5% from target

**4. Contribution Log** (auth)
- Transaction history table with filters
- IKE annual contribution progress bar
- Performance vs buy-and-hold ACWI benchmark (returns in PLN)

**5. Scenario Planner** (auth)
- Monthly contribution input (PLN)
- Three growth curves: pessimistic (5%) / base (8%) / optimistic (10%)
- Milestones: year to first 100k, 500k, 1M PLN
- Equivalent monthly passive income at 4% withdrawal rate

**6. Historical Explorer** (auth)
- SQL-backed filterable table: date range, asset, regime
- Regime-conditional return statistics
- CSV download

### Key Tech Decisions

| Decision | Choice | Why |
|---|---|---|
| Build tool | Vite | Modern standard, faster than CRA |
| JWT storage | Memory (not localStorage) | XSS attack protection |
| Token injection | Axios interceptors | Automatic, not manual per-request |
| Charts | Recharts | Native React, good docs |
| Routing | React Router v6 | Current standard |
| Auth gate | ProtectedRoute component | Clean separation of public/private |

---

## Phase 7 — Auth + Deployment

### Authentication Flow

```
1. User clicks "Sign in with Google"
2. Frontend → GET /auth/login
3. Backend redirects to Google OAuth consent screen
4. Google → GET /auth/callback?code=...
5. Backend exchanges code for Google ID token
6. Backend issues its own signed JWT (24h expiry)
7. Frontend stores JWT in memory (React AuthProvider context)
8. Every API request includes: Authorization: Bearer <jwt>
9. Backend verifies JWT signature on every protected endpoint
```

### Dockerization

```dockerfile
# backend/Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]

# frontend/Dockerfile (two-stage build)
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json .
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

### GCP Deployment Notes
- Backend: Cloud Run — stateless, reads Parquet from GCS
- Frontend: Cloud Run or Firebase Hosting
- Secrets: GCP Secret Manager — FRED key, Finnhub key, JWT secret, Google OAuth credentials
- Rule: secrets never appear in Dockerfile or git history

---

## Repository Structure

```
investor_intelligence/
├── README.md                       # "Designed for monthly decisions, not daily ones."
├── ingestion/
│   ├── prices.py                   # yfinance + STOOQ
│   ├── macro.py                    # FRED + ECB SDW + Econdb
│   ├── fx.py                       # NBP + Frankfurter
│   ├── sentiment.py                # Finnhub + WSB + pytrends
│   ├── fundamentals.py             # SEC EDGAR
│   ├── crypto.py                   # CoinGecko
│   └── pipeline.py                 # Orchestrates all sources
├── processing/
│   ├── qc.py                       # Data quality checks → raw_qc_log
│   ├── align.py                    # Daily alignment, forward-fill
│   ├── features.py                 # Build daily_features via SQL
│   ├── labels.py                   # Rule-based regime labeling
│   └── portfolio.py                # PLN-adjusted portfolio valuation
├── ml/
│   ├── regime.py                   # LightGBM multiclass + nested CV
│   ├── volatility.py               # Random Forest vol forecaster
│   ├── currency.py                 # LightGBM quantile PLN/USD
│   └── evaluate.py                 # Evaluation → model_eval_log
├── db/
│   ├── schema.sql                  # All CREATE TABLE statements
│   └── queries.py                  # Named queries as Python functions
├── backend/
│   ├── main.py
│   ├── routers/
│   │   ├── features.py
│   │   ├── regime.py
│   │   ├── portfolio.py
│   │   ├── volatility.py
│   │   ├── decisions.py            # Recommendation engine
│   │   ├── projection.py           # Long-term growth projection
│   │   └── auth.py                 # Google OAuth + JWT
│   ├── dependencies.py             # Shared DuckDB conn, get_current_user()
│   ├── schemas.py                  # Pydantic response models
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── main.jsx
│   │   ├── App.jsx                 # React Router v6 routing
│   │   ├── api/client.js           # Axios instance with JWT interceptor
│   │   ├── auth/
│   │   │   ├── AuthProvider.jsx    # JWT in memory, login/logout
│   │   │   └── ProtectedRoute.jsx  # Redirect if no token
│   │   ├── pages/
│   │   │   ├── MacroOverview.jsx
│   │   │   ├── DecisionCenter.jsx  # The most important page
│   │   │   ├── Portfolio.jsx
│   │   │   ├── ContributionLog.jsx
│   │   │   ├── ScenarioPlanner.jsx
│   │   │   └── HistoricalExplorer.jsx
│   │   ├── components/
│   │   │   ├── RegimeBadge.jsx
│   │   │   ├── YieldCurveChart.jsx
│   │   │   ├── FanChart.jsx        # PLN/USD uncertainty bands
│   │   │   ├── ShapBar.jsx
│   │   │   └── DataTable.jsx
│   │   └── hooks/
│   │       ├── useRegime.js
│   │       ├── usePortfolio.js
│   │       └── useVolatility.js
│   ├── package.json
│   ├── vite.config.js
│   └── Dockerfile
├── cloud/
│   ├── functions/
│   │   ├── ingest_prices/main.py
│   │   ├── ingest_macro/main.py
│   │   ├── ingest_sentiment/main.py
│   │   └── run_ml_pipeline/main.py
│   └── scheduler/schedules.yaml
├── notebooks/
│   ├── 01_eda_prices.ipynb
│   ├── 02_macro_analysis.ipynb
│   ├── 03_regime_labels.ipynb
│   ├── 04_regime_model.ipynb
│   ├── 05_shap_analysis.ipynb
│   └── 06_backtest.ipynb
├── models/
│   ├── regime_lgbm_v1.pkl
│   ├── vol_rf_v1.pkl
│   └── fx_lgbm_v1.pkl
├── requirements.txt
└── environment.yml
```

---

## Claude Code Prompts (26 total)

> **Convention:** Every prompt ends with the same instruction:
> *"Throughout the implementation, whenever you make a non-obvious architectural decision, add a short comment block starting with `# WHY:` explaining the reasoning. Focus on: data consistency, SQL semantics, cloud statefulness, and ML time-series pitfalls. Do not explain syntax — explain decisions."*

---

### Phase 1 — DuckDB Schema + First Data Load

**Prompt 1 — Project initialization**
```
/plan
Initialize a new Python project called investor_intelligence.
Set up the full folder structure from the pipeline document.
Create a DuckDB database and implement the full schema from schema.sql:
raw tables, processed tables, and user tables.
After creating each table group, add a WHY comment explaining:
- why this table is append-only vs mutable
- what the primary key guarantees
- what would break without it
```

**Prompt 2 — yfinance historical load**
```
/plan
Implement ingestion/prices.py using yfinance.
Load full historical data for all tickers from 2005-01-01.
Insert into raw_prices using upsert logic.
Add WHY comments explaining:
- why INSERT OR REPLACE rather than plain INSERT
- what happens to duplicates if ingestion runs twice
- what append-only means in practice for this table
```

**Prompt 3 — NBP and FRED ingestion**
```
/plan
Implement ingestion/fx.py (NBP API) and ingestion/macro.py (FRED API).
Handle the NBP 93-day window limitation with a year-loop.
Add WHY comments explaining:
- why raw and processed data live in separate tables
- what forward-filling monthly FRED data to daily frequency means
  and what assumption it encodes about how markets price macro
```

---

### Phase 2 — Additional Data Sources

**Prompt 4 — STOOQ + ECB SDW**
```
/plan
Implement ingestion/stooq.py for WIG20, WIG, DAX, USD/PLN, EUR/PLN.
Implement ingestion/ecb.py for ECB SDW: EA HICP, ECB rate,
EA 10Y and 2Y sovereign yields. No auth required for either.
Add WHY comments explaining:
- why STOOQ is more reliable than yfinance for Polish tickers
- what the ECB SDW adds that FRED doesn't cover
- how to handle ECB's different date formats and release frequencies
```

**Prompt 5 — CoinGecko + crypto features**
```
/plan
Implement ingestion/crypto.py using CoinGecko public API.
Fetch BTC and ETH daily from 2015-01-01. Insert into raw_crypto.
Extend processing/features.py to compute:
- btc_ret_21d
- btc_spy_corr_21d (rolling 21-day correlation)
Add WHY comments explaining:
- why BTC/SPY rolling correlation is a regime feature
- what high vs low correlation signals historically
- why this is a risk proxy, not an investment signal
```

**Prompt 6 — Finnhub sentiment + economic calendar**
```
/plan
Implement ingestion/sentiment.py with two Finnhub endpoints:
1. News sentiment score for ACWI and SPY
2. Economic calendar events (FOMC, CPI releases, NFP)
Store sentiment in raw_sentiment, calendar in raw_calendar_events.
Add WHY comments explaining:
- why the economic calendar is a separate table from sentiment
- what FOMC meeting weeks do to volatility patterns structurally
- why we store importance level for calendar events
```

**Prompt 7 — WallStreetBets + Google Trends**
```
/plan
Extend ingestion/sentiment.py:
1. WallStreetBets API — daily mention counts and bullish/bearish ratio for SPY
2. pytrends — weekly Google Trends for:
   ["recession", "stock market crash", "buy stocks", "ETF invest"]
Handle weekly-to-daily mismatch by forward-filling within each week.
Add WHY comments explaining:
- why retail sentiment is a contrarian signal
- what the weekly-to-daily forward-fill assumption encodes
- why Google Trends is normalized 0-100 and what limits cross-time comparison
```

**Prompt 8 — SEC EDGAR fundamentals**
```
/plan
Implement ingestion/fundamentals.py using SEC EDGAR.
Fetch quarterly EPS and compute aggregate S&P 500 P/E ratio.
Compute earnings yield (inverse P/E). Store in raw_fundamentals.
Forward-fill quarterly values to daily in processing/features.py.
Add WHY comments explaining:
- why SEC EDGAR requires a User-Agent header
- what earnings yield is and why it matters for regime detection
- what forward-filling quarterly fundamentals implies about
  information timing in markets
```

**Prompt 9 — Econdb Polish macro**
```
/plan
Implement ingestion/econdb.py: Poland CPI, unemployment,
GDP growth, NBP reference rate.
In processing/features.py add:
- rate_differential: fed_funds_rate - nbp_rate
- cpi_differential: cpi_us_yoy - cpi_pl_yoy
Add WHY comments explaining:
- why interest rate differentials drive PLN/USD currency flows
- what purchasing power parity implies about long-run exchange rates
- why tracking both countries' inflation matters for a PLN investor
  holding USD-denominated assets
```

---

### Phase 3 — Processing + SQL Features

**Prompt 10 — Feature engineering**
```
/plan
Implement processing/features.py building daily_features from raw tables
using DuckDB SQL. Implement feature groups one at a time:
1. Log returns and rolling volatility (window functions)
2. Yield curve spreads and inversion days
3. PLN-adjusted ACWI returns (join raw_prices with raw_fx)
4. Forward-fill monthly/quarterly macro to daily
Add WHY comments after each group explaining:
- what window function is used and why
- what happens if there are missing trading days in the sequence
- what forward-fill assumes about information timing
```

**Prompt 11 — Regime labels**
```
/plan
Implement processing/labels.py with rule-based regime classification
as a DuckDB SQL query writing into regime_labels table.
Add WHY comments explaining:
- why labels are generated with SQL rules rather than Python hardcoding
- what look-ahead bias means in time-series classification
- how rule-based labels become ML training targets
```

**Prompt 12 — QC and data validation**
```
/plan
Implement processing/qc.py with checks after each ingestion cycle:
1. Detect missing trading days in raw_prices for liquid tickers
2. Detect stale data (last date > 3 days behind today)
3. Flag outliers (daily return > 20%) without removing
4. Log all results to raw_qc_log
Add WHY comments explaining:
- why we flag outliers rather than auto-remove them
- what a missing trading day means vs a genuine data gap
- why stale detection matters for a live recommendation engine
```

**Prompt 13 — Incremental ingestion**
```
/plan
Refactor all ingestion modules to detect the latest date in each
raw table and fetch only from there forward.
Fallback to full historical load if table is empty.
Add WHY comments explaining:
- what idempotency means and why ingestion should be idempotent
- why checking max(date) before fetching saves API quota
- what happens if ingestion runs twice on the same day
```

---

### Phase 4 — GCP Cloud

**Prompt 14 — Cloud Functions**
```
/plan
Implement cloud/functions/ingest_prices/main.py as a GCP Cloud Function.
Use functions_framework. After ingestion, export DuckDB table to Parquet
on GCS bucket.
Add WHY comments explaining:
- why Cloud Functions are stateless and what that means for DuckDB
- why we export to Parquet on GCS rather than persisting DuckDB directly
- what happens to data consistency if the function crashes midway
```

**Prompt 15 — Cloud Scheduler**
```
/plan
Create cloud/scheduler/schedules.yaml for all ingestion functions
and the ML pipeline.
Add WHY comments explaining:
- why ingestion runs after market close not during the day
- why the ML pipeline runs last, after all ingestion
- what happens if an upstream ingestion function fails silently
```

---

### Phase 5 — ML Models

**Prompt 16 — Regime classifier**
```
/plan
Implement ml/regime.py with LightGBM multiclass classifier.
Nested TimeSeriesSplit CV — same architecture as master's thesis RF.
Add WHY comments explaining:
- why TimeSeriesSplit and not random KFold for financial data
- what look-ahead bias means and how the split prevents it
- why we use rule-based labels as training targets
```

**Prompt 17 — Volatility forecaster**
```
/plan
Implement ml/volatility.py with Random Forest regressor.
Target: acwi_vol_21d shifted 21 days forward.
Evaluate with TimeSeriesSplit. Log MAE and RMSE to model_eval_log.
Add WHY comments explaining:
- why shifting the target 21 days forward is necessary
- the difference between realized and implied volatility
- how the vol forecast maps to the lump sum vs DCA decision
```

**Prompt 18 — PLN/USD currency risk model**
```
/plan
Implement ml/currency.py with LightGBM quantile regression.
Predict 10th and 90th percentile of USD/PLN 63 days ahead.
Add WHY comments explaining:
- what quantile regression does vs point forecast regression
- why the 90th percentile is more useful than the point forecast
  for a risk-aware investor
- what interest rate parity predicts and where a data-driven model
  may diverge from it
```

**Prompt 19 — SHAP analysis notebook**
```
/plan
Create notebooks/05_shap_analysis.ipynb.
Load regime_lgbm_v1.pkl, compute SHAP values on daily_features.
Produce:
1. Global feature importance bar chart
2. SHAP beeswarm plot per regime class
3. Time-series of top 3 SHAP features annotated with
   2008 GFC, 2020 COVID, 2022 inflation shock
Add WHY comments explaining:
- why SHAP is preferable to LightGBM built-in feature importance
- what the beeswarm plot shows that a bar chart doesn't
- why annotating known events is a sanity check, not a validation metric
```

**Prompt 20 — Backtesting notebook**
```
/plan
Create notebooks/06_backtest.ipynb.
Regime-switching backtest:
  risk_on:     100% ACWI
  risk_off:    100% TLT
  stagflation: 50% GLD + 50% SHY
  deflation:   cash (return = 0)
Compute equity curve vs buy-and-hold ACWI in PLN terms.
Report CAGR, max drawdown, Sharpe, regime transition count.
Add WHY comments explaining:
- why this is decision support not a trading strategy
- why returns are measured in PLN not USD for this investor
- what look-ahead bias would mean and why it doesn't apply here
- what sequence-of-returns risk means post-accumulation
```

---

### Phase 6 — Backend

**Prompt 21 — FastAPI backend structure**
```
/plan
Implement the FastAPI backend in backend/main.py.
Use APIRouter — one router per domain (features, regime, portfolio,
volatility, decisions, projection, auth).
Use Pydantic schemas for all response models.
Shared DuckDB connection via FastAPI dependency injection.
Expose all endpoints from the pipeline document.
Add WHY comments explaining:
- why APIRouter splits endpoints rather than one flat file
- what Pydantic schemas do for API contracts
- why DuckDB connection is shared via dependency, not per-request
- what CORS is and why the backend must allow the React frontend origin
```

**Prompt 22 — Google OAuth + JWT middleware**
```
/plan
Add Google OAuth to FastAPI using GCP Identity Platform.
Implement /auth/login, /auth/callback, /auth/me.
Implement get_current_user() dependency verifying JWT on every
protected endpoint. Protect all non-auth routes.
Add WHY comments explaining:
- what OAuth2 authorization code flow is step by step
- why we issue our own JWT after Google auth rather than
  forwarding Google's token to the frontend
- what token expiry means and why the frontend must handle 401 responses
- the difference between authentication (who are you)
  and authorization (what can you do)
```

**Prompt 23 — Decision engine + long-term projection**
```
/plan
Implement backend/routers/decisions.py with rule-based recommendation
logic combining regime, vol_forecast, usdpln_upper, ike_remaining.
Return structured JSON: recommendation, plain-language rationale list,
and context fields (regime_context, vol_context, fx_context, ike_context).
Implement backend/routers/projection.py with three-scenario growth:
pessimistic 5% / base 8% / optimistic 10% annually.
Account for monthly contributions, existing portfolio value,
IKE limit inflation adjustment (~3%/yr).
Return: projected value time series, year to 1M PLN milestone,
total contributions vs growth decomposition,
equivalent monthly passive income at 4% withdrawal rate.
Add WHY comments explaining:
- why the decision engine is rule-based not ML (interpretability, trust)
- what the 4% withdrawal rule is and its limitations
- why compounding makes early contributions more valuable than late ones
```

---

### Phase 7 — Frontend

**Prompt 24 — React + Vite + auth scaffold**
```
/plan
Initialize React frontend in frontend/ using Vite.
Use React Router v6 for routing.
Implement auth/AuthProvider.jsx storing JWT in memory (not localStorage).
Implement auth/ProtectedRoute.jsx redirecting to login if no valid token.
Implement api/client.js as axios instance injecting JWT Authorization
header automatically via interceptors.
Build App.jsx routing skeleton connecting all pages.
Add WHY comments explaining:
- why Vite over Create React App
- why JWT is stored in memory not localStorage (XSS attack surface)
- what React Context is and why it is correct for auth state
- why axios interceptors handle token injection automatically
```

**Prompt 25 — All dashboard pages**
```
/plan
Implement all six dashboard pages using Recharts.
Each page fetches from FastAPI via axios client.
Use custom hooks in hooks/ per domain.

Pages:
1. MacroOverview — yield curve chart (3M/2Y/10Y), CPI comparison (US/EA/PL),
   RegimeBadge, probability bar chart, Google Trends contrarian signal
2. DecisionCenter — single recommendation card, plain-language rationale,
   IKE headroom bar, action log button. No charts on this page.
3. Portfolio — holdings table, P&L with FX decomposition chart,
   allocation pie vs target, rebalancing alert if drift > 5%
4. ContributionLog — transaction history, IKE progress bar,
   performance vs ACWI benchmark in PLN
5. ScenarioPlanner — three growth curves (Recharts area chart),
   milestone annotations, passive income estimate
6. HistoricalExplorer — filterable DataTable with date/asset/regime
   filters, regime-conditional return stats, CSV download

Add WHY comments explaining:
- why useEffect dependency array controls when data refetches
- why each page has its own hook rather than one global store
- what a fan chart communicates that a point forecast doesn't
- why DecisionCenter has no charts (clarity over information density)
```

---

### Phase 8 — Deployment

**Prompt 26 — Docker + Cloud Run**
```
/plan
Create Dockerfiles for backend/ and frontend/.
Backend: Python 3.11 slim, uvicorn, port 8080.
Frontend: two-stage — Node 20 alpine build, nginx serve.
Configure nginx to proxy /api/* to backend URL (avoids CORS in prod).
Create docker-compose.yml for local development with both containers.
For GCP:
- Backend to Cloud Run: stateless, reads Parquet from GCS
- Frontend to Cloud Run or Firebase Hosting
- All secrets via GCP Secret Manager, injected as env vars at runtime
Add WHY comments explaining:
- why the frontend uses a two-stage Docker build
- what nginx reverse proxy does and why it solves CORS in production
- why Cloud Run is stateless and what that means for DuckDB
  (reads Parquet from GCS on each invocation — no local state)
- why secrets must never appear in Dockerfile or git history
```

---

## Implementation Phases and Priority

| Phase | Content | Primary skill | Priority |
|---|---|---|---|
| 1 | DuckDB schema + yfinance + NBP + FRED | SQL | High |
| 2 | Full ingestion layer (12 sources) + QC | Python + APIs | High |
| 3 | Feature engineering + regime labels | SQL + domain | High |
| 4 | GCP Cloud Functions + Scheduler | Cloud | High |
| 5 | Regime + volatility + currency ML models | ML | Medium |
| 6 | FastAPI backend + Google OAuth + JWT | Backend | Medium |
| 7 | React frontend + all pages | Frontend | Medium |
| 8 | Portfolio features + decision engine | Domain | Medium |
| 9 | Docker + Cloud Run deployment | DevOps | Medium |
| 10 | SHAP + backtesting notebooks | Analysis | Low |
| — | Multi-user public launch | Optional | Deferred |

---

*Created: May 2026*
*Status: planning complete — ready to begin Phase 1*
