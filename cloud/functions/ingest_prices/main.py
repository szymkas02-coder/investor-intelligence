"""Cloud Function: ingest ETF prices into Cloud SQL PostgreSQL."""
import sys, functions_framework
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

@functions_framework.http
def ingest_prices(request):
    try:
        from ingestion.prices import run
        results = run()
        total = sum(r["rows"] for r in results.values())
        errors = [t for t, r in results.items() if r["error"]]
        msg = f"Prices ingested: {total} rows. Errors: {errors or []}"
        print(msg); return (msg, 200)
    except Exception as e:
        return (f"ERROR: {e}", 500)
