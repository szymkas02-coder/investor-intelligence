# Investor Intelligence

**A full-stack investment intelligence platform for long-term passive investors.**

Live demo: https://investor-intelligence-1062085617181.europe-central2.run.app

Built to answer one question per month: *invest now, DCA, or wait?* The system ingests market data from 8+ APIs, runs 6 ML models across market regimes, volatility, FX, and valuation, and surfaces everything through a bilingual React frontend with an AI chat assistant.

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
│   raw_prices / daily_features / regime_labels / fx_forecasts / ...   │
└───────────┬──────────────────────────────────┬───────────────────────┘
            │                                  │
            v                                  v
┌────────────────────────┐          ┌──────────────────────────────────┐
│   ML Layer (6 models)  │          │     FastAPI Backend               │
│                        │          │     30+ routes                    │
│   LightGBM regime      │          │     psycopg2 connection pool      │
│   RF volatility        │─────────>│     Google OAuth + JWT            │
│   LightGBM FX quantile │          │     Pydantic models               │
│   GaussianHMM (155Y)   │          │     Background pipeline tasks     │
│   LightGBM recession   │          └──────────────┬───────────────────┘
│   CAPE quantile reg.   │                         │
└────────────────────────┘                         v
                                    ┌──────────────────────────────────┐
┌────────────────────────┐          │     React + Vite Frontend         │
│   AI Layer (Gemini)    │          │     Dashboard / Decision          │
│                        │          │     Portfolio / History           │
│   2.5 Flash + Search   │─────────>│     Situation Room               │
│   grounding → weekly   │          │     Bilingual: Polish / English   │
│   market briefings     │          │     i18next                       │
│                        │          └──────────────────────────────────┘
│   Chat assistant with  │
│   tool use: signals,   │          ┌──────────────────────────────────┐
│   decision, portfolio, │          │     GCP Infrastructure            │
│   macro data           │          │     Cloud Run (auto-deploy)       │
└────────────────────────┘          │     Cloud Build CI/CD             │
                                    │     Cloud Scheduler               │
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
| ML | LightGBM, scikit-learn, hmmlearn, statsmodels |
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
3. Fetch macro series: CPI, yields, PMI, M2, credit spreads (FRED + ECB SDW)
4. Fetch sentiment indicators (Finnhub, STOOQ)
5. Fetch CAPE/Shiller data (155 years of monthly data)
6. Compute technical features: HAR-RV realized volatility, momentum, mean-reversion signals
7. Compute macro features: yield curve slope, credit spread z-scores, FX carry
8. Generate regime labels: rule-based VIX/CPI/yield curve classification
9. Run QC checks: staleness detection, outlier flagging, coverage validation
10. Write ML predictions to forecast tables

**Dual-DB abstraction:** a `PH` placeholder variable (`%s` for PostgreSQL, `?` for DuckDB) lets all ingestion modules run against both engines. Tests use an in-memory DuckDB fixture; production uses Cloud SQL. The `_PgAdapter` wrapper in `backend/database.py` makes psycopg2 connections quack like DuckDB connections so no code changes are needed between environments.

### Database

- `raw_prices`: 228k+ rows, 55 tickers, 2010-2026
- `daily_features`: 3,979 rows, 30+ engineered features per trading day
- `regime_labels`: 3,549 rows of rule-derived market regime classifications
- `user_transactions`, `user_positions`, `ike_contributions`: per-user portfolio state
- `chat_history`, `situation_updates`: AI layer persistence
- `etf_allocations`: region/sector/commodity weights for 20 ETFs

---

## ML Models

| Model | Algorithm | Target | CV Metric |
|---|---|---|---|
| Market regime classifier | LightGBM | risk-on / risk-off / deflation / consolidation | macro-F1 = 0.43 |
| 21-day volatility forecast | Random Forest (HAR-RV features) | realized vol | RMSE = 0.078 |
| 63-day volatility forecast | Random Forest (HAR-RV features) | realized vol | RMSE = 0.101 |
| EUR/PLN FX quantile model | LightGBM quantile (q=0.10/0.50/0.90) | 21d FX return | MAE = 0.027 |
| Recession probability | LightGBM + isotonic calibration | FRED USREC | calibrated probability |
| Long-run return projection | CAPE quantile regressor | 5-10Y expected return | Shiller E/P-RF formula |
| Hidden Markov Model | GaussianHMM, 4 states, BIC-selected | market phase | 155 years of Shiller data |

The projection model uses horizon-dependent weights so momentum dominates at 1-3 years, CAPE valuation at 5-10 years, and the long-run base rate at 10+ years. Evidence basis: Jegadeesh-Titman (1993), Campbell-Shiller (1988/1998), DMS 2025 Yearbook.

---

## AI Layer

Two Gemini models serve distinct roles:

**Gemini 2.5 Flash with Google Search grounding** runs on a weekly Cloud Scheduler job (Sundays 21:00 Warsaw). It searches for current macro news, synthesizes signals from the database, and writes a structured briefing stored in the `situation_updates` table. A daily "news pulse" (3-5 bullets) refreshes every 6 hours.

**Chat assistant** handles conversational queries using the same Gemini model. Every request injects: the latest briefing, current ML signal outputs, and up to 10 turns of persistent chat history from the database. The model has tool-use access to four backend functions — `get_signals()`, `get_decision()`, `get_portfolio()`, `get_macro()` — and runs in an agentic loop (up to 5 rounds per turn) to answer questions that require cross-referencing multiple data sources.

---

## Portfolio Features

- Transaction CRUD: BUY, SELL, DEPOSIT with account type (IKE, IKZE, standard)
- IKE annual contribution limit tracking (2025: 26,019 PLN; 2026: 28,260 PLN)
- Broker Excel AI import: upload a broker statement, Gemini parses the rows, maps tickers, handles currency conversion using historical FX rates from the database, and returns a preview for user confirmation before commit
- Region / sector / commodity breakdown: donut charts computed from `etf_allocations` weights applied to current position values

---

## Frontend

Five pages built in React + Vite:

- **Dashboard** — regime indicator, volatility gauge, FX fan chart, signal panel
- **Decision** — buy/DCA/wait signal with reasoning, horizon-dependent return projection
- **Portfolio** — positions, transaction history, IKE tracker, allocation breakdown charts
- **History** — price and macro time series with searchable ticker dropdown
- **Situation Room** — AI briefing display + persistent chat assistant

Fully bilingual (Polish/English) via i18next. Language preference is stored in localStorage; the backend decision endpoint accepts a `?lang=` parameter and returns localised reason strings.

---

## GCP Deployment

Auto-deploy workflow:

```
git push origin main
    → Cloud Build trigger fires
    → Docker multi-stage build (Node 20 build + Python 3.11 runtime)
    → ML model artifacts pulled from GCS
    → Cloud Run service updated
    → Cloud SQL connection via Unix socket
    (~5 minutes end-to-end)
```

All secrets (database URL, OAuth credentials, API keys) are stored in Secret Manager and mounted into Cloud Run at runtime. The connection pool (min 1, max 20) is initialised lazily on first request to keep cold start time low.

---

## What This Demonstrates

This project was built as a learning exercise by an atmospheric physicist transitioning into data engineering and full-stack development. It demonstrates:

- **End-to-end data pipeline design** — from raw API ingestion through feature engineering, ML inference, and API serving, all in production on managed cloud infrastructure
- **Production engineering practices** — CI/CD, containerisation, secret management, structured logging, connection pooling, and a test suite with a hermetic in-memory database fixture
- **Applied ML with domain context** — models chosen for interpretability and reliability over benchmark performance; regime classification, volatility forecasting, and valuation-based return projection grounded in published financial research
- **System integration** — eight data sources, two ML frameworks, one LLM provider, Google OAuth, and a bilingual frontend coordinated through a single FastAPI application
- **Iterative problem-solving** — the dual-DB abstraction, the `_PgAdapter` wrapper, and the direct frontend-to-backend calls (bypassing Vite proxy) each solve concrete production issues that emerged during development

---

## Repository Structure

```
investor_intelligence/
├── ingestion/           # One module per data source + pipeline.py orchestrator
├── processing/          # features.py, labels.py, qc.py
├── ml/                  # 6 model scripts; trained artifacts in models/ (gitignored)
├── backend/
│   ├── main.py          # FastAPI app, 30+ routes
│   ├── auth.py          # Google OAuth + JWT
│   ├── database.py      # _PgAdapter, ThreadedConnectionPool
│   ├── models.py        # Pydantic schemas
│   └── routers/         # dashboard, regime, portfolio, pipeline, decision, signals, history
├── frontend/
│   └── src/
│       ├── pages/       # Dashboard, Decision, Portfolio, History, Situation
│       ├── components/  # RegimeBar, VolGauge, FXFanChart, SignalPanel
│       ├── contexts/    # AuthContext
│       └── locales/     # pl.json, en.json
├── db/                  # schema_pg.sql, init_db.py
├── cloud/               # Cloud Build config, Scheduler definitions, deploy scripts
├── tests/               # 43 pytest tests, in-memory DuckDB fixture
├── Dockerfile           # Multi-stage: Node 20 build + Python 3.11 runtime
└── requirements.txt
```

---

## Running Locally

Requires Python 3.11+, Node.js 20+, and a PostgreSQL instance.

```bash
# Backend
pip install -r requirements-backend.txt
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload

# Frontend
cd frontend
npm install
npm run dev
# Open http://localhost:5173 and click "Dev mode" to bypass OAuth
```

Copy `.env.example` to `.env` and fill in `DATABASE_URL`. All other API keys are optional for local development — the app degrades gracefully when external services are unavailable.

```bash
# Tests (no external services required)
pytest tests/ -v
```
