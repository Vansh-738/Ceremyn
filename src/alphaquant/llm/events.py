"""Events the assistant publishes onto the shared core EventBus.

Read-only observability only — nothing here is ever subscribed to by the assistant itself
to trigger a trade; it's one-way, `llm -> EventBus`, for anything else (e.g. a future
dashboard panel) to observe.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from alphaquant.domain.market_data import _require_aware


class AssistantReportGenerated(BaseModel):
    model_config = ConfigDict(frozen=True)

    occurred_at: datetime
    session_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)  # "daily_recap" | "session_recap" | "report" | "comparison"
    citations: tuple[str, ...] = ()

    _aware = field_validator("occurred_at")(_require_aware)
