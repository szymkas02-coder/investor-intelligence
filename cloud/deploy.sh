#!/bin/bash
# cloud/deploy.sh — Deploy Cloud Functions and Scheduler jobs to GCP
#
# Prerequisites:
#   gcloud auth login
#   gcloud config set project YOUR_PROJECT_ID
#   gcloud services enable cloudfunctions.googleapis.com cloudscheduler.googleapis.com
#
# Usage:
#   bash cloud/deploy.sh YOUR_PROJECT_ID YOUR_REGION YOUR_GCS_BUCKET

set -e

PROJECT_ID=${1:?Usage: deploy.sh PROJECT_ID REGION GCS_BUCKET}
REGION=${2:-europe-west1}
GCS_BUCKET=${3:?Usage: deploy.sh PROJECT_ID REGION GCS_BUCKET}
SA_EMAIL="investor-pipeline@${PROJECT_ID}.iam.gserviceaccount.com"

echo "Deploying to project=${PROJECT_ID}, region=${REGION}, bucket=${GCS_BUCKET}"

# ─── Create GCS bucket if it doesn't exist ──────────────────────────────────
gsutil mb -p "${PROJECT_ID}" -l "${REGION}" "gs://${GCS_BUCKET}" 2>/dev/null || true

# ─── Create service account ─────────────────────────────────────────────────
gcloud iam service-accounts create investor-pipeline \
  --display-name="Investor Intelligence Pipeline" \
  --project="${PROJECT_ID}" 2>/dev/null || true

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/storage.objectAdmin"

# ─── Store secrets in Secret Manager ────────────────────────────────────────
# WHY Secret Manager not env vars in source code:
# Env vars in function source would appear in gcloud describe output and logs.
# Secret Manager injects at runtime, never stored in git or function metadata.
echo "Ensure secrets are set in Secret Manager:"
echo "  gcloud secrets create FRED_API_KEY --data-file=- <<< 'YOUR_KEY'"
echo "  gcloud secrets create FINNHUB_API_KEY --data-file=- <<< 'YOUR_KEY'"
echo "  gcloud secrets create STOOQ_API_KEY --data-file=- <<< 'YOUR_KEY'"

# ─── Deploy Cloud Functions ──────────────────────────────────────────────────
FUNCTIONS=(
  "ingest_prices:ingest_prices"
  "ingest_macro:ingest_macro"
  "ingest_sentiment:ingest_sentiment"
  "run_ml_pipeline:run_ml_pipeline"
)

for entry in "${FUNCTIONS[@]}"; do
  DIR="${entry%%:*}"
  ENTRY="${entry##*:}"

  echo ""
  echo "Deploying ${DIR} ..."

  # Copy shared source into the function directory for deployment
  # WHY: Cloud Functions deploy from a single directory. We copy the shared
  # modules (ingestion/, processing/, ml/, db/) alongside the function's
  # main.py so the function can import them.
  DEPLOY_DIR="cloud/functions/${DIR}"
  cp -r ingestion processing ml db "${DEPLOY_DIR}/" 2>/dev/null || true

  gcloud functions deploy "${DIR}" \
    --gen2 \
    --runtime=python311 \
    --region="${REGION}" \
    --source="${DEPLOY_DIR}" \
    --entry-point="${ENTRY}" \
    --trigger-http \
    --no-allow-unauthenticated \
    --service-account="${SA_EMAIL}" \
    --set-env-vars="GCS_BUCKET=${GCS_BUCKET}" \
    --set-secrets="FRED_API_KEY=FRED_API_KEY:latest,FINNHUB_API_KEY=FINNHUB_API_KEY:latest,STOOQ_API_KEY=STOOQ_API_KEY:latest" \
    --memory=1Gi \
    --timeout=540s \
    --project="${PROJECT_ID}"

  FUNCTION_URL=$(gcloud functions describe "${DIR}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --format="value(serviceConfig.uri)")

  # ─── Create/update Cloud Scheduler job ──────────────────────────────────
  SCHEDULE=""
  case "${DIR}" in
    ingest_macro)      SCHEDULE="0 8 * * *"     ;;
    ingest_sentiment)  SCHEDULE="0 20 * * 1-5"  ;;
    ingest_prices)     SCHEDULE="0 22 * * 1-5"  ;;
    run_ml_pipeline)   SCHEDULE="0 23 * * 1-5"  ;;
  esac

  if [ -n "${SCHEDULE}" ]; then
    gcloud scheduler jobs create http "daily-${DIR}" \
      --schedule="${SCHEDULE}" \
      --uri="${FUNCTION_URL}" \
      --time-zone="Europe/Warsaw" \
      --attempt-deadline=540s \
      --oidc-service-account-email="${SA_EMAIL}" \
      --location="${REGION}" \
      --project="${PROJECT_ID}" 2>/dev/null || \
    gcloud scheduler jobs update http "daily-${DIR}" \
      --schedule="${SCHEDULE}" \
      --uri="${FUNCTION_URL}" \
      --time-zone="Europe/Warsaw" \
      --attempt-deadline=540s \
      --oidc-service-account-email="${SA_EMAIL}" \
      --location="${REGION}" \
      --project="${PROJECT_ID}"
  fi

  echo "  Deployed ${DIR} -> ${FUNCTION_URL}"
done

# ─── Weekly fundamentals scheduler ──────────────────────────────────────────
PRICES_URL=$(gcloud functions describe ingest_prices \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format="value(serviceConfig.uri)")

gcloud scheduler jobs create http "weekly-fundamentals" \
  --schedule="0 10 * * 0" \
  --uri="${PRICES_URL}" \
  --time-zone="Europe/Warsaw" \
  --attempt-deadline=600s \
  --oidc-service-account-email="${SA_EMAIL}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}" \
  --headers="X-Run-Fundamentals=true" 2>/dev/null || true

echo ""
echo "Deployment complete."
echo "Run 'gcloud scheduler jobs list --location=${REGION}' to verify jobs."
