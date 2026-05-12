"""Cloud Function: ingest macro data into Cloud SQL PostgreSQL."""
import sys, functions_framework
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

@functions_framework.http
def ingest_macro(request):
    try:
        from ingestion.macro import run as run_macro
        from ingestion.ecb import run as run_ecb
        from ingestion.econdb import run as run_econdb
        from ingestion.stooq import run as run_stooq
        run_macro(); run_ecb(); run_econdb(); run_stooq()
        msg = "Macro ingestion complete"
        print(msg); return (msg, 200)
    except Exception as e:
        return (f"ERROR: {e}", 500)
