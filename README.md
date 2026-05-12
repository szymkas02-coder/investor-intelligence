# Investor Intelligence System

**Designed for monthly decisions, not daily ones.**

A personal investment intelligence platform for long-term passive investors. Built around an IKE/ACWI ETF strategy with PLN exposure — designed to answer one question per month: *should I invest now, DCA, or wait?*

## Philosophy

This app helps you make fewer bad decisions, not more frequent ones. It is explicitly **not** a trading dashboard or stock picker. The core use cases are:

- Monthly IKE contribution decisions (lump sum vs DCA)
- Rebalancing checks (has allocation drifted enough to act?)
- Macro context (what regime am I investing into?)
- Long-term projection (am I on track given my contribution pace?)

## Stack

```
55 ETF tickers (yfinance/NBP/FRED/ECB) → PostgreSQL → ML Models → FastAPI → React
```

- **Database:** PostgreSQL 18 (local dev) → GCP Cloud SQL (production)
- **ML:** LightGBM, Random Forest, HMM, CAPE — 6 models
- **Backend:** FastAPI, 19 routes, psycopg2 connection pool
- **Frontend:** React + Vite, calls backend directly (no proxy)

## Prerequisites

- Python: `C:/Users/szymo/anaconda3/envs/geo/python.exe` (geo conda env)
- PostgreSQL 18 running on localhost:5432
- `.env` file with `DATABASE_URL=postgresql://postgres:PASSWORD@localhost:5432/investor_intelligence`
- Node.js for frontend

## Setup (first time)

```powershell
# 1. Create PostgreSQL database and tables
C:/Users/szymo/anaconda3/envs/geo/python.exe db/init_db.py

# 2. Run full historical data download (~10 min, 55 tickers)
C:/Users/szymo/anaconda3/envs/geo/python.exe ingestion/prices.py --full-reload

# 3. Run full pipeline to build features + labels
C:/Users/szymo/anaconda3/envs/geo/python.exe ingestion/pipeline.py
```

## Running the app

```powershell
# Backend (FastAPI) — http://127.0.0.1:8000/docs
C:/Users/szymo/anaconda3/envs/geo/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --reload --port 8000

# Frontend (React/Vite) — http://localhost:5173
cd frontend && npm run dev
# Click "Dev mode" to bypass Google OAuth in development
```

## Daily pipeline

```powershell
# Fetch new data + rebuild features + labels + QC (~65s)
C:/Users/szymo/anaconda3/envs/geo/python.exe ingestion/pipeline.py

# Run tests
C:/Users/szymo/anaconda3/envs/geo/python.exe -m pytest tests/ -v
```

## Project Structure

```
investor_intelligence/
├── db/               # schema.sql, schema_pg.sql, init_db.py, migrate_duckdb_to_pg.py
├── ingestion/        # One module per data source + pipeline.py orchestrator
├── processing/       # features.py (ISAC.L primary), labels.py, qc.py
├── ml/               # 6 models: regime, volatility, currency, hmm, recession, cape
├── backend/          # FastAPI — 19 routes, psycopg2 pool, _PgAdapter
├── frontend/         # React + Vite — calls 127.0.0.1:8000 directly (no Vite proxy)
├── cloud/            # GCP Cloud Functions + Scheduler + deploy_app.sh
├── tests/            # 43 pytest tests (in-memory DuckDB fixture)
├── utils/            # logging_config.py
├── models/           # Trained .pkl artifacts (gitignored)
└── CLAUDE.md         # Full session guide — read this to start a new session
```

## Node PATH (if npm not found)

```powershell
$env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH","User")
```
