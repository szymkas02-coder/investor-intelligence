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

from backend.auth import get_current_user, require_non_guest
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
    require_non_guest(_user)
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


_CHAT_HISTORY_TURNS = 10  # how many past turns (user+assistant pairs) to inject


@router.get("/chat/history")
def get_chat_history(
    db:      Annotated[object, Depends(get_db)],
    user_id: Annotated[str, Depends(get_current_user)],
):
    """Return last N chat turns for display in the UI on page load."""
    rows = db.execute("""
        SELECT role, content, created_at FROM (
            SELECT role, content, created_at
            FROM chat_history
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        ) sub ORDER BY created_at ASC
    """, [user_id, _CHAT_HISTORY_TURNS * 2]).fetchall()
    return {"messages": [{"role": r[0], "text": r[1]} for r in rows]}


# ---------------------------------------------------------------------------
# Tool implementations — called when Gemini requests them
# ---------------------------------------------------------------------------

def _tool_get_signals(db) -> dict:
    """Return current ML signals."""
    try:
        regime = db.execute("""
            SELECT date, regime_pred, prob_risk_on, prob_risk_off, prob_stagflation, prob_deflation
            FROM regime_predictions ORDER BY date DESC, predicted_at DESC LIMIT 1
        """).fetchone()
        vol = db.execute("""
            SELECT horizon_days, vol_forecast FROM volatility_forecasts
            WHERE horizon_days IN (21, 63) ORDER BY date DESC, predicted_at DESC LIMIT 2
        """).fetchall()
        rec = db.execute("""
            SELECT date, recession_prob FROM recession_predictions
            ORDER BY date DESC, predicted_at DESC LIMIT 1
        """).fetchone()
        cape = db.execute("""
            SELECT date, cape, ret_q50 FROM cape_forecasts
            ORDER BY date DESC LIMIT 1
        """).fetchone()
        result = {}
        if regime:
            result["regime"] = {
                "date": str(regime[0]), "label": regime[1],
                "prob_risk_on": round(regime[2], 3), "prob_risk_off": round(regime[3], 3),
                "prob_stagflation": round(regime[4], 3), "prob_deflation": round(regime[5], 3),
            }
        if vol:
            result["volatility"] = [{"horizon_days": r[0], "forecast_annualised": round(r[1], 4)} for r in vol]
        if rec:
            result["recession"] = {"date": str(rec[0]), "probability": round(rec[1], 3)}
        if cape:
            result["cape"] = {"date": str(cape[0]), "value": round(cape[1], 1), "implied_10y_real_return": round(cape[2], 4)}
        return result
    except Exception as e:
        return {"error": str(e)}


def _tool_get_decision(db) -> dict:
    """Return current monthly investment recommendation."""
    try:
        from backend.routers.decision import _make_decision
        regime_row = db.execute("""
            SELECT date, prob_risk_off, prob_stagflation FROM regime_predictions
            ORDER BY date DESC, predicted_at DESC LIMIT 1
        """).fetchone()
        vol_row = db.execute("""
            SELECT vol_forecast FROM volatility_forecasts
            WHERE ticker = 'VWCE.DE' AND horizon_days = 21 ORDER BY date DESC LIMIT 1
        """).fetchone()
        fx_row = db.execute("""
            SELECT rate_point, rate_upper FROM fx_forecasts
            WHERE pair = 'USDPLN' AND horizon_days = 21 ORDER BY date DESC LIMIT 1
        """).fetchone()
        macro_row = db.execute("""
            SELECT usdpln FROM daily_features WHERE usdpln IS NOT NULL ORDER BY date DESC LIMIT 1
        """).fetchone()

        if not regime_row:
            return {"error": "No regime data available"}

        action, confidence, reasons, flags = _make_decision(
            prob_risk_off    = float(regime_row[1] or 0),
            prob_stagflation = float(regime_row[2] or 0),
            vol_21d          = float(vol_row[0]) if vol_row else None,
            usdpln_current   = float(macro_row[0]) if macro_row else None,
            usdpln_upper_21d = float(fx_row[1]) if fx_row else None,
        )
        return {"action": action, "confidence": confidence, "reasons": reasons, "flags": flags}
    except Exception as e:
        return {"error": str(e)}


def _tool_get_portfolio(db, user_id: str) -> dict:
    """Return user's current portfolio positions and IKE status."""
    try:
        positions = db.execute("""
            SELECT p.ticker, p.shares, p.avg_cost_pln, p.account_type,
                   COALESCE(m.currency, 'USD') as currency
            FROM user_positions p
            LEFT JOIN ticker_metadata m ON m.ticker = p.ticker
            WHERE p.user_id = %s AND p.shares > 0
            ORDER BY p.ticker
        """, [user_id]).fetchall()
        ike = db.execute("""
            SELECT year, contributed_pln, limit_pln
            FROM ike_contributions WHERE user_id = %s ORDER BY year DESC LIMIT 3
        """, [user_id]).fetchall()
        return {
            "positions": [
                {"ticker": r[0], "shares": round(r[1], 4),
                 "avg_cost_pln": round(r[2], 2), "account": r[3], "currency": r[4]}
                for r in positions
            ],
            "ike_contributions": [
                {"year": r[0], "contributed_pln": round(r[1], 2),
                 "limit_pln": round(r[2], 2), "remaining_pln": round(r[2] - r[1], 2)}
                for r in ike
            ],
        }
    except Exception as e:
        return {"error": str(e)}


def _tool_get_macro(db) -> dict:
    """Return latest macro snapshot."""
    try:
        row = db.execute("""
            SELECT date, vix_close, cpi_us_yoy, cpi_pl_yoy, fed_funds_rate,
                   ecb_rate, nbp_rate, eurpln, usdpln, spread_10y_2y, hy_spread
            FROM daily_features
            WHERE vix_close IS NOT NULL ORDER BY date DESC LIMIT 1
        """).fetchone()
        if not row:
            return {"error": "No macro data"}
        keys = ["date","vix","cpi_us_yoy","cpi_pl_yoy","fed_rate",
                "ecb_rate","nbp_rate","eurpln","usdpln","spread_10y_2y","hy_spread"]
        return {k: (str(v) if k == "date" else (round(v, 4) if v is not None else None))
                for k, v in zip(keys, row)}
    except Exception as e:
        return {"error": str(e)}


# Tool dispatch map
_TOOL_DISPATCH = {
    "get_signals":  lambda db, uid: _tool_get_signals(db),
    "get_decision": lambda db, uid: _tool_get_decision(db),
    "get_portfolio": _tool_get_portfolio,
    "get_macro":    lambda db, uid: _tool_get_macro(db),
}


@router.post("/chat")
def chat(
    req:     ChatRequest,
    db:      Annotated[object, Depends(get_db_write)],
    user_id: Annotated[str, Depends(get_current_user)],
):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    client = _get_genai_client()
    from google.genai import types
    import json

    # Load last N turns from DB for this user
    history_rows = db.execute("""
        SELECT role, content FROM (
            SELECT role, content, created_at
            FROM chat_history
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        ) sub ORDER BY created_at ASC
    """, [user_id, _CHAT_HISTORY_TURNS * 2]).fetchall()

    # Static briefing context
    pulse_txt, briefing_txt = _get_latest_briefings(db)

    system_parts = [
        "You are a personal investment assistant for a Polish retail investor.",
        "They hold VWCE.DE (UCITS global equity ETF) in an IKE tax-advantaged account.",
        "They invest ~500 PLN/month and make monthly decisions: invest now, DCA, or wait.",
        "Answer concisely and in the same language the user writes in (Polish or English).",
        "Do not give personalised financial advice — explain data and context instead.",
        "Use the available tools to fetch live data when the user asks about signals, portfolio, macro, or the monthly decision.",
    ]
    if briefing_txt:
        system_parts += ["", "=== Latest Weekly Briefing ===", briefing_txt]
    if pulse_txt:
        system_parts += ["", "=== Latest News Pulse ===", pulse_txt]

    system_instruction = "\n".join(system_parts)

    # Define tools for Gemini
    tools = [types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name="get_signals",
            description="Get current ML model signals: market regime (LightGBM), volatility forecast, recession probability, and CAPE 10Y return estimate.",
            parameters=types.Schema(type="OBJECT", properties={}, required=[]),
        ),
        types.FunctionDeclaration(
            name="get_decision",
            description="Get the current monthly investment recommendation: INVEST, DCA, or WAIT, with the reasons.",
            parameters=types.Schema(type="OBJECT", properties={}, required=[]),
        ),
        types.FunctionDeclaration(
            name="get_portfolio",
            description="Get the user's current portfolio: positions, shares, average cost, and IKE contribution status for the current year.",
            parameters=types.Schema(type="OBJECT", properties={}, required=[]),
        ),
        types.FunctionDeclaration(
            name="get_macro",
            description="Get the latest macro snapshot: VIX, CPI, central bank rates, EUR/PLN, USD/PLN, yield curve spread.",
            parameters=types.Schema(type="OBJECT", properties={}, required=[]),
        ),
    ])]

    # Build conversation contents: history + new message
    contents = []
    for role, content in history_rows:
        contents.append(types.Content(
            role="user" if role == "user" else "model",
            parts=[types.Part(text=content)]
        ))
    contents.append(types.Content(
        role="user",
        parts=[types.Part(text=req.message)]
    ))

    # Agentic loop: let Gemini call tools until it produces a final text response
    MAX_TOOL_ROUNDS = 5
    reply = None

    for _ in range(MAX_TOOL_ROUNDS):
        try:
            response = client.models.generate_content(
                model=CHAT_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    tools=tools,
                    temperature=0.7,
                ),
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"AI error: {e}")

        # Check if model wants to call tools
        tool_calls = [p for part in response.candidates[0].content.parts
                      for p in [part] if hasattr(p, 'function_call') and p.function_call]
        if not tool_calls:
            # Final text response
            reply = response.text
            break

        # Append model's tool-call turn to contents
        contents.append(response.candidates[0].content)

        # Execute each requested tool and build function response parts
        tool_response_parts = []
        for part in response.candidates[0].content.parts:
            if not (hasattr(part, 'function_call') and part.function_call):
                continue
            fn_name = part.function_call.name
            fn_result = _TOOL_DISPATCH.get(fn_name, lambda db, uid: {"error": "unknown tool"})(db, user_id)
            tool_response_parts.append(types.Part(
                function_response=types.FunctionResponse(
                    name=fn_name,
                    response={"result": json.dumps(fn_result, default=str)},
                )
            ))

        contents.append(types.Content(role="tool", parts=tool_response_parts))

    if reply is None:
        reply = "Sorry, I couldn't generate a response."

    # Persist this turn to DB
    db.execute(
        "INSERT INTO chat_history (user_id, role, content) VALUES (%s, %s, %s)",
        [user_id, "user", req.message[:4000]]
    )
    db.execute(
        "INSERT INTO chat_history (user_id, role, content) VALUES (%s, %s, %s)",
        [user_id, "assistant", reply[:4000]]
    )
    db.commit()

    return {"reply": reply}
