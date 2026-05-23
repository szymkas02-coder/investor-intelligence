# Inwestowanie Pasywne

**A personal finance dashboard for long-term passive investors.**
**Built primarily to demonstrate data engineering, PostgreSQL, and cloud deployment (GCP + Render).**

Live demo: https://inwestowanie-pasywne-1062085617181.europe-central2.run.app  
*(Open link — no login required. Sign in with any Google account for full portfolio access.)*

> **Backup deployment:** also live on Render + Supabase (free tier, $0/month).
> The GCP deployment runs on a free trial ending ~2026-08-10; the Render deployment will become primary at that point.

The core proposition is unromantic on purpose: **be globally diversified, contribute monthly, don't time the market.** The app supports that by tracking your portfolio (positions, IKE contribution limit, transaction history, AI-parsed broker imports), providing a long-run perspective on equity returns, an AI assistant for market questions, and a Situation Room with Gemini-grounded weekly briefings.

**The ML models are a research showcase, not the recommendation engine.** Seven models (HMM regime detection, Kaplan-Meier survival, RF volatility, LightGBM quantile FX, LightGBM recession with isotonic calibration, CAPE quantile regression, rolling PCA diversification) live under `/ml` as a demonstration of applied techniques. Each comes with honest caveats — including, for the HMM, the fact that the post-1990 equity environment is structurally different from the 19th and mid-20th century and the model can't see through that. They do not drive the app's investment advice.

This project's primary goal was learning **PostgreSQL, cloud deployment (GCP + Render), and full-stack production practices** — the ML layer was added to give the data something to do. The repo is structured to make those skills visible: see [Data Engineering Highlights](#data-engineering-highlights) and [GCP Deployment](#gcp-deployment).

For a detailed description of every ML model (inputs, method, limitations, how to retrain), see [`docs/ML_REFERENCE.md`](docs/ML_REFERENCE.md).

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                          Data Sources (8+ APIs)                      │
│   yfinance  FRED  NBP  ECB SDW  STOOQ  Finnhub  SEC EDGAR  Shiller  │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ 10-step automated pipeline
                                │ Cloud Scheduler: Mon-Fri 06:00 Warsaw
                                v
┌──────────────────────────────────────────────────────────────────────┐
│                    PostgreSQL (Cloud SQL)                             │
│   228k+ rows   55 ETF tickers   25 tables                            │
│   raw_prices / daily_features / hmm_predictions / fx_forecasts / ... │
└───────────┬──────────────────────────────────┬───────────────────────┘
            │                                  │
            v                                  v
┌────────────────────────┐          ┌──────────────────────────────────┐
│   ML Layer (7 models)  │          │     FastAPI Backend               │
│                        │          │     30+ routes                    │
│   GaussianHMM (155Y)   │          │     psycopg2 connection pool      │
│   KM regime duration   │─────────>│     Google OAuth + JWT            │
│   RF volatility        │          │     Pydantic models               │
│   LightGBM FX quantile │          │     Background pipeline tasks     │
│   LightGBM recession   │          └──────────────┬───────────────────┘
│   CAPE quantile reg.   │                         │
│   PCA diversification  │                         v
└────────────────────────┘          ┌──────────────────────────────────┐
                                    │     React + Vite Frontend         │
┌────────────────────────┐          │     Dashboard / Decision          │
│   AI Layer (Gemini)    │          │     Portfolio / History           │
│                        │          │     Situation Room               │
│   2.5 Flash + Search   │─────────>│     Bilingual: Polish / English   │
│   grounding → weekly   │          │     i18next                       │
│   market briefings     │          └──────────────────────────────────┘
│                        │
│   Chat assistant with  │          ┌──────────────────────────────────┐
│   tool use: signals,   │          │     GCP Infrastructure            │
│   decision, portfolio, │          │     Cloud Run (auto-deploy)       │
│   macro data           │          │     Cloud Build CI/CD             │
└────────────────────────┘          │     Cloud Scheduler               │
                                    │     Secret Manager                │
                                    │     Artifact Registry             │
                                    └──────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technologies |
|---|---|
| Data ingestion | Python, requests, yfinance, pandas, 8+ REST/SDMX APIs |
| Database | PostgreSQL 18, psycopg2, SQL (DDL + window functions + CTEs) |
| ML | LightGBM, scikit-learn, hmmlearn, arch (GARCH benchmark) |
| Backend | FastAPI, Pydantic, PyJWT, openpyxl |
| AI | Google Gemini 2.5 Flash (grounded search + tool use) |
| Frontend | React, Vite, Recharts, i18next, react-router-dom |
| Auth | Google OAuth 2.0 + HS256 JWT |
| Infrastructure | Docker (multi-stage build), GCP Cloud Run, Cloud SQL, Cloud Build, Cloud Scheduler, Secret Manager, Artifact Registry |
| Testing | pytest, DuckDB (in-memory test fixture), 43 tests |

---

## Data Engineering Highlights

### 10-Step Automated Ingestion Pipeline

`ingestion/pipeline.py` orchestrates the full chain on a daily Cloud Scheduler cron:

1. Fetch prices for 55 ETF tickers (yfinance)
2. Fetch FX rates: EUR/PLN, USD/PLN (NBP API)
3. Fetch macro series: CPI, yields, credit spreads, LEI components (FRED + ECB SDW)
4. Fetch sentiment indicators (Finnhub, STOOQ)
5. Fetch CAPE/Shiller data (155 years of monthly data)
6. Compute technical features: HAR-RV realized volatility, momentum, mean-reversion signals
7. Compute macro features: yield curve slope, credit spread z-scores, FX carry, Sahm rule
8. Generate regime predictions (HMM forward-filter)
9. Run QC checks: staleness detection, outlier flagging, coverage validation
10. Write ML predictions to forecast tables (vol, FX, recession, CAPE, regime duration, PCA)

**Dual-DB abstraction:** a `PH` placeholder variable (`%s` for PostgreSQL, `?` for DuckDB) lets all ingestion modules run against both engines. Tests use an in-memory DuckDB fixture; production uses Cloud SQL. The `_PgAdapter` wrapper makes psycopg2 connections quack like DuckDB connections — no environment-specific code paths.

### Database

- `raw_prices`: 228k+ rows, 55 tickers, 2010–2026
- `daily_features`: 3,979 rows, 35+ engineered features per trading day (including 4 LEI columns: Sahm, initial claims, housing permits, INDPRO)
- `hmm_predictions`: monthly HMM state probabilities back to 1880
- `regime_duration_stats`: Kaplan-Meier survival estimates per regime
- `user_transactions`, `user_positions`, `ike_contributions`: per-user portfolio state
- `chat_history`, `situation_updates`: AI layer persistence

---

## ML Models

| Model | Algorithm | Purpose | Data |
|---|---|---|---|
| Market regime | GaussianHMM, 4 states, BIC-selected | Bull / Consolidation / Expensive / Bear | Shiller 1871–2026 (monthly) |
| Regime duration | Kaplan-Meier survival | P(episode still ongoing at T months) | HMM predictions 1880–present |
| Volatility 21d/63d | Random Forest (HAR-RV features) | Realised vol forecast | Daily features 2011–present |
| FX USD/PLN | LightGBM quantile (q=0.10/0.50/0.90) | Exchange rate uncertainty band | Daily features 2011–present |
| Recession | LightGBM + isotonic calibration | US recession probability | FRED USREC + 12 LEI features |
| CAPE valuation | QuantileRegressor (q=0.10/0.50/0.90) | 10Y real return distribution | Shiller 1871–2016 |
| PCA diversification | Rolling PCA on 5-asset correlation | Diversification index | Daily returns 2011–present |

**Benchmark result (GARCH vs RF volatility):** walk-forward test over 152 windows × 21d shows RF RMSE=0.051 vs GARCH(1,1) RMSE=0.056 — RF wins by 8.2% due to HAR-RV + macro features.

The projection model blends momentum (dominates 1–3Y), CAPE (peaks at 5Y), and long-run base rate (dominates 10Y+) with horizon-dependent weights. Evidence basis: Jegadeesh-Titman (1993), Campbell-Shiller (1988/1998), DMS 2025.

See [`docs/ML_REFERENCE.md`](docs/ML_REFERENCE.md) for full model documentation.

---

## AI Layer

Two Gemini models serve distinct roles:

**Gemini 2.5 Flash with Google Search grounding** runs on a weekly Cloud Scheduler job (Sundays 21:00 Warsaw). It searches for current macro news, synthesizes signals from the database, and writes a structured briefing stored in `situation_updates`. A daily "news pulse" (3–5 bullets) refreshes on demand (rate-limited to once per 24h).

**Chat assistant** handles conversational queries. Every request injects: the latest briefing, current ML signal outputs, and up to 10 turns of persistent chat history from the database. The model has tool-use access to four backend functions — `get_signals()`, `get_decision()`, `get_portfolio()`, `get_macro()` — and runs in an agentic loop (up to 5 rounds per turn).

---

## Portfolio Features

- Transaction CRUD: BUY, SELL, DEPOSIT with account type (IKE, IKZE, standard)
- IKE annual contribution limit tracking (2025: 26,019 PLN; 2026: 28,260 PLN)
- Broker Excel AI import: upload any broker statement, Gemini parses rows, maps tickers, handles currency conversion, returns a preview before commit
- Region / sector / commodity breakdown: donut charts from `etf_allocations` weights × current positions

---

## Frontend

Six pages + 7 ML model detail pages built in React + Vite:

- **Dashboard** — verdict banner, regime indicator, signal panel (HMM, KM duration, recession, CAPE, valuation context), volatility gauge, FX fan chart, macro snapshot
- **Decision** — INVEST/DCA/WAIT with plain-language reasons, horizon-dependent return projection
- **Portfolio** — positions, transaction history, IKE tracker, allocation breakdown charts
- **History** — price and macro time series with regime overlay, searchable ticker dropdown
- **Situation Room** — AI market briefing + persistent chat assistant
- **ML Models** — hub page listing all 7 models with live signal badges; each model has its own dedicated page with 4–5 interactive charts (regime timeline, survival curves, CAPE scatter, recession calibration, etc.), two-level descriptions (plain language ↔ technical), and feature importance visualisations

Fully bilingual (Polish/English) via i18next. Language preference stored in localStorage.

---

## GCP Deployment

Auto-deploy on every push to `main`:

```
git push origin main
    → Cloud Build trigger fires
    → Docker multi-stage build (Node 20 build + Python 3.11 runtime)
    → ML model artifacts pulled from GCS bucket
    → Cloud Run service updated (~5 minutes end-to-end)
```

All secrets stored in Secret Manager and mounted at runtime. Connection pool (min 1, max 20) initialised lazily on first request.

---

## What This Demonstrates

Built as a learning exercise by an atmospheric physicist moving into data engineering and full-stack development:

- **End-to-end pipeline design** — raw API ingestion → feature engineering → ML inference → API serving, all in production on managed cloud infrastructure
- **Production practices** — CI/CD, containerisation, secret management, connection pooling, parameterized SQL, in-memory test fixture
- **Applied ML with domain context** — models chosen for interpretability and reliability; regime classification, volatility forecasting, and valuation-based return projection grounded in published financial research
- **System integration** — eight data sources, two ML frameworks, one LLM provider, Google OAuth, bilingual frontend coordinated through a single FastAPI application

---

## Repository Structure

```
investor_intelligence/
├── ingestion/           # One module per data source + pipeline.py orchestrator
├── processing/          # features.py, labels.py, qc.py
├── ml/                  # 7 model scripts + garch_benchmark.py; artifacts in models/ (gitignored)
├── docs/
│   └── ML_REFERENCE.md  # Detailed reference: inputs, method, limitations, retrain instructions
├── backend/
│   ├── main.py          # FastAPI app, 30+ routes
│   ├── auth.py          # Google OAuth + JWT; open registration (ALLOWED_EMAILS = set())
│   ├── database.py      # _PgAdapter, ThreadedConnectionPool
│   ├── models.py        # Pydantic schemas
│   └── routers/         # dashboard, regime, portfolio, pipeline, decision, signals, history, situation
├── frontend/
│   └── src/
│       ├── pages/       # Dashboard, Decision, Portfolio, History, Situation
│       ├── components/  # RegimeBar, VolGauge, FXFanChart, SignalPanel
│       ├── contexts/    # AuthContext (auto-guest on first visit)
│       └── locales/     # pl.json, en.json
├── db/                  # schema_pg.sql, schema.sql (DuckDB), init_db.py
├── cloud/               # Cloud Build config, Scheduler definitions
├── tests/               # 43 pytest tests, in-memory DuckDB fixture
├── Dockerfile           # Multi-stage: Node 20 build + Python 3.11 runtime
└── shiller.csv          # 1,863 monthly rows, 1871–2026 (Shiller dataset)
```

---

## Running Locally

Requires Python 3.11+, Node.js 20+, and a PostgreSQL instance (or omit `DATABASE_URL` to fall back to DuckDB).

```bash
# Backend
pip install -r requirements-backend.txt
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
# Swagger UI: http://127.0.0.1:8000/docs

# Frontend
cd frontend && npm install && npm run dev
# App: http://localhost:5173 (auto-logs in as guest on first visit)

# Tests (no external services required)
pytest tests/ -v
```

Copy `.env.example` to `.env` and set `DATABASE_URL`. All other API keys are optional — the app degrades gracefully when external services are unavailable.
