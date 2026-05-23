-- =============================================================================
-- Inwestowanie Pasywne — DuckDB Schema
-- =============================================================================

-- =============================================================================
-- RAW TABLES (append-only, never modified after insert)
-- =============================================================================

-- WHY: Raw tables are append-only because they represent what an API returned
-- at a specific ingested_at timestamp. Mutating them destroys the audit trail.
-- If an upstream API corrects a value, we append a new row and handle it in
-- processing, not here. The primary key (date, ticker, source) prevents exact
-- duplicate ingestion runs from creating double rows, but allows the same date
-- from two different sources (yfinance vs STOOQ) to coexist — important for
-- cross-source validation in QC. Without the primary key, two ingestion runs
-- on the same day would silently double every row, corrupting all downstream
-- rolling calculations.

CREATE TABLE IF NOT EXISTS raw_prices (
    date            DATE        NOT NULL,
    ticker          VARCHAR     NOT NULL,
    source          VARCHAR     NOT NULL,   -- 'yfinance', 'stooq'
    open            DOUBLE,
    high            DOUBLE,
    low             DOUBLE,
    close           DOUBLE,
    adj_close       DOUBLE,
    volume          BIGINT,
    ingested_at     TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (date, ticker, source)
);

-- WHY: Macro series live in their own table rather than raw_prices because they
-- have fundamentally different semantics: a FRED CPI value on a given date is
-- a monthly aggregate, not a price tick. Mixing frequencies in one table would
-- require date-alignment logic in every downstream query. Separating by type
-- (price vs macro) means each table has a coherent granularity contract.
-- The primary key (date, series_id, source) allows the same economic concept
-- (e.g., inflation) to be stored from both FRED and ECB SDW without collision,
-- so we can compare or fall back between sources during QC.

CREATE TABLE IF NOT EXISTS raw_macro (
    date            DATE        NOT NULL,
    series_id       VARCHAR     NOT NULL,
    source          VARCHAR     NOT NULL,   -- 'fred', 'ecb', 'econdb'
    value           DOUBLE,
    frequency       VARCHAR,                -- 'daily', 'monthly', 'quarterly'
    ingested_at     TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (date, series_id, source)
);

-- WHY: FX rates get their own table because the natural key is a currency pair,
-- not a ticker. Storing (base, quote, source) as a compound primary key lets us
-- keep both NBP's official PLN rates and Frankfurter's ECB-sourced rates for the
-- same pair on the same date. This matters because NBP is the authoritative
-- source for PLN but has a 93-day query window limit; Frankfurter fills gaps.
-- Triangulation (USD/PLN via EUR) is validated in QC by comparing both sources.

CREATE TABLE IF NOT EXISTS raw_fx (
    date            DATE        NOT NULL,
    base_currency   VARCHAR     NOT NULL,
    quote_currency  VARCHAR     NOT NULL,
    rate            DOUBLE      NOT NULL,
    source          VARCHAR     NOT NULL,   -- 'nbp', 'frankfurter'
    ingested_at     TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (date, base_currency, quote_currency, source)
);

-- WHY: Sentiment has no natural numeric primary key — a Finnhub sentiment score
-- and a Google Trends value for the same date are structurally different objects
-- (one is ticker-based, one is keyword-based). We allow multiple rows per date
-- by omitting a primary key here. The (date, source, ticker, keyword) combination
-- uniquely identifies a row in practice, but enforcing this as a PK would block
-- adding new sentiment sources without schema changes. Flexibility is correct here
-- because sentiment sources are the most volatile part of the pipeline.

CREATE TABLE IF NOT EXISTS raw_sentiment (
    date            DATE        NOT NULL,
    source          VARCHAR     NOT NULL,   -- 'finnhub', 'wsb', 'gtrends'
    ticker          VARCHAR,
    keyword         VARCHAR,
    score           DOUBLE,
    buzz            DOUBLE,
    metadata        JSON,
    ingested_at     TIMESTAMPTZ DEFAULT now()
);

-- WHY: SEC EDGAR fundamentals are quarterly, not daily. Storing them in raw_macro
-- would be wrong because the primary key is (date, series_id, source) with no
-- ticker dimension — P/E ratio for SPY is fundamentally tied to an instrument.
-- The (date, ticker, metric) PK prevents double-inserting the same quarterly
-- filing. Forward-filling to daily happens in processing/features.py, not here,
-- because the assumption that "Q3 P/E applies until Q4 is released" is a
-- modeling decision, not a raw data fact.

CREATE TABLE IF NOT EXISTS raw_fundamentals (
    date            DATE        NOT NULL,
    ticker          VARCHAR     NOT NULL,
    metric          VARCHAR     NOT NULL,   -- 'EPS', 'PE', 'earnings_yield'
    value           DOUBLE,
    unit            VARCHAR,
    source          VARCHAR     DEFAULT 'sec_edgar',
    ingested_at     TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (date, ticker, metric)
);

-- WHY: Crypto is separated from raw_prices because CoinGecko's data model differs
-- from yfinance: it returns market_cap and volume in a single call without OHLC.
-- Forcing it into raw_prices would require nulling open/high/low for every crypto
-- row, which signals a schema mismatch. A dedicated table with exactly the fields
-- CoinGecko provides keeps the schema honest about what data is actually available.
-- The primary key (date, coin_id) enforces one row per coin per day — re-running
-- ingestion is safe.

CREATE TABLE IF NOT EXISTS raw_crypto (
    date            DATE        NOT NULL,
    coin_id         VARCHAR     NOT NULL,   -- 'bitcoin', 'ethereum'
    price_usd       DOUBLE,
    market_cap_usd  DOUBLE,
    volume_usd      DOUBLE,
    ingested_at     TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (date, coin_id)
);

-- WHY: Economic calendar events (FOMC meetings, CPI release dates) are separate
-- from raw_sentiment because they are scheduled future events with known metadata
-- (importance, actual vs estimate), not real-time sentiment signals. Mixing them
-- would force every sentiment query to filter out calendar rows by type. Calendar
-- events don't have a natural deduplication key across re-ingestion (same event
-- can update as 'actual' fills in after the fact), so we omit a PK and rely on
-- ingested_at for ordering. The alternative — using (date, event_name) as PK —
-- would silently discard updated actuals, which is worse than duplicates.

CREATE TABLE IF NOT EXISTS raw_calendar_events (
    date            DATE        NOT NULL,
    event_name      VARCHAR     NOT NULL,
    country         VARCHAR,
    importance      VARCHAR,                -- 'high', 'medium', 'low'
    actual          DOUBLE,
    estimate        DOUBLE,
    ingested_at     TIMESTAMPTZ DEFAULT now()
);

-- WHY: QC results must be stored separately from the data they describe because
-- QC is a process log, not a data fact. It answers "what did we check and when?"
-- not "what did the market do?". Storing QC output here lets downstream code
-- (and the FastAPI backend) query data freshness without re-running all checks.
-- No primary key: every check run produces a new row intentionally — historical
-- QC records are the audit trail proving the pipeline has been healthy over time.

CREATE TABLE IF NOT EXISTS raw_qc_log (
    checked_at      TIMESTAMPTZ DEFAULT now(),
    check_name      VARCHAR     NOT NULL,
    table_name      VARCHAR     NOT NULL,
    issue_count     INTEGER,
    details         VARCHAR
);


-- =============================================================================
-- PROCESSED / ANALYTICAL TABLES (mutable — rebuilt or upserted by processing/)
-- =============================================================================

-- WHY: daily_features is the single ML input surface. It is mutable (not
-- append-only) because feature engineering is idempotent: running features.py
-- twice on the same date should produce exactly one row, not two. The PRIMARY KEY
-- on date enforces this — INSERT OR REPLACE semantics overwrite stale feature rows.
-- All features are aligned to a single daily date, even those sourced from monthly
-- or quarterly series (which are forward-filled). This alignment is the critical
-- modeling decision: it assumes a monthly CPI print is "known" by the market on
-- the first day after release and remains so until the next print. Without this
-- table, every ML query would require a multi-table join with forward-fill logic
-- repeated in each query — a lookahead-bias trap waiting to happen.

CREATE TABLE IF NOT EXISTS daily_features (
    date                    DATE    PRIMARY KEY,

    -- Price returns (log returns, annualization-ready)
    acwi_ret_1d             DOUBLE,
    acwi_ret_5d             DOUBLE,
    acwi_ret_21d            DOUBLE,
    acwi_ret_63d            DOUBLE,
    spy_ret_1d              DOUBLE,
    wig20_ret_1d            DOUBLE,
    gold_ret_1d             DOUBLE,
    gold_ret_21d            DOUBLE,
    tlt_ret_1d              DOUBLE,

    -- Volatility (realized, annualized)
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

    -- Macro (forward-filled from monthly/quarterly releases)
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

    -- Credit / risk-on proxies
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

    -- Leading indicators for recession model
    sahm_indicator          DOUBLE,
    initial_claims          DOUBLE,
    housing_permits         DOUBLE,
    indpro                  DOUBLE,

    -- Derived (computed from above — stored to avoid re-computation in ML)
    acwi_pln_ret_1d         DOUBLE,
    acwi_pln_ret_21d        DOUBLE,
    yield_curve_inverted    BOOLEAN,
    vol_regime              VARCHAR,       -- 'low' / 'medium' / 'high'

    updated_at              TIMESTAMPTZ DEFAULT now()
);

-- WHY: regime_labels is the ground truth used to train the regime classifier.
-- It is a separate table from daily_features because labels require human review
-- for known crisis periods (2008 GFC, 2020 COVID, 2022 inflation shock) where
-- rule-based SQL mislabels transitions. If labels were a column in daily_features,
-- manual overrides would be overwritten every time features.py runs. Storing
-- label_source ('rule_based' vs 'manual') preserves the audit trail of which
-- labels were reviewed. The confidence column allows the ML training code to
-- optionally down-weight low-confidence boundary labels.

CREATE TABLE IF NOT EXISTS regime_labels (
    date            DATE    PRIMARY KEY,
    regime          VARCHAR NOT NULL,      -- 'risk_on', 'risk_off', 'stagflation', 'deflation'
    label_source    VARCHAR,               -- 'rule_based', 'manual'
    confidence      DOUBLE,
    notes           VARCHAR
);

-- regime_predictions removed — circular LightGBM model replaced by KM survival analysis + HMM as primary signal

-- WHY: Volatility forecasts store (date, model_version, ticker, horizon_days)
-- because the same model may forecast multiple horizons (21d, 63d) and multiple
-- tickers. The primary key prevents duplicate forecasts on re-run. vol_lower and
-- vol_upper are stored alongside the point forecast so the frontend can render a
-- confidence band without calling the model again at query time — forecasting is
-- expensive; reading stored intervals is cheap.

CREATE TABLE IF NOT EXISTS volatility_forecasts (
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

-- WHY: FX forecasts store quantile bounds (rate_lower = 10th pct, rate_upper =
-- 90th pct) rather than a point estimate because the decision use is risk-based:
-- "if the worst-case PLN/USD in 63 days exceeds 4.30, consider hedging." A point
-- forecast is useless for this purpose. Storing both bounds means the frontend
-- fan chart reads directly from this table — no model is loaded at render time.

CREATE TABLE IF NOT EXISTS fx_forecasts (
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

CREATE TABLE IF NOT EXISTS regime_duration_stats (
    regime              VARCHAR     NOT NULL,
    duration_months     INTEGER     NOT NULL,
    km_survival         DOUBLE,
    km_survival_lower   DOUBLE,
    km_survival_upper   DOUBLE,
    n_at_risk           INTEGER,
    n_events            INTEGER,
    computed_at         TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (regime, duration_months)
);

CREATE TABLE IF NOT EXISTS correlation_stats (
    computed_date   DATE        NOT NULL,
    regime          VARCHAR,
    asset_pair      VARCHAR     NOT NULL,
    window_days     INTEGER     NOT NULL,
    correlation     DOUBLE,
    computed_at     TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (computed_date, asset_pair, window_days)
);

CREATE TABLE IF NOT EXISTS diversification_index (
    computed_date   DATE        PRIMARY KEY,
    regime          VARCHAR,
    div_index       DOUBLE,
    pc1_explained   DOUBLE,
    n_assets        INTEGER,
    computed_at     TIMESTAMPTZ DEFAULT now()
);

-- WHY: model_eval_log records metrics (MAE, RMSE, accuracy) after each training
-- run. Storing eval results in the database rather than log files means the
-- FastAPI backend can expose model health as an API endpoint, and future training
-- runs can query whether the previous model degraded before deciding to replace it.
-- The (eval_date, model_name, metric) PK means one score per metric per training
-- run — re-running evaluation on the same date overwrites with corrected values.

CREATE TABLE IF NOT EXISTS model_eval_log (
    eval_date           DATE        NOT NULL,
    model_name          VARCHAR     NOT NULL,
    metric              VARCHAR     NOT NULL,
    value               DOUBLE,
    eval_window_days    INTEGER,
    PRIMARY KEY (eval_date, model_name, metric)
);


-- =============================================================================
-- USER TABLES (mutable — managed by FastAPI endpoints)
-- =============================================================================

-- WHY: user_id is the Google OAuth 'sub' claim — a stable, globally unique
-- identifier that does not change even if the user's email changes. Using email
-- as PK would break the join to all user tables the day a user changes their
-- Google email. 'sub' is guaranteed permanent by the OAuth spec.

CREATE TABLE IF NOT EXISTS users (
    user_id         VARCHAR     PRIMARY KEY,  -- Google OAuth sub
    email           VARCHAR     NOT NULL,
    display_name    VARCHAR,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- WHY: user_positions is mutable because it represents current state, not
-- history. When a user buys more shares, avg_cost_pln is recalculated and the
-- row is updated in place. The transaction history (user_transactions) is the
-- append-only ledger; this table is the derived aggregate. Separating them means
-- portfolio valuation queries always read one row per position — not a full
-- transaction history scan. account_type is part of the PK because the same
-- ticker can be held in both IKE and a regular brokerage account simultaneously,
-- with different tax treatment and cost basis.

CREATE TABLE IF NOT EXISTS user_positions (
    user_id         VARCHAR     NOT NULL,
    ticker          VARCHAR     NOT NULL,
    shares          DOUBLE      NOT NULL,
    avg_cost_pln    DOUBLE      NOT NULL,   -- weighted average cost in PLN
    avg_cost_usdpln DOUBLE,                 -- USD/PLN rate at avg cost date
    account_type    VARCHAR     DEFAULT 'IKE',  -- 'IKE', 'IKZE', 'regular'
    opened_at       DATE        NOT NULL,
    updated_at      TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (user_id, ticker, account_type)
);

-- WHY: user_transactions is append-only — it is the source of truth for cost
-- basis and tax calculations. Deleting or modifying a transaction would silently
-- corrupt avg_cost_pln in user_positions. Instead, corrections are made by
-- inserting a compensating transaction. transaction_id is a UUID generated by
-- the FastAPI layer to guarantee global uniqueness without auto-increment
-- (which DuckDB supports but UUIDs are portable across database migrations).

CREATE TABLE IF NOT EXISTS user_transactions (
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

-- WHY: ike_contributions tracks the annual IKE limit separately from transactions
-- because the limit itself changes year to year (indexed to average salary).
-- Storing limit_pln per year lets the UI show "you have X PLN remaining this year"
-- without the backend needing to know the current year's limit from external config.
-- The limit is set once per year (manually or from a seeded table) and
-- contributed_pln is updated on each buy transaction in the IKE account.

CREATE TABLE IF NOT EXISTS ike_contributions (
    user_id         VARCHAR     NOT NULL,
    year            INTEGER     NOT NULL,
    contributed_pln DOUBLE      DEFAULT 0,
    limit_pln       DOUBLE,                 -- annual IKE limit for that year
    PRIMARY KEY (user_id, year)
);

-- WHY: target_allocation is stored as JSON because the set of tickers a user
-- targets is variable and sparse — one user holds ACWI only, another holds
-- ACWI + GLD + TLT. A normalized table with one row per (user, ticker, weight)
-- would require a separate join in every allocation-drift query. JSON keeps
-- the schema stable while allowing arbitrary allocation vectors. The FastAPI
-- layer validates the JSON structure (weights sum to 1.0) before writing.

CREATE TABLE IF NOT EXISTS user_preferences (
    user_id                 VARCHAR PRIMARY KEY,
    risk_tolerance          VARCHAR,    -- 'conservative', 'moderate', 'aggressive'
    investment_horizon_yrs  INTEGER,
    monthly_budget_pln      DOUBLE,
    target_allocation       JSON,       -- e.g. {"ACWI": 0.8, "GLD": 0.2}
    updated_at              TIMESTAMPTZ DEFAULT now()
);

-- WHY: decision_log captures both what the system recommended AND what the user
-- actually did. This asymmetry is the core learning loop: after 12 months we can
-- answer "did lump-sum recommendations during risk_on regimes outperform DCA?"
-- with real user behavior data. Storing regime_at_time, vol_at_time, usdpln_at_time
-- as snapshot columns (not foreign keys to feature tables) protects the record
-- against any retrospective reprocessing of daily_features. The rationale JSON
-- stores the plain-language strings shown to the user at decision time — the
-- "why" of each recommendation is preserved even if the decision engine logic
-- changes in future versions.

CREATE TABLE IF NOT EXISTS decision_log (
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
