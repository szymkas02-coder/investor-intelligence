"""Cloud Function: ingest sentiment/calendar into Cloud SQL PostgreSQL."""
import sys, functions_framework
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

@functions_framework.http
def ingest_sentiment(request):
    try:
        from ingestion.sentiment import run
        run()
        msg = "Sentiment ingestion complete"
        print(msg); return (msg, 200)
    except Exception as e:
        return (f"ERROR: {e}", 500)
