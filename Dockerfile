# ── Stage 1: build React frontend ────────────────────────────────────────────
FROM node:20-slim AS frontend-build

WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci

# VITE_API_URL is empty so that the built JS calls the same origin (Cloud Run).
# The FastAPI backend serves the static files, so the browser hits the same host.
ARG VITE_API_URL=""
ENV VITE_API_URL=${VITE_API_URL}

COPY frontend/ ./
RUN npm run build
# Output: /frontend/dist


# ── Stage 2: Python backend + static files ────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

COPY requirements-backend.txt .
RUN pip install --no-cache-dir -r requirements-backend.txt

COPY backend/   ./backend/
COPY db/        ./db/
COPY ml/        ./ml/
COPY ingestion/ ./ingestion/
COPY processing/ ./processing/
COPY utils/     ./utils/
COPY shiller.csv ./shiller.csv

# Download ML model artifacts from GCS at build time
RUN mkdir -p ./models
RUN pip install --no-cache-dir google-cloud-storage==2.18.2
RUN python - <<'EOF'
from google.cloud import storage
import os, pathlib
bucket = storage.Client().bucket("investor-intelligence-496113-backup")
models_dir = pathlib.Path("./models")
for blob in bucket.list_blobs(prefix="models/"):
    fname = blob.name.split("/", 1)[1]
    if fname:
        blob.download_to_filename(str(models_dir / fname))
        print(f"Downloaded {fname}")
EOF

# Copy built React app into a location FastAPI will serve as static files
COPY --from=frontend-build /frontend/dist ./frontend/dist

ENV PORT=8080

EXPOSE 8080

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
