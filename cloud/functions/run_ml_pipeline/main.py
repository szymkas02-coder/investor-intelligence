"""Cloud Function: run feature engineering + ML inference against Cloud SQL."""
import sys, functions_framework
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

@functions_framework.http
def run_ml_pipeline(request):
    try:
        from processing.features import build_features
        from processing.labels import run as run_labels
        from processing.qc import run as run_qc
        build_features()
        run_labels()
        run_qc()
        msg = "ML pipeline complete"
        print(msg); return (msg, 200)
    except Exception as e:
        return (f"ERROR: {e}", 500)
