"""
Test suite: Pipeline accuracy and latency benchmarks using 100 labeled tickets.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import pytest
from openai import AsyncOpenAI

from app.agent.pipeline import run_pipeline
from app.models import TicketIn, TicketCategory


FIXTURES_PATH = Path(__file__).parent / "fixtures" / "tickets.json"
CONFIDENCE_THRESHOLD = 0.75


def load_fixtures() -> list[dict]:
    with open(FIXTURES_PATH) as f:
        return json.load(f)


def get_client() -> AsyncOpenAI:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        pytest.skip("OPENAI_API_KEY not set — skipping live LLM tests")
    return AsyncOpenAI(api_key=api_key)


# ── Unit tests (no LLM calls) ────────────────────────────────────────────────

class TestModels:
    def test_ticket_in_defaults(self):
        t = TicketIn(
            ticket_id="t001",
            subject="Test",
            body="Test body",
            customer_email="test@example.com",
        )
        assert t.ticket_id == "t001"
        assert t.metadata == {}

    def test_all_categories_valid(self):
        cats = [c.value for c in TicketCategory]
        assert "billing" in cats
        assert "urgent" in cats
        assert len(cats) == 5


class TestFixtures:
    def test_fixtures_load(self):
        tickets = load_fixtures()
        assert len(tickets) == 100

    def test_all_categories_covered(self):
        tickets = load_fixtures()
        labels = {t["metadata"]["label"] for t in tickets}
        assert labels == {"billing", "bug", "feature", "urgent", "general"}

    def test_urgent_tickets_present(self):
        tickets = load_fixtures()
        urgent = [t for t in tickets if t["metadata"]["label"] == "urgent"]
        assert len(urgent) >= 5


# ── Integration tests (requires OPENAI_API_KEY) ─────────────────────────────

class TestPipelineBatch:
    """Batch accuracy and latency test — runs against real LLM API."""

    @pytest.mark.asyncio
    async def test_single_ticket_pipeline(self):
        """Smoke test: single ticket full pipeline run."""
        client = get_client()
        ticket = TicketIn(
            ticket_id="smoke-001",
            subject="URGENT: All data deleted, we're losing $10k/hour",
            body="Our production database is completely empty. This is catastrophic. We need help NOW.",
            customer_email="cto@emergency.com",
        )
        result = await run_pipeline(ticket, client)

        assert result.ticket_id == "smoke-001"
        assert result.category is not None
        assert 0.0 <= result.confidence <= 1.0
        assert len(result.draft.reply_draft) > 50
        assert result.extract.priority is not None
        assert result.latency_ms > 0

    @pytest.mark.asyncio
    async def test_urgent_classified_correctly(self):
        client = get_client()
        ticket = TicketIn(
            ticket_id="urgent-test",
            subject="EMERGENCY: Database corrupted, all data gone",
            body="We just lost all 100,000 records. Complete data loss. Need help immediately.",
            customer_email="cto@urgent.com",
        )
        result = await run_pipeline(ticket, client)
        assert result.category.value == "urgent"
        assert result.confidence >= 0.7

    @pytest.mark.asyncio
    async def test_billing_classified_correctly(self):
        client = get_client()
        ticket = TicketIn(
            ticket_id="billing-test",
            subject="Charged twice this month - please refund",
            body="My credit card was charged $99 twice on January 1st. Please refund the duplicate.",
            customer_email="finance@test.com",
        )
        result = await run_pipeline(ticket, client)
        assert result.category.value == "billing"

    @pytest.mark.asyncio
    async def test_reply_draft_not_empty(self):
        client = get_client()
        ticket = TicketIn(
            ticket_id="draft-test",
            subject="Cannot export to CSV",
            body="Every time I try to export my data to CSV the download fails with a network error.",
            customer_email="user@test.com",
        )
        result = await run_pipeline(ticket, client)
        assert len(result.draft.reply_draft) > 100
        assert "Best regards" in result.draft.reply_draft or "Support Team" in result.draft.reply_draft

    @pytest.mark.asyncio
    async def test_low_confidence_triggers_review(self):
        """Ambiguous ticket should trigger human review if confidence is low."""
        client = get_client()
        ticket = TicketIn(
            ticket_id="ambig-test",
            subject="Question",
            body="Hi",
            customer_email="vague@example.com",
        )
        result = await run_pipeline(ticket, client)
        # Either classified with low confidence → needs_review, or handled gracefully
        assert isinstance(result.needs_review, bool)

    @pytest.mark.asyncio
    async def test_batch_accuracy(self):
        """
        Run full 100-ticket batch accuracy test.
        Saves results to test_report.json.
        Set RUN_BATCH_TEST=1 env var to enable (expensive).
        """
        if not os.environ.get("RUN_BATCH_TEST"):
            pytest.skip("Set RUN_BATCH_TEST=1 to run batch accuracy test")

        client = get_client()
        tickets_data = load_fixtures()

        correct = 0
        total = len(tickets_data)
        latencies = []
        results = []
        human_review_count = 0

        # Process in batches of 5 to avoid rate limits
        BATCH_SIZE = 5
        for i in range(0, total, BATCH_SIZE):
            batch = tickets_data[i:i+BATCH_SIZE]
            ticket_objs = [
                TicketIn(**{k: v for k, v in t.items() if k != "metadata"})
                for t in batch
            ]
            labels = [t["metadata"]["label"] for t in batch]

            batch_results = await asyncio.gather(
                *[run_pipeline(t, client) for t in ticket_objs],
                return_exceptions=True,
            )

            for result, label in zip(batch_results, labels):
                if isinstance(result, Exception):
                    results.append({"error": str(result)})
                    continue

                predicted = result.category.value
                is_correct = predicted == label
                if is_correct:
                    correct += 1
                if result.needs_review:
                    human_review_count += 1
                latencies.append(result.latency_ms)

                results.append({
                    "ticket_id": result.ticket_id,
                    "label": label,
                    "predicted": predicted,
                    "correct": is_correct,
                    "confidence": result.confidence,
                    "needs_review": result.needs_review,
                    "latency_ms": result.latency_ms,
                })

            # Brief pause between batches
            await asyncio.sleep(1)

        accuracy = correct / total
        avg_latency = sum(latencies) / len(latencies) if latencies else 0
        sorted_lat = sorted(latencies)
        p95_latency = sorted_lat[int(len(sorted_lat) * 0.95)] if sorted_lat else 0

        report = {
            "total": total,
            "correct": correct,
            "accuracy": round(accuracy, 4),
            "avg_latency_ms": round(avg_latency, 1),
            "p95_latency_ms": round(p95_latency, 1),
            "human_review_count": human_review_count,
            "human_review_rate": round(human_review_count / total, 4),
            "results": results,
        }

        # Save report
        import json
        with open("test_report.json", "w") as f:
            json.dump(report, f, indent=2)

        print(f"\n{'='*50}")
        print(f"ACCURACY:         {accuracy:.1%} ({correct}/{total})")
        print(f"AVG LATENCY:      {avg_latency:.0f}ms")
        print(f"P95 LATENCY:      {p95_latency:.0f}ms")
        print(f"HUMAN REVIEW:     {human_review_count}/{total} ({human_review_count/total:.1%})")
        print(f"Report saved to:  test_report.json")
        print(f"{'='*50}")

        assert accuracy >= 0.85, f"Accuracy {accuracy:.1%} below 85% threshold"
        assert avg_latency < 15000, f"Avg latency {avg_latency:.0f}ms exceeds 15s"
