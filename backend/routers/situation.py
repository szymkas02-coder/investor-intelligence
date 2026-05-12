"""
backend/routers/situation.py — Situation Room: AI-generated macro briefings + chat

GET  /situation         — latest pulse + latest briefing
POST /situation/refresh — manual trigger (rate-limited: once per 24h)
POST /chat              — Gemma chat assistant with context injection
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.auth import get_current_user
from backend.database import get_db, get_db_write

logger = logging.getLogger(__name__)

router = APIRouter(tags=["situation"])

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

SITUATION_MODEL = "gemini-2.5-flash"  # best free-tier model, supports Search grounding; 20 RPD (we use ~5/day)
CHAT_MODEL      = "gemini-3.1-flash-lite"  # 500 RPD, confirmed working — good for interactive chat

PULSE_PROMPT = """You are a macro analyst. Search the web for the latest economic and market news from the last 24 hours.

Focus on:
- Central bank decisions or signals (Fed, ECB, NBP)
- Inflation data releases (CPI, PPI)
- Key economic indicators (PMI, jobs, GDP)
- Major market moves or risk events
- Events relevant to global equity ETF investors (ACWI/VWCE)

Return exactly 4-6 bullet points. Each bullet: one sentence, factual, include the date if known.
Format: markdown bullet list. No intro text, no conclusion."""

BRIEFING_PROMPT = """You are a senior investment strategist. Search the web for current macro conditions.

You are writing a weekly briefing for a Polish retail investor who holds VWCE.DE (UCITS ACWI global equity ETF) in an IKE tax-advantaged account. They invest ~500 PLN/month and make monthly decisions: invest now, DCA, or wait.

Write a structured briefing with exactly these four sections:

## Macro Outlook
2-3 sentences on global growth, inflation trajectory, and central bank stance.

## Market Regime
2-3 sentences on equity market conditions, risk sentiment, and volatility environment.

## Key Risks
3-4 bullet points of the main risks to global equities over the next 1-3 months.

## For VWCE Investors
2-3 sentences: what does the current environment mean for a monthly DCA investor in a global ETF? Any reason to pause, accelerate, or stay the course?

Be direct and specific. No generic disclaimers."""


def _get_genai_client():
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY not configured.")
    from google import genai
    return genai.Client(api_key=GEMINI_API_KEY)


def _get_app_context(db) -> str:
    """Build a short text summary of current app signals to inject into chat."""
    try:
        # Latest decision signal
        dec = db.execute("""
            SELECT regime_pred, prob_risk_on, prob_risk_off
            FROM regime_predictions
            ORDER BY date DESC, predicted_at DESC LIMIT 1
        """).fetchone()

        vol = db.execute("""
            SELECT vol_forecast FROM volatility_forecasts
            WHERE horizon_days = 21
            ORDER BY date DESC, predicted_at DESC LIMIT 1
        """).fetchone()

        macro = db.execute("""
            SELECT vix_close, cpi_us_yoy, fed_funds_rate, eurpln, spread_10y_2y
            FROM daily_features
            WHERE vix_close IS NOT NULL
            ORDER BY date DESC LIMIT 1
        """).fetchone()

        rec = db.execute("""
            SELECT recession_prob FROM recession_predictions
            ORDER BY date DESC, predicted_at DESC LIMIT 1
        """).fetchone()

        def fmt(v, spec):
            return format(v, spec) if v is not None else "n/a"

        lines = ["=== Current App Signals ==="]
        if dec:
            lines.append(f"Regime: {dec[0]} (risk-on prob: {fmt(dec[1], '.0%')}, risk-off prob: {fmt(dec[2], '.0%')})")
        if vol:
            lines.append(f"21-day volatility forecast: {fmt(vol[0], '.1%')}")
        if macro:
            lines.append(f"VIX: {fmt(macro[0], '.1f')} | CPI US YoY: {fmt(macro[1], '.1%')} | Fed rate: {fmt(macro[2], '.2%')}")
            lines.append(f"EUR/PLN: {fmt(macro[3], '.4f')} | Yield curve spread (10y-2y): {fmt(macro[4], '.2%')}")
        if rec:
            lines.append(f"Recession probability: {fmt(rec[0], '.0%')}")

        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Could not fetch app context: {e}")
        return ""


def _get_latest_briefings(db) -> tuple[str, str]:
    """Return (latest pulse content, latest briefing content) or empty strings."""
    pulse = db.execute("""
        SELECT content FROM situation_updates
        WHERE type = 'pulse' ORDER BY created_at DESC LIMIT 1
    """).fetchone()
    briefing = db.execute("""
        SELECT content FROM situation_updates
        WHERE type = 'briefing' ORDER BY created_at DESC LIMIT 1
    """).fetchone()
    return (pulse[0] if pulse else "", briefing[0] if briefing else "")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/situation")
def get_situation(
    db:      Annotated[object, Depends(get_db)],
    _user:   Annotated[str, Depends(get_current_user)],
):
    pulse_row = db.execute("""
        SELECT content, created_at FROM situation_updates
        WHERE type = 'pulse' ORDER BY created_at DESC LIMIT 1
    """).fetchone()

    briefing_row = db.execute("""
        SELECT content, created_at FROM situation_updates
        WHERE type = 'briefing' ORDER BY created_at DESC LIMIT 1
    """).fetchone()

    return {
        "pulse": {
            "content":    pulse_row[0] if pulse_row else None,
            "created_at": pulse_row[1].isoformat() if pulse_row else None,
        },
        "briefing": {
            "content":    briefing_row[0] if briefing_row else None,
            "created_at": briefing_row[1].isoformat() if briefing_row else None,
        },
    }


@router.post("/situation/refresh")
def refresh_situation(
    db:      Annotated[object, Depends(get_db_write)],
    _user:   Annotated[str, Depends(get_current_user)],
):
    """Manual refresh — rate-limited to once per 24h per type."""
    last = db.execute("""
        SELECT created_at FROM situation_updates
        WHERE type = 'pulse'
        ORDER BY created_at DESC LIMIT 1
    """).fetchone()

    if last:
        age = datetime.now(timezone.utc) - last[0].replace(tzinfo=timezone.utc)
        if age < timedelta(hours=24):
            remaining = int((timedelta(hours=24) - age).total_seconds() / 3600)
            raise HTTPException(
                status_code=429,
                detail=f"Last refresh was {int(age.total_seconds()/3600)}h ago. Next allowed in ~{remaining}h.",
            )

    client = _get_genai_client()
    from google.genai import types

    search_tool = types.Tool(google_search=types.GoogleSearch())
    config = types.GenerateContentConfig(tools=[search_tool])

    try:
        pulse_resp = client.models.generate_content(
            model=SITUATION_MODEL,
            contents=PULSE_PROMPT,
            config=config,
        )
        pulse_text = pulse_resp.text
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini API error: {e}")

    db.execute("""
        INSERT INTO situation_updates (type, content, model_used)
        VALUES (%s, %s, %s)
    """, ("pulse", pulse_text, SITUATION_MODEL))
    db.commit()

    return {"status": "ok", "message": "Pulse refreshed.", "content": pulse_text}


class ChatRequest(BaseModel):
    message: str


@router.post("/chat")
def chat(
    req:     ChatRequest,
    db:      Annotated[object, Depends(get_db)],
    _user:   Annotated[str, Depends(get_current_user)],
):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    client = _get_genai_client()
    from google.genai import types

    # Build context from app signals + stored briefings
    app_ctx = _get_app_context(db)
    pulse_txt, briefing_txt = _get_latest_briefings(db)

    system_parts = [
        "You are a personal investment assistant for a Polish retail investor.",
        "They hold VWCE.DE (UCITS global equity ETF) in an IKE tax-advantaged account.",
        "They invest ~500 PLN/month and make monthly decisions: invest now, DCA, or wait.",
        "Answer concisely and in the same language the user writes in (Polish or English).",
        "Do not give personalised financial advice — explain data and context instead.",
    ]
    if app_ctx:
        system_parts += ["", app_ctx]
    if briefing_txt:
        system_parts += ["", "=== Latest Weekly Briefing ===", briefing_txt]
    if pulse_txt:
        system_parts += ["", "=== Latest News Pulse ===", pulse_txt]

    system_instruction = "\n".join(system_parts)

    try:
        response = client.models.generate_content(
            model=CHAT_MODEL,
            contents=req.message,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.7,
            ),
        )
        return {"reply": response.text}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI error: {e}")
