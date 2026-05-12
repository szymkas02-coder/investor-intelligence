"""
backend/routers/pipeline.py — Trigger the ingestion pipeline

POST /pipeline/run
  Kicks off the full ingestion + feature build + regime labeling as a
  background task. Returns immediately with a started_at timestamp.
  The GCP Cloud Functions version (cloud/functions/) does the same thing
  on a schedule; this endpoint is for manual triggers from the UI.
"""

import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends

from backend.auth import get_current_user
from backend.models import PipelineRunResponse

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

PROJECT_ROOT = Path(__file__).parent.parent.parent


def _run_pipeline():
    """Run ingestion pipeline as subprocess — keeps FastAPI thread free."""
    subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "ingestion" / "pipeline.py")],
        cwd=str(PROJECT_ROOT),
        check=False,
    )


@router.post("/run", response_model=PipelineRunResponse)
def trigger_pipeline(
    background_tasks: BackgroundTasks,
    _user: Annotated[str, Depends(get_current_user)],
):
    background_tasks.add_task(_run_pipeline)
    return PipelineRunResponse(
        status     = "started",
        started_at = datetime.utcnow(),
        message    = "Pipeline started in background. Check logs for progress.",
    )
