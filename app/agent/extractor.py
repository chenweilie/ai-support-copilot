"""
Step 3: Field Extractor
Extracts structured fields from the ticket: priority, sentiment, action items, entities.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from openai import AsyncOpenAI

from app.models import ExtractOutput, Priority, Sentiment
from app.observability.logger import get_logger

if TYPE_CHECKING:
    from app.models import ClassifyOutput, TicketIn

logger = get_logger(__name__)

EXTRACT_SYSTEM_PROMPT = """You are a customer support data analyst. Extract structured fields from the support ticket.

Priority rules:
- critical: service down, data loss, security breach, legal threat
- high: major feature broken, billing error > $100, deadline tomorrow
- medium: important issue but workaround exists, billing discrepancy < $100
- low: minor UX issues, informational questions, feature requests

Sentiment rules:
- frustrated: ALL CAPS, exclamation marks!!!, words like "unacceptable", "terrible", "immediately"
- negative: unhappy tone, complaints, disappointment
- neutral: matter-of-fact, technical description
- positive: polite, appreciative, excited about a feature

Return ONLY valid JSON:
{
  "priority": "low|medium|high|critical",
  "sentiment": "positive|neutral|negative|frustrated",
  "action_items": ["list of concrete actions the support team should take"],
  "key_entities": {
    "product_area": "e.g. billing portal, API, mobile app",
    "account_id": "if mentioned",
    "amount": "if money discussed",
    "error_code": "if mentioned"
  },
  "summary": "1-2 sentence plain English summary of the issue"
}"""


async def extract_fields(
    ticket: "TicketIn",
    classify: "ClassifyOutput",
    client: AsyncOpenAI,
) -> ExtractOutput:
    """Extract structured fields from a ticket."""
    user_content = f"""Category: {classify.category.value}
Subject: {ticket.subject}

Body:
{ticket.body}"""

    logger.debug(f"Extracting fields for ticket {ticket.ticket_id}")

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
        max_tokens=400,
    )

    raw = response.choices[0].message.content
    data = json.loads(raw)

    result = ExtractOutput(
        priority=Priority(data.get("priority", "medium")),
        sentiment=Sentiment(data.get("sentiment", "neutral")),
        action_items=data.get("action_items", []),
        key_entities=data.get("key_entities", {}),
        summary=data.get("summary", ""),
    )

    logger.info(
        f"Fields extracted for ticket {ticket.ticket_id}",
        priority=result.priority.value,
        sentiment=result.sentiment.value,
        action_count=len(result.action_items),
    )
    return result
