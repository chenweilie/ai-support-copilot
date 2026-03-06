"""
Pydantic models for AI Support Copilot.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TicketCategory(str, Enum):
    BILLING = "billing"
    BUG = "bug"
    FEATURE = "feature"
    GENERAL = "general"
    URGENT = "urgent"


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Sentiment(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    FRUSTRATED = "frustrated"


class TicketStatus(str, Enum):
    PENDING = "pending"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    PROCESSED = "processed"


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

class TicketIn(BaseModel):
    ticket_id: str = Field(..., description="Unique ticket identifier")
    subject: str = Field(..., description="Email/form subject line")
    body: str = Field(..., description="Full ticket body text")
    customer_email: str = Field(..., description="Customer's email address")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Agent step outputs
# ---------------------------------------------------------------------------

class ClassifyOutput(BaseModel):
    category: TicketCategory
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str


class DraftOutput(BaseModel):
    reply_draft: str
    tone: str = "professional"
    word_count: int


class ExtractOutput(BaseModel):
    priority: Priority
    sentiment: Sentiment
    action_items: list[str] = Field(default_factory=list)
    key_entities: dict[str, str] = Field(default_factory=dict)
    summary: str


# ---------------------------------------------------------------------------
# Full pipeline result
# ---------------------------------------------------------------------------

class TicketResult(BaseModel):
    ticket_id: str
    category: TicketCategory
    confidence: float
    needs_review: bool
    status: TicketStatus = TicketStatus.PENDING

    # Step outputs
    classify: ClassifyOutput
    draft: DraftOutput
    extract: ExtractOutput

    # Timing
    processed_at: datetime = Field(default_factory=datetime.utcnow)
    latency_ms: float = 0.0

    # Errors
    errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# API response
# ---------------------------------------------------------------------------

class TicketResponse(BaseModel):
    success: bool
    ticket_id: str
    category: str
    confidence: float
    needs_review: bool
    status: str
    reply_draft: str
    priority: str
    sentiment: str
    action_items: list[str]
    latency_ms: float
    message: str = ""


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class BatchRequest(BaseModel):
    tickets: list[TicketIn]


class BatchResponse(BaseModel):
    total: int
    processed: int
    needs_review: int
    errors: int
    results: list[TicketResponse]
    total_latency_ms: float
