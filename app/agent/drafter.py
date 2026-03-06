"""
Step 2: Reply Drafter
Generates a professional email reply draft based on ticket content and category.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from openai import AsyncOpenAI

from app.models import DraftOutput, TicketCategory
from app.observability.logger import get_logger

if TYPE_CHECKING:
    from app.models import ClassifyOutput, TicketIn

logger = get_logger(__name__)

CATEGORY_PROMPTS = {
    TicketCategory.BILLING: """You are a billing support specialist. Be professional, empathetic, and solution-focused.
Always:
- Acknowledge the billing concern specifically
- Offer a concrete next step (refund timeline, escalation path, etc.)
- Include a reference to checking the customer portal""",

    TicketCategory.BUG: """You are a technical support engineer. Be precise, empathetic, and action-oriented.
Always:
- Acknowledge the frustration caused by the bug
- Ask for any additional diagnostic info if needed (or assume you have it)
- Provide a workaround if possible and mention it's being escalated to engineering""",

    TicketCategory.FEATURE: """You are a product-focused support specialist. Be enthusiastic and appreciative.
Always:
- Thank the customer for the valuable feedback
- Explain how feature requests are evaluated
- Set realistic expectations about timelines""",

    TicketCategory.URGENT: """You are a senior support manager handling a critical issue. Be decisive, empathetic, and urgent.
Always:
- Start with immediate acknowledgment of severity
- Commit to a specific response SLA (e.g., "within 2 hours")
- Provide an escalation path or emergency contact
- Make the customer feel heard and prioritized""",

    TicketCategory.GENERAL: """You are a friendly and helpful customer support specialist.
Always:
- Be warm and conversational
- Address the question directly and completely
- Offer additional resources (docs, video, etc.) where helpful""",
}

DRAFT_SYSTEM_PROMPT = """You are an expert customer support writer.
Write a professional, empathetic email reply to this support ticket.

Guidelines:
- Length: 100-200 words (concise but complete)
- Tone: professional yet warm
- Do NOT use generic filler phrases like "I hope this email finds you well"
- Personalize by referencing the customer's specific issue
- End with a clear next step or call-to-action
- Use the customer's name if inferable (otherwise use "there")
- Sign off as: "Best regards,\nSupport Team"

Return ONLY the email body text, no subject line, no metadata."""


async def draft_reply(
    ticket: "TicketIn",
    classify: "ClassifyOutput",
    client: AsyncOpenAI,
) -> DraftOutput:
    """Generate a professional reply draft for the ticket."""
    category_guidance = CATEGORY_PROMPTS.get(classify.category, CATEGORY_PROMPTS[TicketCategory.GENERAL])

    system = f"{DRAFT_SYSTEM_PROMPT}\n\nCategory-specific guidance:\n{category_guidance}"

    user_content = f"""Ticket Category: {classify.category.value}
Subject: {ticket.subject}
Customer Email: {ticket.customer_email}

Ticket Body:
{ticket.body}

Write a reply draft:"""

    logger.debug(f"Drafting reply for ticket {ticket.ticket_id} (category: {classify.category.value})")

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        temperature=0.4,
        max_tokens=400,
    )

    reply_text = response.choices[0].message.content.strip()
    word_count = len(reply_text.split())

    result = DraftOutput(
        reply_draft=reply_text,
        tone="professional",
        word_count=word_count,
    )

    logger.info(f"Draft generated for ticket {ticket.ticket_id}", word_count=word_count)
    return result
