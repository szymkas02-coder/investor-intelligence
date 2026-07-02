"""
backend/routers/pipeline.py — Trigger the ingestion pipeline

POST /pipeline/run
  Kicks off the full ingestion + feature build + regime labeling as a
  background task. Returns immediately with a started_at timestamp.
  The GCP Cloud Functions version (cloud/functions/) does the same thing
  on a schedule; this endpoint is for manual triggers from the UI.
"""

from datetime import datetime
from pathlib import Path
import os

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from typing import Optional

from backend.models import PipelineRunResponse

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

PROJECT_ROOT = Path(__file__).parent.parent.parent

# Optional secret for manual triggers from UI or curl.
# Cloud Scheduler bypasses this via GCP IAM (OIDC) at the Cloud Run level.
PIPELINE_SECRET = os.getenv("PIPELINE_SECRET", "")

SCHEDULER_SA = "investor-intelligence@investor-intelligence-496113.iam.gserviceaccount.com"


def _run_pipeline():
    """Run ingestion pipeline in-process so Cloud Run doesn't kill it."""
    import sys
    sys.path.insert(0, str(PROJECT_ROOT))
    from ingestion.pipeline import run
    return run(skip_fundamentals=True)


def _summarise(results: dict) -> dict:
    """Collapse the full per-step result dict to a compact status summary."""
    return {k: v.get("status") for k, v in results.items() if isinstance(v, dict)}


def _check_pipeline_auth(authorization: Optional[str]):
    """
    Accept the request if any of these are true:
    1. No PIPELINE_SECRET configured (dev mode / open)
    2. Authorization header is a Bearer token matching PIPELINE_SECRET
    3. Authorization header is a Google OIDC token from the scheduler SA
    """
    if not PIPELINE_SECRET:
        return  # dev mode — open

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    token = authorization.removeprefix("Bearer ")

    # Simple secret match
    if token == PIPELINE_SECRET:
        return

    # OIDC token from Cloud Scheduler — verify email claim
    try:
        import jwt as pyjwt
        # Decode without verification just to read the email claim
        # (Cloud Run IAM already verified the OIDC signature before we get here)
        claims = pyjwt.decode(token, options={"verify_signature": False})
        if claims.get("email") == SCHEDULER_SA:
            return
    except Exception:
        pass

    raise HTTPException(status_code=401, detail="Unauthorized")


@router.post("/run", response_model=PipelineRunResponse)
def trigger_pipeline(
    background_tasks: BackgroundTasks,
    authorization: Optional[str] = Header(None),
    wait: bool = False,
):
    """
    Trigger the ingestion pipeline.

    wait=false (default): fire-and-forget as a background task. Good for the UI
      "Refresh" button so the browser gets an immediate response.

    wait=true: run the pipeline SYNCHRONOUSLY and only return once it finishes.
      REQUIRED on Cloud Run: with the default (background task), Cloud Run returns
      the 200, throttles CPU to ~0, and reaps the scaled-to-zero instance before
      the background work completes — so scheduled runs never actually finish and
      the data goes stale. Holding the request open keeps CPU allocated and the
      instance alive for the whole run. Cloud Scheduler must therefore call this
      with ?wait=true and an attempt-deadline >= pipeline runtime.
    """
    _check_pipeline_auth(authorization)
    started_at = datetime.utcnow()

    if wait:
        results = _run_pipeline()
        summary = _summarise(results or {})
        errors  = [k for k, s in summary.items() if s == "error"]
        return PipelineRunResponse(
            status     = "error" if errors else "completed",
            started_at = started_at,
            message    = (
                f"Pipeline finished with errors in: {errors}"
                if errors else "Pipeline completed successfully."
            ),
            results    = summary,
        )

    background_tasks.add_task(_run_pipeline)
    return PipelineRunResponse(
        status     = "started",
        started_at = started_at,
        message    = "Pipeline started in background. Check logs for progress.",
    )
