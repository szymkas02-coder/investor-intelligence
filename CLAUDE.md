# Investor Intelligence — Claude Session Guide

Read this first. It has everything needed to continue without re-deriving context.

---

## What this project is

Personal investment intelligence app for a Warsaw-based IKE investor in VWCE.DE (UCITS ACWI ETF). Answers one question per month: *invest now, DCA, or wait?* Built with PostgreSQL + Python ML + FastAPI + React.

**The app is fully operational** — running live on GCP Cloud Run. All features are built and deployed. Remaining work is enhancements only.

**Secondary aim:** Learning project. The user is an atmospheric physicist/scientist — not a software engineer by training. Claude should explain architecture decisions and "why does this work" questions at any point, without assuming prior software engineering background. Connect explanations to scientific analogues where helpful (pipelines = processing chains, features = predictors, etc.).

---

## How to run things

**Python:** always use `C:/Users/szymo/anaconda3/envs/geo/python.exe` — never system Python.

**Backend (FastAPI):**
```powershell
C:/Users/szymo/anaconda3/envs/geo/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --reload --port 8000
```
Swagger UI: http://127.0.0.1:8000/docs

**Frontend (React/Vite):**
```powershell
cd frontend
npm run dev
```
App: http://localhost:5173 — click "Dev mode" to bypass Google OAuth.
Frontend calls backend directly at `http://127.0.0.1:8000` (no Vite proxy — it caused ECONNRESET under concurrent load).

**Node PATH issue:** if `npm` is not found, run first:
```powershell
$env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH","User")
```

**Full pipeline (~65s):**
```powershell
C:/Users/szymo/anaconda3/envs/geo/python.exe ingestion/pipeline.py
```
Runs against PostgreSQL (DATABASE_URL in .env). All 10 steps: ingestion → features → labels → QC.

**Run tests:**
```powershell
C:/Users/szymo/anaconda3/envs/geo/python.exe -m pytest tests/ -v
```
43 tests, all passing. In-memory DuckDB fixture — safe to run any time.

**ML training** (artifacts already saved in `models/` — only re-run if retraining):
```powershell
C:/Users/szymo/anaconda3/envs/geo/python.exe ml/regime.py train
C:/Users/szymo/anaconda3/envs/geo/python.exe ml/volatility.py train
C:/Users/szymo/anaconda3/envs/geo/python.exe ml/currency.py train
C:/Users/szymo/anaconda3/envs/geo/python.exe ml/hmm_regime.py train
C:/Users/szymo/anaconda3/envs/geo/python.exe ml/recession.py train
C:/Users/szymo/anaconda3/envs/geo/python.exe ml/cape_signal.py train
```

---

## Project structure

```
investor_intelligence/
├── db/                  # schema_pg.sql (PostgreSQL), init_db.py
│                        # init_db.py auto-detects DATABASE_URL → PG or DuckDB fallback
├── ingestion/           # one module per data source + pipeline.py orchestrator
│                        # all use PH placeholder from db.init_db (%s or ?)
├── processing/          # features.py, labels.py, qc.py
├── ml/                  # regime.py, volatility.py, currency.py,
│                        # hmm_regime.py, recession.py, cape_signal.py
├── models/              # saved .pkl artifacts (gitignored, pulled from GCS on Cloud Build)
├── backend/
│   ├── main.py          # FastAPI app entry, all routes registered here
│   ├── auth.py          # Google OAuth + PyJWT HS256; ALLOWED_EMAILS whitelist
│   ├── database.py      # _PgAdapter wraps psycopg2 to look like DuckDB conn
│   │                    # ThreadedConnectionPool(1,20); run_migrations() at startup
│   ├── models.py        # Pydantic schemas
│   └── routers/         # dashboard, regime, portfolio, pipeline, decision,
│                        # signals, history, situation, chat
├── frontend/src/
│   ├── pages/           # Dashboard, Decision, Portfolio, History, Situation, Login
│   ├── components/      # RegimeBar, VolGauge, FXFanChart, SignalPanel
│   ├── contexts/        # AuthContext (JWT in sessionStorage)
│   ├── locales/         # pl.json, en.json (i18next translations)
│   └── api/             # client.js → calls http://127.0.0.1:8000 directly
├── cloud/
│   ├── cloudbuild.yaml  # Cloud Build config; pulls ML models from GCS at build time
│   └── scheduler/       # schedules.yaml (cron times for all jobs)
├── tests/               # 43 pytest tests; in-memory DuckDB fixture (conftest.py)
├── utils/
│   └── logging_config.py  # structured logging (USE_JSON_LOGGING=1 for Cloud Run)
├── Dockerfile           # multi-stage: Node 20 build → Python 3.11; serves React via StaticFiles
├── requirements-backend.txt  # slim deps for Cloud Run (no duckdb, no training libs)
├── shiller.csv          # 1,862 monthly rows 1871–2026 (used by HMM + CAPE models)
└── CLAUDE.md            # this file
```

---

## Database

**Primary:** PostgreSQL 18 locally on port 5432; Cloud SQL (`investor-intelligence-db`, db-f1-micro) on GCP.
**Connection:** `DATABASE_URL=postgresql://postgres:***@localhost:5432/investor_intelligence` in `.env`
**Fallback:** DuckDB (in-memory, tests only via conftest.py fixture)

**Key tables:**

| Table | Rows (approx) | Notes |
|-------|--------------|-------|
| `raw_prices` | 228k+ | 55 tickers, 2005–2026 |
| `daily_features` | 3,979 | 2010–2026, 30+ features |
| `regime_labels` | 3,549 | rule-based, used for LightGBM training |
| `regime_predictions` | — | LightGBM output |
| `volatility_forecasts` | — | RF 21d + 63d |
| `fx_forecasts` | — | LightGBM quantile PLN/USD |
| `hmm_predictions` | — | GaussianHMM 4-state |
| `recession_predictions` | — | LightGBM + isotonic calibration |
| `cape_forecasts` | — | QuantileRegressor |
| `user_transactions` | per user | BUY/SELL/DEPOSIT |
| `user_positions` | per user | aggregated holdings |
| `ike_contributions` | per user | annual IKE limits tracked |
| `ticker_metadata` | 55 | long_name + currency from yfinance |
| `etf_allocations` | 20 ETFs | region/sector/commodity weights (hardcoded factsheet values) |
| `situation_updates` | — | Gemini-generated news pulses + weekly briefings |
| `chat_history` | per user | last 10 turns injected into every Gemini request |

**Dual-DB abstraction:**
- `db/init_db.py` exports `PH` (`%s` for PG, `?` for DuckDB) — all SQL uses this as f-string placeholder
- `backend/database.py` has `_PgAdapter` that wraps psycopg2 to look like DuckDB connection
- `run_migrations()` in `database.py` creates new tables automatically at container startup

**Known DuckDB bugs** (workarounds in place, only relevant for test fallback):
- `MAX()` with 2 params crashes on empty partition → `get_max_date()` in `init_db.py`
- `LAST_VALUE IGNORE NULLS` unreliable → correlated subquery ffill in `features.py`

---

## SSL fix (important — do not undo)

AVG Antivirus intercepts HTTPS and re-signs with its own root CA. Fix already applied:
- AVG root CA appended to `C:/Users/szymo/anaconda3/envs/geo/Lib/site-packages/certifi/cacert.pem`
- `CLOUDSDK_PYTHON` set permanently to geo Python so gcloud works: `[System.Environment]::SetEnvironmentVariable("CLOUDSDK_PYTHON", "C:/Users/szymo/anaconda3/envs/geo/python.exe", "User")`
- `NODE_OPTIONS=--use-system-ca` set permanently for npm

If geo env is recreated, re-run:
```powershell
$cert = Get-ChildItem Cert:\LocalMachine\Root | Where-Object { $_.Subject -like "*AVG*" }
$pem = "-----BEGIN CERTIFICATE-----`n" + [Convert]::ToBase64String($cert.RawData, 'InsertLineBreaks') + "`n-----END CERTIFICATE-----"
$pem | Out-File -FilePath "C:\Users\szymo\avg_root.pem" -Encoding ascii
C:/Users/szymo/anaconda3/envs/geo/python.exe -c "
import certifi, pathlib
cacert = pathlib.Path(certifi.where())
avg = pathlib.Path('C:/Users/szymo/avg_root.pem').read_text()
if 'AVG' not in cacert.read_text():
    open(cacert, 'a').write('\n# AVG Web/Mail Shield Root\n' + avg)
    print('Appended')
"
```

---

## ML models (all trained, artifacts in models/)

| Model | File | Notes |
|-------|------|-------|
| ~~LightGBM regime~~ | ~~`ml/regime.py`~~ | **DELETED** — circular labels (99.5% train accuracy, memorised rules). Replaced by HMM as primary signal. |
| RF vol 21d/63d | `ml/volatility.py` | HAR-RV features + macro context. RMSE=0.078/0.101 |
| LightGBM FX 21d/63d | `ml/currency.py` | Quantile q=0.10/0.50/0.90. Kept as uncertainty tool only (Meese-Rogoff — direction near-random) |
| GaussianHMM (4-state) | `ml/hmm_regime.py` | **PRIMARY regime signal.** Shiller 1871–2026. States: bull/consolidation/stagflation/bear. Stagflation = high-vol cluster (CAPE~20 centroid, negative ECY, ret~+2%/yr). Current CAPE=39 is outside training distribution — nearest-cluster assignment. |
| LightGBM recession | `ml/recession.py` | FRED USREC + isotonic calibration. Known look-ahead bias (NBER lag). |
| CAPE quantile | `ml/cape_signal.py` | QuantileRegressor q=0.10/0.50/0.90; 145Y Shiller. US-only (known limitation). |
| **KM regime duration** | `ml/regime_duration.py` | **NEW.** Kaplan-Meier survival analysis on HMM episodes. 4 states. Stagflation median=19m; current episode=73m (KM=0.20). Run: `python ml/regime_duration.py compute` |
| **PCA diversification** | `ml/correlation_pca.py` | **NEW.** Rolling 63d correlation PCA. Diversification index = 1 - PC1 variance. Current: 0.585. Run: `python ml/correlation_pca.py compute` |

**HMM probability resolution:** `backend/hmm_utils.py` — `resolve_hmm_probs(state_label, p_bull, p_bear, p_cons)` handles underflow and returns (state, p_bull, p_bear, p_cons, p_stagflation). All four sum to 1.0. When state='stagflation', stored probs ~10^-60 (underflow) — sets p_stagflation=0.99.

**New DB tables:** `regime_duration_stats`, `correlation_stats`, `diversification_index` — created by `run_migrations()` at startup. Also drops `regime_predictions` (removed).

**Decision engine** now uses: HMM prob_bear + prob_stagflation (primary), recession_prob (secondary), vol_21d (overlay), spread_10y_3m (yield curve check). No LightGBM dependency. Logic: WAIT if (bear>0.50 AND rec>0.40) OR spread<-0.50; DCA if stagflation>0.50 OR bear>0.35 OR rec>0.30 OR vol>0.25.

**Projection model** (`/decision/projection`): horizon-dependent weights varying continuously with forecast horizon T (years):
```
w_momentum(T)  = max(0, 1 - T/3) * 0.40   # dominates 1–3Y
w_cape(T)      = 0.55 * exp(-0.5 * ((T-5)/3)^2)  # peaks at 5Y
w_base_rate(T) = 1 - w_momentum(T) - w_cape(T)   # dominates 10Y+
```
CAPE signal uses Shiller E/P–RF formula (60%) blended with Asness decile table (40%). Momentum dampened when CAPE > 20. Evidence: Jegadeesh-Titman (1993), Campbell-Shiller (1988/1998), DMS 2025.

---

## Backend API routes

```
GET  /health
GET  /tickers                          → all ETFs in DB with long_name + currency
GET  /auth/login
GET  /auth/google/callback
GET  /auth/me
GET  /dashboard                        → now returns regime (HMM), regime_duration (KM), correlation (PCA)
GET  /signals                          → now returns hmm_regime, regime_duration, recession, cape_10y (no lgbm)
GET  /regime-duration                  → NEW: current regime age + full KM survival table
GET  /regime/history
GET  /history/prices?ticker=&days=
GET  /history/regime?days=
GET  /history/macro?series=&days=
GET  /history/fx?days=
GET  /history/cape?days=
GET  /portfolio
POST /portfolio/transaction
GET  /portfolio/transactions
DELETE /portfolio/transaction/{id}
PUT  /portfolio/transaction/{id}
DELETE /portfolio/transactions/all
GET  /portfolio/price/{ticker}?on_date=
GET  /portfolio/template              → pre-filled .xlsx download
POST /portfolio/upload                → bulk Excel import (standard template)
POST /portfolio/upload-broker         → AI-parsed broker Excel (step 1: sheet names)
POST /portfolio/upload-broker/confirm → commit broker import after preview
GET  /portfolio/analysis              → region/sector/commodity breakdown
POST /portfolio/allocations/refresh   → iShares auto-refresh (7-day rate limit)
POST /pipeline/run
GET  /decision
GET  /decision/projection
GET  /situation                       → latest pulse + briefing
POST /situation/refresh               → manual trigger (24h rate limit)
POST /chat
GET  /chat/history
```

**History router** uses `_json(Response)` to bypass Pydantic serialisation — critical for performance on large payloads (was 2s, now <100ms).

**Auth:** Dev mode auto-bypasses when `GOOGLE_CLIENT_ID` not in `.env`. Production: only `szymkas02@gmail.com` in `ALLOWED_EMAILS` in `auth.py`.

---

## Frontend pages

| Page | Route | Notes |
|------|-------|-------|
| Dashboard | `/` | **Redesigned.** Verdict banner (plain sentence + 5 key stats) + all technical panels collapsed by default. Each collapsible section has ▼ expand + ⓘ plain-language explanation. |
| Decision | `/decision` | INVEST/DCA/WAIT + plain-language reasons. Technical signal detail behind "Szczegóły ▼". Earnings growth limitation disclaimer on projection. |
| Situation Room | `/situation` | Gemini news pulse + weekly briefing + chat panel |
| Portfolio | `/portfolio` | Positions, transactions CRUD, Excel import, IKE tracker, allocation donut charts |
| History | `/history` | Searchable combobox, cumulative return % chart, regime overlay |
| Login | `/login` | Google OAuth or Dev mode bypass |

**Key frontend decisions:**
- No Vite proxy — frontend calls `http://127.0.0.1:8000` directly (Vite proxy caused ECONNRESET)
- Polish is default language; EN/PL toggle in navbar via i18next; preference in localStorage
- History chart shows cumulative return (%) rebased to 0% at period start
- ISAC.L is the primary ACWI ticker in features.py (history from 2011 vs VWCE.DE from 2019)
- Projection inputs debounced 600ms before API call

---

## AI layer (Situation Room)

Two Gemini models, two roles:

**Layer 1 — Gemini 2.5 Flash** (Google Search grounding, 20 RPD):
- `POST /situation/refresh` — generates news pulse; rate-limited to once per 24h
- Cloud Scheduler fires Sunday 21:00 Warsaw for weekly briefing
- Output stored in `situation_updates` table (type: `pulse` or `briefing`)

**Layer 2 — Gemini 2.5 Flash Lite** (chat, 500 RPD):
- `POST /chat` — injects app signals + latest pulse + briefing + last 10 chat turns as context
- Responds in user's language (auto-detected)
- Tool use: Gemini calls `get_signals()`, `get_decision()`, `get_portfolio()`, `get_macro()` in an agentic loop (max 5 rounds)

**Model notes:** Gemma 4 models (26B, 31B) return 500 errors from Google's side — avoid. `gemini-2.5-flash` confirmed working; use `gemini-2.5-flash-lite` for chat (500 RPD).

---

## GCP deployment

**App URL:** https://investor-intelligence-1062085617181.europe-central2.run.app

**Infrastructure:**
- GitHub: `szymkas02-coder/investor-intelligence` (private)
- GCP project: `investor-intelligence-496113`, region `europe-central2`
- Cloud SQL: instance `investor-intelligence-db` (db-f1-micro, ENTERPRISE edition), database `investor_intelligence`
- Secrets in Secret Manager: `DATABASE_URL`, `APP_SECRET`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, `GEMINI_API_KEY`, `FRED_API_KEY`, `STOOQ_API_KEY`, `FINNHUB_API_KEY`
- Cloud Build trigger `deploy-on-push` on `main` branch — auto-deploys on every `git push` (~5 min)
- ML models: trained locally, uploaded to GCS; `cloudbuild.yaml` pulls via `gsutil cp` at build time
- Cloud Scheduler: daily pipeline Mon–Fri 06:00 Warsaw; weekly briefing Sunday 21:00 Warsaw
- Cloud Run timeout: 3600s (handles long pipeline runs)
- `GOOGLE_REDIRECT_URI` = `https://investor-intelligence-1062085617181.europe-central2.run.app/auth/google/callback`

**Deploy workflow:**
```
local edit → git commit → git push origin main → Cloud Build fires → Docker build → Cloud Run deploy
```

**IAM:**
- `1062085617181-compute@developer.gserviceaccount.com`: Logs Writer, Cloud Run Admin, Service Account User, Storage Admin, Artifact Registry Writer, Service Account Token Creator
- `investor-intelligence@investor-intelligence-496113.iam.gserviceaccount.com`: Cloud Run Invoker, Secret Manager Secret Accessor, Cloud SQL Client

---

## GCP billing and free trial

**Free trial:** signed up ~2026-05-12, expires ~2026-08-10 (90 days). ~$300 credit.
**Current burn rate:** ~$0.33/day (after Cloud SQL downgrade from db-perf-optimized-N-8 to db-f1-micro on 2026-05-15).
**Credit will outlast the trial** (~$30 used in 90 days, ~$270 unspent at expiry — unspent credit disappears).

**What happens at trial end (~2026-08-10):**
- Without billing enabled → all resources deleted
- With billing enabled → app continues, ~$10/month from card

**Decision to make by ~2026-08-01:**

**Option A — Enable billing + migrate SQL to Supabase (~$1/month forever):**
- Cloud Run: $0 (Always Free, permanent)
- Supabase PostgreSQL: $0 (free tier, 500MB — app uses ~57MB)
- Everything else: ~$1/month (Artifact Registry + Secret Manager)
- Migration: `pg_dump` locally → restore to Supabase → update `DATABASE_URL` secret → redeploy

**Option B — Enable billing + keep Cloud SQL db-f1-micro (~$10/month):**
- Simpler, no migration needed, just activate billing before trial ends

**Option C — Don't enable billing → migrate everything to free hosts before 2026-08-10:**
- DB → Supabase/Neon (free PostgreSQL)
- App → Render/Railway (free Cloud Run alternative)
- No ongoing cost, but loses GCP infrastructure

**Recommended:** Option A. Migrate SQL to Supabase ~2 weeks before trial ends, then enable billing. Total cost ~$1/month permanently. Card won't see meaningful charges.

**Artifact Registry cleanup policy:** set 2026-05-15 — keeps last 5 images, deletes images older than 7 days. Was 7.6GB, will shrink automatically.

---

## User context

- Polish retail investor, IKE account, ~500 PLN/month contributions
- Core holding: VWCE.DE (UCITS ACWI ETF, EUR-denominated on Xetra)
- Decision frequency: monthly — this is NOT a trading app
- The app should make fewer bad decisions, not more frequent ones
- IKE annual limits: 2025 = 26,019 PLN; 2026 = 28,260 PLN

---

## Remaining work (enhancements only — app is fully functional)

### ⚠️ Unfinished from last session — do first next time

**KM survival + PCA tables are empty on Cloud SQL (production).** Locally populated, but Cloud Run pipeline failed to reach steps 11-12 (regime_duration, correlation_pca) because the yfinance prices step took 600s and the full pipeline ran overtime. Fix options:
- Option A (easiest): manually run `ml/regime_duration.py compute` and `ml/correlation_pca.py compute` pointing at Cloud SQL. Requires setting `DATABASE_URL` to the Cloud SQL connection string temporarily, or using the Cloud SQL Auth proxy.
- Option B: trigger the daily Cloud Scheduler pipeline (runs Mon–Fri 06:00 Warsaw) — it will naturally populate the tables next morning.
- Option C: the pipeline already ran in background on Cloud Run — it may have completed overnight. Check `/regime-duration` endpoint first before doing anything.

The app is fully functional without these tables (regime_duration and correlation cards show `—` gracefully). It's cosmetic for now.

**URL / access:** App is live at `https://investor-intelligence-1062085617181.europe-central2.run.app`. Share with friends using **Dev mode** (Tryb deweloperski button) — no Google account needed. Only `szymkas02@gmail.com` can sign in with Google.

**Custom domain:** not yet set up. Options: buy a domain (~40 PLN/yr), or use Firebase Hosting proxy (free, subdomain of `web.app`). Discuss in next session if desired.

---

### ✅ Completed this session (ML rewrite + UX overhaul)

- **Deleted** circular LightGBM regime classifier (`ml/regime.py`) + `regime_predictions` table
- **Added** Kaplan-Meier survival analysis (`ml/regime_duration.py`) — HMM-based episodes, 4 states
- **Added** rolling PCA correlation / diversification index (`ml/correlation_pca.py`)
- **Promoted** HMM to primary regime signal — `backend/hmm_utils.py` handles all 4 states incl. stagflation underflow
- **Rewired** decision engine to HMM + recession (no LightGBM dependency)
- **Dashboard redesigned** — verdict banner first, all technical panels collapsed with ⓘ plain-language explanations
- **Signal cards redesigned** — plain one-line summary visible by default, detail behind ▼
- **Added** earnings growth / current market dynamics disclaimer to projection

### ML improvements still needed

1. **Current market dynamics blind spot** ← **MUST ADDRESS IN NEXT SESSION**
   All models are backward-looking (valuation + macro). They cannot see that S&P 500 earnings grew ~30% 2023-2026 partly due to AI/tech structural changes. A CAPE=39 in 2026 may be justified by permanently higher margins — historical comparisons pre-AI era may systematically overstate risk. Possible approaches:
   - Add forward P/E (analyst consensus EPS estimates) alongside trailing CAPE as a second valuation signal
   - Add earnings growth trend (5Y EPS CAGR) as a feature — if earnings growing >10%/yr, dampen CAPE warning
   - Track CAPE vs sector-adjusted CAPE (tech-heavy S&P vs MSCI World have different fair values)
   - Simplest: show both CAPE and forward P/E on dashboard; let user judge the gap

2. **Volatility forecaster — benchmark against GARCH** — RF likely doesn't beat GARCH(1,1). Should benchmark. Consider adding VVIX as feature.

3. **FX direction useless at 21d+** — Already reframed as uncertainty tool. Next: benchmark median vs random walk; consider dropping 21d horizon, keeping only 63d.

4. **CAPE — US-only overstates risk for global portfolio** — VWCE.DE is 60% US + 40% non-US. European/EM CAPE is often 12-15. Consider: weighted global CAPE using VWCE geographic allocation from StarCapital/Research Affiliates.

5. **Recession look-ahead bias** — NBER declares recessions 6-18 months late. Switch to FRED-MD vintage + Conference Board LEI + ISM PMI for real-time leading indicator signal.

6. **HMM Gaussian tails** — Switch to Student-t emissions for better tail behaviour. Monthly data → daily resolution mismatch.

### Not yet implemented

1. **Multi-step AI reasoning loop** — Gemini calls one tool per turn max. True chaining not yet done.
2. **Structured AI output** — Gemini returns prose; could return JSON for UI rendering.
3. **ETF allocation freshness** — `etf_allocations` uses hardcoded factsheet values. iShares auto-refresh exists but may block.
4. **Pipeline structured logging** — `ingestion/pipeline.py` uses `print()`, invisible in Cloud Run logs.

### Known minor issues

- Gold 21d return chart may render blank for small values — Y-axis scale issue
- IKE tracking uses buy transactions as proxy for contributions (by design, documented in UI)
- HMM `stagflation` label is misleading — it's actually the "expensive market / compressed equity premium" cluster. The label was assigned post-hoc; CAPE=39 is 2× the cluster centroid (CAPE~20). The model is extrapolating outside training data when assigning this state. This is disclosed in the ⓘ explanation but could be addressed by retraining HMM with more recent data or relabelling the cluster.
