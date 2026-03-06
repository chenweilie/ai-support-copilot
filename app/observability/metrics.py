"""
Observability: Prometheus metrics.
"""
from prometheus_client import Counter, Histogram, Gauge

TICKETS_PROCESSED = Counter(
    "tickets_processed_total",
    "Total tickets processed",
    ["category"],
)

PIPELINE_LATENCY = Histogram(
    "pipeline_latency_seconds",
    "End-to-end pipeline latency",
    buckets=[0.5, 1, 2, 3, 5, 8, 12, 20, 30],
)

LLM_CONFIDENCE = Histogram(
    "llm_confidence",
    "LLM classification confidence scores",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.75, 0.8, 0.9, 0.95, 1.0],
)

HUMAN_REVIEW_TOTAL = Counter(
    "human_review_total",
    "Tickets routed to human review queue",
)

SHEETS_WRITE_TOTAL = Counter(
    "sheets_write_total",
    "Google Sheets write operations",
    ["status"],
)

SLACK_NOTIFY_TOTAL = Counter(
    "slack_notify_total",
    "Slack notifications sent",
    ["type"],  # urgent | review_request | approved | rejected
)

ACTIVE_TICKETS = Gauge(
    "active_tickets_pending_review",
    "Tickets currently awaiting human approval",
)
