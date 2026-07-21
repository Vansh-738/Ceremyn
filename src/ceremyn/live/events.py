"""Live engine lifecycle events."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ceremyn.domain.market_data import _require_aware
from ceremyn.live.market_hours import MarketStatus
from ceremyn.live.snapshot import LiveTick, MarketSnapshot


class _AwareEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    occurred_at: datetime

    _aware = field_validator("occurred_at")(_require_aware)


class MarketOpen(_AwareEvent):
    underlying: str = Field(min_length=1)


class MarketClose(_AwareEvent):
    underlying: str = Field(min_length=1)


class TickReceived(_AwareEvent):
    tick: LiveTick


class SnapshotBuilt(_AwareEvent):
    snapshot: MarketSnapshot


class ReconnectStarted(_AwareEvent):
    reason: str = Field(min_length=1)
    attempt: int = Field(ge=1)


class ReconnectSucceeded(_AwareEvent):
    attempt: int = Field(ge=1)


class ReconnectFailed(_AwareEvent):
    attempt: int = Field(ge=1)
    reason: str = Field(min_length=1)


class HeartbeatLost(_AwareEvent):
    last_seen_at: datetime

    _last_seen = field_validator("last_seen_at")(_require_aware)


class HeartbeatRecovered(_AwareEvent):
    delay_seconds: float = Field(ge=0)


class MarketStatusChanged(_AwareEvent):
    underlying: str = Field(min_length=1)
    status: MarketStatus
