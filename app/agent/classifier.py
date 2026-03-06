"""
Step 1: Ticket Classifier
Classifies a support ticket into a category with confidence score.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from openai import AsyncOpenAI

from app.models import ClassifyOutput, TicketCategory
from app.observability.logger import get_logger

if TYPE_CHECKING:
    from app.models import TicketIn

logger = get_logger(__name__)

CLASSIFY_SYSTEM_PROMPT = """You are an expert customer support ticket classifier for a SaaS company.

Classify the ticket into EXACTLY ONE of these categories:
- billing: payment issues, invoices, refunds, subscription changes, pricing questions
- bug: software errors, crashes, unexpected behavior, broken features
- feature: feature requests, suggestions, enhancement ideas
- urgent: data loss, security breaches, complete service outage, legal threats, critical business impact
- general: account questions, how-to questions, onboarding, documentation requests, other

Rules:
1. If ANY urgent signals exist (data loss, legal, outage), classify as "urgent" regardless of other content
2. Billing + bug together → pick whichever is more central to the ticket
3. Be conservative: confidence < 0.75 means you are genuinely unsure

Return ONLY valid JSON in this exact format:
{
  "category": "billing|bug|feature|urgent|general",
  "confidence": 0.0-1.0,
  "reasoning": "one sentence explanation"
}"""


async def classify_ticket(ticket: "TicketIn", client: AsyncOpenAI) -> ClassifyOutput:
    """Classify a ticket into a category with confidence score."""
    user_content = f"""Subject: {ticket.subject}

Body:
{ticket.body}

Customer: {ticket.customer_email}"""

    logger.debug(f"Classifying ticket {ticket.ticket_id}")

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
        max_tokens=200,
    )

    raw = response.choices[0].message.content
    data = json.loads(raw)

    result = ClassifyOutput(
        category=TicketCategory(data["category"]),
        confidence=float(data["confidence"]),
        reasoning=data.get("reasoning", ""),
    )

    logger.info(
        f"Ticket {ticket.ticket_id} classified",
        category=result.category.value,
        confidence=result.confidence,
    )
    return result
