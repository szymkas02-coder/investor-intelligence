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
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements-backend.txt

COPY backend/   ./backend/
COPY db/        ./db/
COPY ml/        ./ml/
COPY ingestion/ ./ingestion/
COPY processing/ ./processing/
COPY utils/     ./utils/
COPY shiller.csv ./shiller.csv

# Models are downloaded into build context by Cloud Build (cloudbuild.yaml)
RUN mkdir -p ./models
COPY models/ ./models/

# Copy built React app into a location FastAPI will serve as static files
COPY --from=frontend-build /frontend/dist ./frontend/dist

ENV PORT=8080

EXPOSE 8080

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
