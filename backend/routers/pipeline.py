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
    run(skip_fundamentals=True)


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
):
    _check_pipeline_auth(authorization)
    background_tasks.add_task(_run_pipeline)
    return PipelineRunResponse(
        status     = "started",
        started_at = datetime.utcnow(),
        message    = "Pipeline started in background. Check logs for progress.",
    )
