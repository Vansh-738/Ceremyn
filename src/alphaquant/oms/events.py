"""Internal OMS domain events."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from alphaquant.domain.market_data import _require_aware


class OMSEventType(StrEnum):
    INTENT_CREATED = "intent_created"
    PLAN_CREATED = "plan_created"
    ORDER_CREATED = "order_created"
    ORDER_VALIDATED = "order_validated"
    ORDER_ROUTED = "order_routed"
    SUBMIT_REQUESTED = "submit_requested"
    ACKNOWLEDGED = "acknowledged"
    PARTIAL_FILL_RECORDED = "partial_fill_recorded"
    FILL_RECORDED = "fill_recorded"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    REPLACED = "replaced"
    REJECTED = "rejected"
    FAILED = "failed"
    EXPIRED = "expired"
    DUPLICATE_SUPPRESSED = "duplicate_suppressed"
    RETRY_SCHEDULED = "retry_scheduled"
    RETRY_SUCCEEDED = "retry_succeeded"
    RETRY_EXHAUSTED = "retry_exhausted"
    RECONCILIATION_COMPLETED = "reconciliation_completed"
    KILL_SWITCH_ARMED = "kill_switch_armed"
    KILL_SWITCH_DISARMED = "kill_switch_disarmed"
    COMPENSATION_SUBMITTED = "compensation_submitted"


class OMSEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: UUID = Field(default_factory=uuid4)
    event_type: OMSEventType
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    oms_order_id: UUID | None = None
    correlation_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    _aware = field_validator("occurred_at")(_require_aware)
