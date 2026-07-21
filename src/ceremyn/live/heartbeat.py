"""Heartbeat tracking for the live stream."""

from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ceremyn.domain.market_data import _require_aware


class HeartbeatState(BaseModel):
    model_config = ConfigDict(frozen=True)

    is_healthy: bool = True
    last_seen_at: datetime | None = None
    delay_seconds: float = Field(default=0.0, ge=0)

    @field_validator("last_seen_at")
    @classmethod
    def _validate_last_seen(cls, value: datetime | None) -> datetime | None:
        return _require_aware(value) if value is not None else None


class HeartbeatMonitor:
    def __init__(self, timeout_seconds: float = 5.0) -> None:
        self._timeout = timedelta(seconds=timeout_seconds)
        self._state = HeartbeatState()

    def record(self, at: datetime) -> HeartbeatState:
        previous = self._state
        delay = 0.0
        if previous.last_seen_at is not None:
            delay = max(0.0, (at - previous.last_seen_at).total_seconds())
        self._state = HeartbeatState(is_healthy=True, last_seen_at=at, delay_seconds=delay)
        return self._state

    def check(self, now: datetime) -> HeartbeatState:
        last_seen = self._state.last_seen_at
        if last_seen is None:
            return self._state
        delay = max(0.0, (now - last_seen).total_seconds())
        healthy = now - last_seen <= self._timeout
        self._state = HeartbeatState(
            is_healthy=healthy,
            last_seen_at=last_seen,
            delay_seconds=delay,
        )
        return self._state
