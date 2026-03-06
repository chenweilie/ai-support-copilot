"""
Main Pipeline Orchestrator
Runs classify → draft → extract with error handling,
retry logic, and confidence-based human-review routing.
"""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from openai import AsyncOpenAI, APIError, RateLimitError

from app.agent.classifier import classify_ticket
from app.agent.drafter import draft_reply
from app.agent.extractor import extract_fields
from app.models import (
    ClassifyOutput,
    DraftOutput,
    ExtractOutput,
    Priority,
    Sentiment,
    TicketCategory,
    TicketResult,
    TicketStatus,
)
from app.observability.logger import get_logger
from app.observability.metrics import (
    PIPELINE_LATENCY,
    TICKETS_PROCESSED,
    LLM_CONFIDENCE,
    HUMAN_REVIEW_TOTAL,
)

if TYPE_CHECKING:
    from app.models import TicketIn

logger = get_logger(__name__)

CONFIDENCE_THRESHOLD = 0.75
MAX_RETRIES = 3


def _fallback_classify() -> ClassifyOutput:
    return ClassifyOutput(
        category=TicketCategory.GENERAL,
        confidence=0.0,
        reasoning="Fallback: LLM call failed after retries",
    )


def _fallback_draft() -> DraftOutput:
    return DraftOutput(
        reply_draft=(
            "Thank you for reaching out to our support team. "
            "We have received your message and a specialist will review it shortly. "
            "We apologize for any inconvenience and will get back to you as soon as possible.\n\n"
            "Best regards,\nSupport Team"
        ),
        tone="professional",
        word_count=45,
    )


def _fallback_extract() -> ExtractOutput:
    return ExtractOutput(
        priority=Priority.MEDIUM,
        sentiment=Sentiment.NEUTRAL,
        action_items=["Manual review required — automated extraction failed"],
        key_entities={},
        summary="Extraction failed. Manual review needed.",
    )


async def _with_retry(coro_fn, ticket_id: str, step_name: str, max_retries: int = MAX_RETRIES):
    """Run an async coroutine with exponential backoff retry."""
    for attempt in range(1, max_retries + 1):
        try:
            return await coro_fn()
        except RateLimitError:
            if attempt < max_retries:
                wait = 2 ** attempt
                logger.warning(f"Rate limit hit for {step_name} on ticket {ticket_id}, retrying in {wait}s")
                await asyncio.sleep(wait)
            else:
                raise
        except APIError as e:
            if attempt < max_retries:
                wait = 2 ** attempt
                logger.warning(f"API error in {step_name} for {ticket_id} (attempt {attempt}): {e}, retrying in {wait}s")
                await asyncio.sleep(wait)
            else:
                raise


async def run_pipeline(ticket: "TicketIn", client: AsyncOpenAI) -> TicketResult:
    """
    Full 3-step pipeline:
    1. Classify  → category + confidence
    2. Draft     → reply text
    3. Extract   → structured fields

    Low confidence (< 0.75) → needs_review = True, routed to human queue.
    Any step failure → fallback values + errors list populated.
    """
    start = time.monotonic()
    errors: list[str] = []

    logger.info(f"Pipeline start: ticket {ticket.ticket_id}")

    # ── Step 1: Classify ──────────────────────────────────────────────────
    classify: ClassifyOutput
    try:
        classify = await _with_retry(
            lambda: classify_ticket(ticket, client),
            ticket.ticket_id,
            "classify",
        )
    except Exception as e:
        logger.error(f"Classify failed for {ticket.ticket_id}: {e}")
        errors.append(f"classify: {str(e)}")
        classify = _fallback_classify()

    # ── Step 2 & 3: Draft + Extract in parallel ──────────────────────────
    draft: DraftOutput
    extract: ExtractOutput

    async def _draft():
        return await _with_retry(
            lambda: draft_reply(ticket, classify, client),
            ticket.ticket_id,
            "draft",
        )

    async def _extract():
        return await _with_retry(
            lambda: extract_fields(ticket, classify, client),
            ticket.ticket_id,
            "extract",
        )

    results = await asyncio.gather(_draft(), _extract(), return_exceptions=True)

    if isinstance(results[0], Exception):
        logger.error(f"Draft failed for {ticket.ticket_id}: {results[0]}")
        errors.append(f"draft: {str(results[0])}")
        draft = _fallback_draft()
    else:
        draft = results[0]

    if isinstance(results[1], Exception):
        logger.error(f"Extract failed for {ticket.ticket_id}: {results[1]}")
        errors.append(f"extract: {str(results[1])}")
        extract = _fallback_extract()
    else:
        extract = results[1]

    # ── Scoring ───────────────────────────────────────────────────────────
    latency_ms = (time.monotonic() - start) * 1000
    needs_review = classify.confidence < CONFIDENCE_THRESHOLD or bool(errors)
    status = TicketStatus.NEEDS_REVIEW if needs_review else TicketStatus.PENDING

    # ── Metrics ───────────────────────────────────────────────────────────
    PIPELINE_LATENCY.observe(latency_ms / 1000)
    TICKETS_PROCESSED.labels(category=classify.category.value).inc()
    LLM_CONFIDENCE.observe(classify.confidence)
    if needs_review:
        HUMAN_REVIEW_TOTAL.inc()

    logger.info(
        f"Pipeline complete: ticket {ticket.ticket_id}",
        category=classify.category.value,
        confidence=classify.confidence,
        needs_review=needs_review,
        latency_ms=round(latency_ms, 1),
        errors=len(errors),
    )

    return TicketResult(
        ticket_id=ticket.ticket_id,
        category=classify.category,
        confidence=classify.confidence,
        needs_review=needs_review,
        status=status,
        classify=classify,
        draft=draft,
        extract=extract,
        latency_ms=round(latency_ms, 1),
        errors=errors,
    )
