"""
FastAPI main application entry point.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from app.agent.pipeline import run_pipeline
from app.config import get_settings
from app.integrations.sheets import write_ticket_to_sheet
from app.integrations.slack_notifier import notify_slack, handle_approval
from app.models import (
    BatchRequest,
    BatchResponse,
    HealthResponse,
    TicketIn,
    TicketResponse,
)
from app.observability.logger import get_logger, setup_logging

settings = get_settings()
setup_logging(settings.log_level)
logger = get_logger(__name__)

# In-memory store for demo (replace with Redis/DB in production)
_ticket_store: dict[str, Any] = {}
_stats: dict[str, Any] = {
    "total": 0,
    "needs_review": 0,
    "approved": 0,
    "rejected": 0,
    "categories": {},
    "latencies": [],
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"🚀 {settings.app_name} v{settings.version} starting up")
    os.makedirs("logs", exist_ok=True)
    yield
    logger.info("Shutting down gracefully")


app = FastAPI(
    title="AI Support Copilot",
    description="Intelligent customer support ticket classification, drafting and CRM write-back",
    version=settings.version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static dashboard
static_path = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_path):
    app.mount("/static", StaticFiles(directory=static_path), name="static")


def _get_openai() -> AsyncOpenAI:
    api_key = settings.openai_api_key or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured")
    return AsyncOpenAI(api_key=api_key)


def _to_response(result) -> TicketResponse:
    return TicketResponse(
        success=True,
        ticket_id=result.ticket_id,
        category=result.category.value,
        confidence=result.confidence,
        needs_review=result.needs_review,
        status=result.status.value,
        reply_draft=result.draft.reply_draft,
        priority=result.extract.priority.value,
        sentiment=result.extract.sentiment.value,
        action_items=result.extract.action_items,
        latency_ms=result.latency_ms,
        message="Routed to human review queue" if result.needs_review else "Auto-processed successfully",
    )


async def _background_integrations(result):
    """Run Sheets + Slack in background after response is returned."""
    await asyncio.gather(
        write_ticket_to_sheet(result),
        notify_slack(result),
        return_exceptions=True,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the web dashboard."""
    dashboard_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(dashboard_path):
        with open(dashboard_path) as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>AI Support Copilot API</h1><p>Dashboard not found. See <a href='/docs'>/docs</a>.</p>")


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse()


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return HTMLResponse(
        content=generate_latest().decode("utf-8"),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.get("/stats")
async def stats():
    """Current processing statistics."""
    latencies = _stats["latencies"]
    return {
        **_stats,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0,
        "p95_latency_ms": round(sorted(latencies)[int(len(latencies) * 0.95)], 1) if len(latencies) >= 20 else None,
        "recent_tickets": list(_ticket_store.values())[-10:],
    }


@app.post("/tickets", response_model=TicketResponse)
async def process_ticket(ticket: TicketIn, background_tasks: BackgroundTasks):
    """
    Process a single support ticket through the full AI pipeline.
    Returns classification, reply draft, and extracted fields.
    Integration with Sheets + Slack runs in the background.
    """
    client = _get_openai()
    result = await run_pipeline(ticket, client)

    # Update in-memory stats
    _stats["total"] += 1
    if result.needs_review:
        _stats["needs_review"] += 1
    cat = result.category.value
    _stats["categories"][cat] = _stats["categories"].get(cat, 0) + 1
    _stats["latencies"].append(result.latency_ms)

    # Store for dashboard
    _ticket_store[result.ticket_id] = {
        "ticket_id": result.ticket_id,
        "category": cat,
        "confidence": round(result.confidence, 3),
        "needs_review": result.needs_review,
        "status": result.status.value,
        "priority": result.extract.priority.value,
        "sentiment": result.extract.sentiment.value,
        "latency_ms": result.latency_ms,
        "processed_at": result.processed_at.isoformat(),
        "summary": result.extract.summary,
    }

    background_tasks.add_task(_background_integrations, result)
    return _to_response(result)


@app.post("/tickets/batch", response_model=BatchResponse)
async def process_batch(batch: BatchRequest, background_tasks: BackgroundTasks):
    """Process multiple tickets concurrently (max 20 at a time)."""
    tickets = batch.tickets[:20]
    client = _get_openai()

    start = time.monotonic()
    results = await asyncio.gather(
        *[run_pipeline(t, client) for t in tickets],
        return_exceptions=True,
    )

    processed, needs_review, errors = 0, 0, 0
    responses = []

    for r in results:
        if isinstance(r, Exception):
            errors += 1
            responses.append(TicketResponse(
                success=False,
                ticket_id="unknown",
                category="error",
                confidence=0,
                needs_review=True,
                status="error",
                reply_draft="",
                priority="medium",
                sentiment="neutral",
                action_items=[],
                latency_ms=0,
                message=str(r),
            ))
        else:
            processed += 1
            if r.needs_review:
                needs_review += 1
            responses.append(_to_response(r))
            background_tasks.add_task(_background_integrations, r)

    total_latency = (time.monotonic() - start) * 1000

    return BatchResponse(
        total=len(tickets),
        processed=processed,
        needs_review=needs_review,
        errors=errors,
        results=responses,
        total_latency_ms=round(total_latency, 1),
    )


@app.post("/webhook/slack")
async def slack_webhook(request: Request):
    """Handle Slack interactive button callbacks (approve/reject)."""
    body = await request.body()
    payload_str = body.decode("utf-8")

    # Slack sends payload as form-encoded
    if payload_str.startswith("payload="):
        import urllib.parse
        payload_str = urllib.parse.unquote_plus(payload_str[8:])

    try:
        payload = json.loads(payload_str)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid payload")

    actions = payload.get("actions", [])
    user = payload.get("user", {}).get("name", "unknown")

    for action in actions:
        action_id = action.get("action_id", "")
        ticket_id = action.get("value", "")

        if action_id == "approve_ticket":
            await handle_approval(ticket_id, approved=True, approver=user)
            if ticket_id in _ticket_store:
                _ticket_store[ticket_id]["status"] = "approved"
            _stats["approved"] += 1
            return {"text": f"✅ Ticket {ticket_id} approved by {user}"}

        elif action_id == "reject_ticket":
            await handle_approval(ticket_id, approved=False, approver=user)
            if ticket_id in _ticket_store:
                _ticket_store[ticket_id]["status"] = "rejected"
            _stats["rejected"] += 1
            return {"text": f"❌ Ticket {ticket_id} rejected by {user}"}

    return {"text": "Action received"}
