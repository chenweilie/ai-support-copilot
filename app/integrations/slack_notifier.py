"""
Integration: Slack notifications.
- Sends urgent ticket alerts immediately
- Sends human-review requests with Block Kit ✅/❌ interactive buttons
- Handles approval/rejection callbacks
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.errors import SlackApiError

from app.observability.logger import get_logger
from app.observability.metrics import SLACK_NOTIFY_TOTAL, ACTIVE_TICKETS

if TYPE_CHECKING:
    from app.models import TicketResult

logger = get_logger(__name__)

CATEGORY_EMOJI = {
    "billing": "💳",
    "bug": "🐛",
    "feature": "✨",
    "urgent": "🚨",
    "general": "💬",
}

PRIORITY_COLOR = {
    "critical": "#FF0000",
    "high": "#FF7A00",
    "medium": "#FFD700",
    "low": "#36A64F",
}


def _get_client() -> AsyncWebClient:
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not token:
        raise ValueError("SLACK_BOT_TOKEN not set")
    return AsyncWebClient(token=token)


def _build_urgent_blocks(result: "TicketResult") -> list[dict]:
    emoji = CATEGORY_EMOJI.get(result.category.value, "📋")
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🚨 URGENT TICKET — Immediate Action Required"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Ticket ID:*\n`{result.ticket_id}`"},
                {"type": "mrkdwn", "text": f"*Category:*\n{emoji} {result.category.value.title()}"},
                {"type": "mrkdwn", "text": f"*Priority:*\n{result.extract.priority.value.upper()}"},
                {"type": "mrkdwn", "text": f"*Sentiment:*\n{result.extract.sentiment.value}"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Summary:*\n{result.extract.summary}"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Reply Draft Preview:*\n```{result.draft.reply_draft[:300]}...```",
            },
        },
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✅ Approve & Send"},
                    "style": "primary",
                    "action_id": "approve_ticket",
                    "value": result.ticket_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "❌ Reject"},
                    "style": "danger",
                    "action_id": "reject_ticket",
                    "value": result.ticket_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✏️ Edit Draft"},
                    "action_id": "edit_draft",
                    "value": result.ticket_id,
                },
            ],
        },
    ]


def _build_review_blocks(result: "TicketResult") -> list[dict]:
    emoji = CATEGORY_EMOJI.get(result.category.value, "📋")
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "👀 Human Review Required"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Low confidence ({result.confidence:.0%})* — manual review needed before sending.\n"
                    f"*Ticket:* `{result.ticket_id}` | *Category:* {emoji} {result.category.value.title()}"
                ),
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Priority:*\n{result.extract.priority.value.upper()}"},
                {"type": "mrkdwn", "text": f"*Sentiment:*\n{result.extract.sentiment.value}"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Summary:*\n{result.extract.summary}"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Draft Reply:*\n```{result.draft.reply_draft[:400]}```",
            },
        },
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "⏰ SLA: Please review within 30 minutes"},
            ],
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✅ Approve & Send"},
                    "style": "primary",
                    "action_id": "approve_ticket",
                    "value": result.ticket_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "❌ Reject"},
                    "style": "danger",
                    "action_id": "reject_ticket",
                    "value": result.ticket_id,
                },
            ],
        },
    ]


async def notify_slack(result: "TicketResult") -> bool:
    """Send appropriate Slack notification based on ticket type."""
    channel = os.environ.get("SLACK_CHANNEL", "#support-copilot")

    if not os.environ.get("SLACK_BOT_TOKEN"):
        logger.warning("SLACK_BOT_TOKEN not set — skipping Slack notification")
        return False

    try:
        client = _get_client()

        if result.category.value == "urgent":
            blocks = _build_urgent_blocks(result)
            notify_type = "urgent"
        elif result.needs_review:
            blocks = _build_review_blocks(result)
            notify_type = "review_request"
            ACTIVE_TICKETS.inc()
        else:
            # Only notify for urgent/review — auto-approve low-confidence
            logger.debug(f"Ticket {result.ticket_id} auto-approved, no Slack needed")
            return True

        await client.chat_postMessage(
            channel=channel,
            blocks=blocks,
            text=f"Support ticket {result.ticket_id} requires attention",
        )

        SLACK_NOTIFY_TOTAL.labels(type=notify_type).inc()
        logger.info(f"Slack notification sent for ticket {result.ticket_id}", type=notify_type)
        return True

    except SlackApiError as e:
        logger.error(f"Slack API error for ticket {result.ticket_id}: {e.response['error']}")
        return False
    except Exception as e:
        logger.error(f"Unexpected Slack error for ticket {result.ticket_id}: {e}")
        return False


async def handle_approval(ticket_id: str, approved: bool, approver: str) -> None:
    """Handle Slack interactive button callback (approve/reject)."""
    from app.observability.metrics import SLACK_NOTIFY_TOTAL
    action = "approved" if approved else "rejected"
    SLACK_NOTIFY_TOTAL.labels(type=action).inc()
    ACTIVE_TICKETS.dec()
    logger.info(f"Ticket {ticket_id} {action} by {approver} via Slack")
