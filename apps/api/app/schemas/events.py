from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

EVENT_TYPES = (
    "payment.failed",
    "payment.captured",
    "payment.authorized",
    "payment.refunded",
    "order.created",
    "order.paid",
    "order.cancelled",
    "subscription.payment_failed",
    "subscription.recovered",
    "dispute.created",
    "dispute.resolved",
    "settlement.created",
    "settlement.delayed",
    "settlement.processed",
    "payout.created",
    "payout.completed",
    "payout.delayed",
    "invoice.created",
    "invoice.paid",
    "invoice.overdue",
    "payroll.scheduled",
    "customer.created",
    "customer.returned",
    "refund.created",
    "refund.processed",
    "cash.adjusted",
    "action.executed",
    "action.verified",
)


class EventEnvelope(BaseModel):
    event_id: str
    event_type: str
    event_version: str = "1.0"
    merchant_id: str
    entity_id: str
    timestamp: datetime
    source: str
    trace_id: str
    payload: dict[str, Any] = Field(default_factory=dict)


class IngestEventRequest(BaseModel):
    event_type: str
    entity_id: str
    source: str = "api"
    timestamp: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    event_id: str | None = None
    trace_id: str | None = None


ActionType = Literal[
    "payout.delay",
    "payout.create",
    "receivable.recover",
    "payment.retry",
    "refund.create",
    "retry.config.update",
    "invoice.dunning.draft",
    "observe",
]

RecommendationStatus = Literal[
    "GENERATED",
    "VIEWED",
    "APPROVED",
    "REJECTED",
    "EXECUTED",
    "FAILED",
    "VERIFIED",
    "EXPIRED",
]

Reversibility = Literal["read", "draft", "reversible", "financial", "high_impact"]
