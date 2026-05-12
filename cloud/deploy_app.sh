#!/bin/bash
# cloud/deploy_app.sh — Build and deploy to Cloud Run (PostgreSQL backend)
#
# Architecture:
#   - Single Cloud Run container: FastAPI backend + React static files
#   - Database: Cloud SQL PostgreSQL (private, accessed via Unix socket)
#   - Secrets: Secret Manager (DATABASE_URL, API keys, JWT secret)
#   - Auto-deploy: Cloud Build trigger on git push (set up separately via cloudbuild.yaml)
#
# One-time prerequisites (run once, then use Cloud Build for future deploys):
#   gcloud auth login
#   gcloud config set project YOUR_PROJECT_ID
#   gcloud services enable \
#     run.googleapis.com \
#     sqladmin.googleapis.com \
#     secretmanager.googleapis.com \
#     artifactregistry.googleapis.com \
#     cloudbuild.googleapis.com
#
# Usage:
#   bash cloud/deploy_app.sh PROJECT_ID [REGION] [SQL_INSTANCE_NAME]
#
# Example:
#   bash cloud/deploy_app.sh my-investor-app europe-west1 investor-pg

set -euo pipefail

PROJECT_ID=${1:?Usage: deploy_app.sh PROJECT_ID [REGION] [SQL_INSTANCE_NAME]}
REGION=${2:-europe-west1}
SQL_INSTANCE=${3:-investor-pg}
SERVICE_NAME="investor-intelligence"
IMAGE_NAME="${REGION}-docker.pkg.dev/${PROJECT_ID}/investor/${SERVICE_NAME}"
SA_EMAIL="${SERVICE_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
SQL_CONN_NAME="${PROJECT_ID}:${REGION}:${SQL_INSTANCE}"

echo "========================================"
echo "  Investor Intelligence — Cloud Run Deploy"
echo "  Project  : ${PROJECT_ID}"
echo "  Region   : ${REGION}"
echo "  Image    : ${IMAGE_NAME}"
echo "  Cloud SQL: ${SQL_CONN_NAME}"
echo "========================================"
echo ""

# ─── 1. Artifact Registry ────────────────────────────────────────────────────
echo "[1/6] Ensuring Artifact Registry repository exists..."
gcloud artifacts repositories create investor \
  --repository-format=docker \
  --location="${REGION}" \
  --project="${PROJECT_ID}" 2>/dev/null || true

# ─── 2. Build and push image ─────────────────────────────────────────────────
echo "[2/6] Building Docker image (multi-stage: Node frontend + Python backend)..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

# Build from repo root; Dockerfile handles Node build then Python layer
docker build -t "${IMAGE_NAME}:latest" .
docker push "${IMAGE_NAME}:latest"
echo "  Image pushed: ${IMAGE_NAME}:latest"

# ─── 3. Service account ──────────────────────────────────────────────────────
echo "[3/6] Ensuring service account exists..."
gcloud iam service-accounts create "${SERVICE_NAME}" \
  --display-name="Investor Intelligence App" \
  --project="${PROJECT_ID}" 2>/dev/null || true

# Cloud SQL Client role — required to connect via Unix socket
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/cloudsql.client" --quiet

# Secret Manager accessor
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor" --quiet

# ─── 4. Secrets reminder ─────────────────────────────────────────────────────
echo "[4/6] Checking secrets..."
echo ""
echo "  Required secrets in Secret Manager (create if missing):"
echo ""
echo "    gcloud secrets create DATABASE_URL --data-file=-"
echo "    # paste: postgresql://postgres:PASSWORD@/investor_intelligence?host=/cloudsql/${SQL_CONN_NAME}"
echo ""
echo "    gcloud secrets create APP_SECRET          --data-file=- <<< 'YOUR_JWT_SECRET'"
echo "    gcloud secrets create GOOGLE_CLIENT_ID    --data-file=- <<< 'YOUR_OAUTH_CLIENT_ID'"
echo "    gcloud secrets create GOOGLE_CLIENT_SECRET --data-file=- <<< 'YOUR_OAUTH_SECRET'"
echo "    gcloud secrets create GEMINI_API_KEY      --data-file=- <<< 'YOUR_GEMINI_KEY'"
echo "    gcloud secrets create FRED_API_KEY        --data-file=- <<< 'YOUR_FRED_KEY'"
echo "    gcloud secrets create STOOQ_API_KEY       --data-file=- <<< 'YOUR_STOOQ_KEY'"
echo "    gcloud secrets create FINNHUB_API_KEY     --data-file=- <<< 'YOUR_FINNHUB_KEY'"
echo ""
echo "  Note: DATABASE_URL uses Unix socket format (not TCP) for Cloud SQL."
echo "  Format: postgresql://USER:PASSWORD@/DBNAME?host=/cloudsql/PROJECT:REGION:INSTANCE"
echo ""

# ─── 5. Deploy to Cloud Run ──────────────────────────────────────────────────
echo "[5/6] Deploying to Cloud Run..."

gcloud run deploy "${SERVICE_NAME}" \
  --image="${IMAGE_NAME}:latest" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --service-account="${SA_EMAIL}" \
  --platform=managed \
  --allow-unauthenticated \
  --port=8080 \
  --memory=1Gi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=3 \
  --concurrency=10 \
  --timeout=120 \
  --add-cloudsql-instances="${SQL_CONN_NAME}" \
  --set-secrets="\
DATABASE_URL=DATABASE_URL:latest,\
APP_SECRET=APP_SECRET:latest,\
GOOGLE_CLIENT_ID=GOOGLE_CLIENT_ID:latest,\
GOOGLE_CLIENT_SECRET=GOOGLE_CLIENT_SECRET:latest,\
GEMINI_API_KEY=GEMINI_API_KEY:latest,\
FRED_API_KEY=FRED_API_KEY:latest,\
STOOQ_API_KEY=STOOQ_API_KEY:latest,\
FINNHUB_API_KEY=FINNHUB_API_KEY:latest"

SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format="value(status.url)")

# ─── 6. Smoke test ───────────────────────────────────────────────────────────
echo "[6/6] Smoke testing..."
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${SERVICE_URL}/health")
if [ "${HTTP_STATUS}" = "200" ]; then
  echo "  Health check passed (HTTP 200)"
else
  echo "  WARNING: Health check returned HTTP ${HTTP_STATUS}"
fi

echo ""
echo "========================================"
echo "  Deployment complete!"
echo "  Service URL : ${SERVICE_URL}"
echo "  Swagger UI  : ${SERVICE_URL}/docs"
echo "========================================"
echo ""
echo "  Post-deploy checklist:"
echo "  1. Add ${SERVICE_URL}/auth/callback to Google OAuth authorised redirect URIs"
echo "  2. Add ${SERVICE_URL} to CORS allow_origins in backend/main.py if needed"
echo "  3. Set up Cloud Build trigger for auto-deploy on git push (see cloudbuild.yaml)"
