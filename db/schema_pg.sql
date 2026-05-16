-- =============================================================================
-- Investor Intelligence System — PostgreSQL Schema
-- =============================================================================
--
-- TEACHING NOTE — key differences from schema.sql (DuckDB):
--
--   DOUBLE → DOUBLE PRECISION   (PostgreSQL's name for 64-bit float)
--   VARCHAR → TEXT               (PostgreSQL TEXT is unlimited, VARCHAR(n) just adds a constraint)
--   TIMESTAMPTZ DEFAULT now()    (same — PostgreSQL uses now() too, this one didn't change)
--   JSON → JSONB                 (PostgreSQL's binary JSON — faster to query than plain JSON)
--
-- Everything else — PRIMARY KEY, NOT NULL, DEFAULT, INTERVAL, window functions,
-- ON CONFLICT DO UPDATE — is identical standard SQL that both databases support.
-- =============================================================================

-- =============================================================================
-- RAW TABLES (append-only, never modified after insert)
-- =============================================================================

CREATE TABLE IF NOT EXISTS raw_prices (
    date            DATE                NOT NULL,
    ticker          TEXT                NOT NULL,
    source          TEXT                NOT NULL,
    open            DOUBLE PRECISION,
    high            DOUBLE PRECISION,
    low             DOUBLE PRECISION,
    close           DOUBLE PRECISION,
    adj_close       DOUBLE PRECISION,
    volume          BIGINT,
    ingested_at     TIMESTAMPTZ         DEFAULT now(),
    PRIMARY KEY (date, ticker, source)
);

CREATE TABLE IF NOT EXISTS raw_macro (
    date            DATE                NOT NULL,
    series_id       TEXT                NOT NULL,
    source          TEXT                NOT NULL,
    value           DOUBLE PRECISION,
    frequency       TEXT,
    ingested_at     TIMESTAMPTZ         DEFAULT now(),
    PRIMARY KEY (date, series_id, source)
);

CREATE TABLE IF NOT EXISTS raw_fx (
    date            DATE                NOT NULL,
    base_currency   TEXT                NOT NULL,
    quote_currency  TEXT                NOT NULL,
    rate            DOUBLE PRECISION    NOT NULL,
    source          TEXT                NOT NULL,
    ingested_at     TIMESTAMPTZ         DEFAULT now(),
    PRIMARY KEY (date, base_currency, quote_currency, source)
);

CREATE TABLE IF NOT EXISTS raw_sentiment (
    date            DATE                NOT NULL,
    source          TEXT                NOT NULL,
    ticker          TEXT,
    keyword         TEXT,
    score           DOUBLE PRECISION,
    buzz            DOUBLE PRECISION,
    metadata        JSONB,
    ingested_at     TIMESTAMPTZ         DEFAULT now()
);

CREATE TABLE IF NOT EXISTS raw_fundamentals (
    date            DATE                NOT NULL,
    ticker          TEXT                NOT NULL,
    metric          TEXT                NOT NULL,
    value           DOUBLE PRECISION,
    unit            TEXT,
    source          TEXT                DEFAULT 'sec_edgar',
    ingested_at     TIMESTAMPTZ         DEFAULT now(),
    PRIMARY KEY (date, ticker, metric)
);

CREATE TABLE IF NOT EXISTS raw_crypto (
    date            DATE                NOT NULL,
    coin_id         TEXT                NOT NULL,
    price_usd       DOUBLE PRECISION,
    market_cap_usd  DOUBLE PRECISION,
    volume_usd      DOUBLE PRECISION,
    ingested_at     TIMESTAMPTZ         DEFAULT now(),
    PRIMARY KEY (date, coin_id)
);

CREATE TABLE IF NOT EXISTS raw_calendar_events (
    date            DATE                NOT NULL,
    event_name      TEXT                NOT NULL,
    country         TEXT,
    importance      TEXT,
    actual          DOUBLE PRECISION,
    estimate        DOUBLE PRECISION,
    ingested_at     TIMESTAMPTZ         DEFAULT now()
);

CREATE TABLE IF NOT EXISTS raw_qc_log (
    checked_at      TIMESTAMPTZ         DEFAULT now(),
    check_name      TEXT                NOT NULL,
    table_name      TEXT                NOT NULL,
    issue_count     INTEGER,
    details         TEXT
);


-- =============================================================================
-- PROCESSED / ANALYTICAL TABLES
-- =============================================================================

CREATE TABLE IF NOT EXISTS daily_features (
    date                    DATE    PRIMARY KEY,

    acwi_ret_1d             DOUBLE PRECISION,
    acwi_ret_5d             DOUBLE PRECISION,
    acwi_ret_21d            DOUBLE PRECISION,
    acwi_ret_63d            DOUBLE PRECISION,
    spy_ret_1d              DOUBLE PRECISION,
    wig20_ret_1d            DOUBLE PRECISION,
    gold_ret_1d             DOUBLE PRECISION,
    gold_ret_21d            DOUBLE PRECISION,
    tlt_ret_1d              DOUBLE PRECISION,

    acwi_vol_21d            DOUBLE PRECISION,
    acwi_vol_63d            DOUBLE PRECISION,
    vix_close               DOUBLE PRECISION,
    vix_change_5d           DOUBLE PRECISION,

    yield_10y               DOUBLE PRECISION,
    yield_2y                DOUBLE PRECISION,
    yield_3m                DOUBLE PRECISION,
    spread_10y_2y           DOUBLE PRECISION,
    spread_10y_3m           DOUBLE PRECISION,
    ecb_rate_10y            DOUBLE PRECISION,

    cpi_us_yoy              DOUBLE PRECISION,
    cpi_core_us_yoy         DOUBLE PRECISION,
    cpi_ea_yoy              DOUBLE PRECISION,
    cpi_pl_yoy              DOUBLE PRECISION,
    unemployment_us         DOUBLE PRECISION,
    fed_funds_rate          DOUBLE PRECISION,
    ecb_rate                DOUBLE PRECISION,
    nbp_rate                DOUBLE PRECISION,
    gdp_us_yoy              DOUBLE PRECISION,
    rate_differential       DOUBLE PRECISION,
    cpi_differential        DOUBLE PRECISION,

    usdpln                  DOUBLE PRECISION,
    eurpln                  DOUBLE PRECISION,
    usdpln_ret_21d          DOUBLE PRECISION,
    usdpln_vol_21d          DOUBLE PRECISION,
    dxy_close               DOUBLE PRECISION,

    hy_spread               DOUBLE PRECISION,
    btc_ret_21d             DOUBLE PRECISION,
    btc_spy_corr_21d        DOUBLE PRECISION,

    finnhub_sentiment       DOUBLE PRECISION,
    wsb_bullish_ratio       DOUBLE PRECISION,
    gtrends_recession       DOUBLE PRECISION,
    gtrends_invest          DOUBLE PRECISION,

    sp500_pe_ratio          DOUBLE PRECISION,
    sp500_earnings_yield    DOUBLE PRECISION,

    sahm_indicator          DOUBLE PRECISION,
    initial_claims          DOUBLE PRECISION,
    housing_permits         DOUBLE PRECISION,
    indpro                  DOUBLE PRECISION,

    acwi_pln_ret_1d         DOUBLE PRECISION,
    acwi_pln_ret_21d        DOUBLE PRECISION,
    yield_curve_inverted    BOOLEAN,
    vol_regime              TEXT,

    updated_at              TIMESTAMPTZ     DEFAULT now()
);

CREATE TABLE IF NOT EXISTS regime_labels (
    date            DATE    PRIMARY KEY,
    regime          TEXT    NOT NULL,
    label_source    TEXT,
    confidence      DOUBLE PRECISION,
    notes           TEXT
);

-- regime_predictions removed — circular LightGBM model replaced by KM survival analysis + HMM as primary signal

CREATE TABLE IF NOT EXISTS volatility_forecasts (
    date            DATE                NOT NULL,
    model_version   TEXT                NOT NULL,
    ticker          TEXT                NOT NULL,
    horizon_days    INTEGER             NOT NULL,
    vol_forecast    DOUBLE PRECISION,
    vol_lower       DOUBLE PRECISION,
    vol_upper       DOUBLE PRECISION,
    predicted_at    TIMESTAMPTZ         DEFAULT now(),
    PRIMARY KEY (date, model_version, ticker, horizon_days)
);

CREATE TABLE IF NOT EXISTS fx_forecasts (
    date            DATE                NOT NULL,
    model_version   TEXT                NOT NULL,
    pair            TEXT                NOT NULL,
    horizon_days    INTEGER             NOT NULL,
    rate_point      DOUBLE PRECISION,
    rate_lower      DOUBLE PRECISION,
    rate_upper      DOUBLE PRECISION,
    predicted_at    TIMESTAMPTZ         DEFAULT now(),
    PRIMARY KEY (date, model_version, pair, horizon_days)
);

CREATE TABLE IF NOT EXISTS cape_forecasts (
    date            DATE                NOT NULL,
    model_version   TEXT                NOT NULL,
    cape            DOUBLE PRECISION,
    ret_q10         DOUBLE PRECISION,
    ret_q50         DOUBLE PRECISION,
    ret_q90         DOUBLE PRECISION,
    predicted_at    TIMESTAMPTZ         DEFAULT now(),
    PRIMARY KEY (date, model_version)
);

CREATE TABLE IF NOT EXISTS hmm_predictions (
    date                DATE                NOT NULL,
    model_version       TEXT                NOT NULL,
    state_pred          INTEGER,
    state_label         TEXT,
    prob_bull           DOUBLE PRECISION,
    prob_bear           DOUBLE PRECISION,
    prob_consolidation  DOUBLE PRECISION,
    predicted_at        TIMESTAMPTZ         DEFAULT now(),
    PRIMARY KEY (date, model_version)
);

CREATE TABLE IF NOT EXISTS recession_predictions (
    date            DATE                NOT NULL,
    model_version   TEXT                NOT NULL,
    recession_prob  DOUBLE PRECISION,
    recession_pred  TEXT,
    predicted_at    TIMESTAMPTZ         DEFAULT now(),
    PRIMARY KEY (date, model_version)
);

CREATE TABLE IF NOT EXISTS regime_duration_stats (
    regime              TEXT        NOT NULL,
    duration_months     INTEGER     NOT NULL,
    km_survival         DOUBLE PRECISION,
    km_survival_lower   DOUBLE PRECISION,
    km_survival_upper   DOUBLE PRECISION,
    n_at_risk           INTEGER,
    n_events            INTEGER,
    computed_at         TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (regime, duration_months)
);

CREATE TABLE IF NOT EXISTS correlation_stats (
    computed_date   DATE        NOT NULL,
    regime          TEXT,
    asset_pair      TEXT        NOT NULL,
    window_days     INTEGER     NOT NULL,
    correlation     DOUBLE PRECISION,
    computed_at     TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (computed_date, asset_pair, window_days)
);

CREATE TABLE IF NOT EXISTS diversification_index (
    computed_date   DATE        PRIMARY KEY,
    regime          TEXT,
    div_index       DOUBLE PRECISION,
    pc1_explained   DOUBLE PRECISION,
    n_assets        INTEGER,
    computed_at     TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS model_eval_log (
    eval_date           DATE                NOT NULL,
    model_name          TEXT                NOT NULL,
    metric              TEXT                NOT NULL,
    value               DOUBLE PRECISION,
    eval_window_days    INTEGER,
    PRIMARY KEY (eval_date, model_name, metric)
);


CREATE TABLE IF NOT EXISTS ticker_metadata (
    ticker          TEXT        PRIMARY KEY,
    long_name       TEXT,
    currency        TEXT,
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- =============================================================================
-- USER TABLES
-- =============================================================================

CREATE TABLE IF NOT EXISTS users (
    user_id         TEXT        PRIMARY KEY,
    email           TEXT        NOT NULL,
    display_name    TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_positions (
    user_id         TEXT                NOT NULL,
    ticker          TEXT                NOT NULL,
    shares          DOUBLE PRECISION    NOT NULL,
    avg_cost_pln    DOUBLE PRECISION    NOT NULL,
    avg_cost_usdpln DOUBLE PRECISION,
    account_type    TEXT                DEFAULT 'IKE',
    opened_at       DATE                NOT NULL,
    updated_at      TIMESTAMPTZ         DEFAULT now(),
    PRIMARY KEY (user_id, ticker, account_type)
);

CREATE TABLE IF NOT EXISTS user_transactions (
    transaction_id  TEXT        PRIMARY KEY,
    user_id         TEXT        NOT NULL,
    ticker          TEXT,
    date            DATE        NOT NULL,
    type            TEXT        NOT NULL,
    shares          DOUBLE PRECISION,
    price_pln       DOUBLE PRECISION,
    usdpln_rate     DOUBLE PRECISION,
    account_type    TEXT                DEFAULT 'IKE',
    notes           TEXT,
    created_at      TIMESTAMPTZ         DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ike_contributions (
    user_id         TEXT                NOT NULL,
    year            INTEGER             NOT NULL,
    contributed_pln DOUBLE PRECISION    DEFAULT 0,
    limit_pln       DOUBLE PRECISION,
    PRIMARY KEY (user_id, year)
);

CREATE TABLE IF NOT EXISTS user_preferences (
    user_id                 TEXT    PRIMARY KEY,
    risk_tolerance          TEXT,
    investment_horizon_yrs  INTEGER,
    monthly_budget_pln      DOUBLE PRECISION,
    target_allocation       JSONB,
    updated_at              TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS situation_updates (
    id          SERIAL      PRIMARY KEY,
    type        TEXT        NOT NULL,       -- 'pulse' or 'briefing'
    content     TEXT        NOT NULL,
    model_used  TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS decision_log (
    decision_id     TEXT        PRIMARY KEY,
    user_id         TEXT        NOT NULL,
    date            DATE        NOT NULL,
    regime_at_time  TEXT,
    vol_at_time     DOUBLE PRECISION,
    usdpln_at_time  DOUBLE PRECISION,
    recommendation  TEXT,
    rationale       JSONB,
    user_action     TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);
