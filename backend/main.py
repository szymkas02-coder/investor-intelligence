"""
backend/main.py — FastAPI application entry point

Run locally:
    cd investor_intelligence
    uvicorn backend.main:app --reload --port 8000

API docs available at:
    http://localhost:8000/docs   (Swagger UI)
    http://localhost:8000/redoc  (ReDoc)
"""

import os
import logging
from pathlib import Path

# Load .env before anything else so DATABASE_URL is available when
# backend/database.py is imported (it reads DATABASE_URL at module load time)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass  # python-dotenv not installed — rely on env vars set externally

from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from backend.database import get_db
from fastapi.middleware.cors import CORSMiddleware

from backend.auth import router as auth_router
from backend.routers import dashboard, regime, portfolio, pipeline, decision, invest, history, signals, situation, regime_duration, ml_charts

logger = logging.getLogger(__name__)


# Database is PostgreSQL — connection managed by backend/database.py via DATABASE_URL.
# On GCP: DATABASE_URL points to Cloud SQL instance (injected via Secret Manager).

app = FastAPI(
    title       = "Investor Intelligence API",
    description = "Personal investment intelligence for IKE/ACWI ETF investors.",
    version     = "0.1.0",
)

# CORS — dev origins + any Cloud Run origin set via env var
_extra_origin = os.getenv("ALLOWED_ORIGIN", "https://investor-intelligence-1062085617181.europe-central2.run.app")
app.add_middleware(
    CORSMiddleware,
    allow_origins     = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        *([_extra_origin] if _extra_origin else []),
    ],
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

app.include_router(auth_router)                           # /auth/... stays at root (OAuth callback)
app.include_router(dashboard.router,       prefix="/api")  # /api/dashboard
app.include_router(regime.router,          prefix="/api")  # /api/regime
app.include_router(portfolio.router,       prefix="/api")  # /api/portfolio
app.include_router(pipeline.router,        prefix="/api")  # /api/pipeline
app.include_router(decision.router,        prefix="/api")  # /api/decision (legacy)
app.include_router(invest.router,          prefix="/api")  # /api/invest
app.include_router(history.router,         prefix="/api")  # /api/history
app.include_router(signals.router,         prefix="/api")  # /api/signals
app.include_router(situation.router,       prefix="/api")  # /api/situation, /api/chat
app.include_router(regime_duration.router, prefix="/api")  # /api/regime-duration
app.include_router(ml_charts.router,      prefix="/api")  # /api/ml/*

# Run DB migrations on startup (creates any missing tables safely)
try:
    from backend.database import run_migrations, IS_POSTGRES
    if IS_POSTGRES:
        run_migrations()
except Exception as _e:
    logging.getLogger(__name__).warning("Migration skipped: %s", _e)


@app.get("/api/tickers")
def get_tickers(db=Depends(get_db)):
    """Return all investable ETF tickers available in raw_prices, sorted by row count."""
    rows = db.execute("""
        SELECT p.ticker, COUNT(*) AS n, MIN(p.date) AS first, MAX(p.date) AS last,
               m.long_name
        FROM raw_prices p
        LEFT JOIN ticker_metadata m ON m.ticker = p.ticker
        WHERE p.source = 'yfinance'
          AND p.ticker NOT LIKE '^%'
          AND p.ticker NOT LIKE '%=X'
          AND p.ticker NOT IN ('DX-Y.NYB')
        GROUP BY p.ticker, m.long_name
        ORDER BY n DESC
    """).fetchall()
    return [{"ticker": r[0], "rows": r[1], "first": str(r[2]),
             "last": str(r[3]), "name": r[4] or r[0]} for r in rows]


@app.get("/api/health")
def health():
    return {"status": "ok", "version": app.version}


# Serve React frontend in production (when frontend/dist exists — not present locally).
# All unknown routes return index.html so React Router handles client-side navigation.
_FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def serve_root():
        return FileResponse(_FRONTEND_DIST / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str):
        candidate = _FRONTEND_DIST / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_FRONTEND_DIST / "index.html")
