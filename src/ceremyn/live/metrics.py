"""Operational metrics for the live market-data engine."""

from collections import deque
from datetime import datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ceremyn.domain.market_data import _require_aware


class LiveMetricsSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    as_of: datetime
    messages_per_second: float = Field(ge=0)
    ticks_processed: int = Field(ge=0)
    dropped_ticks: int = Field(ge=0)
    reconnect_count: int = Field(ge=0)
    heartbeat_delay_seconds: float = Field(ge=0)
    avg_latency_ms: float = Field(ge=0)
    max_latency_ms: float = Field(ge=0)
    avg_processing_ms: float = Field(ge=0)

    _aware = field_validator("as_of")(_require_aware)


class LiveMetrics:
    def __init__(self) -> None:
        self._message_times: deque[datetime] = deque()
        self._ticks_processed = 0
        self._dropped_ticks = 0
        self._reconnect_count = 0
        self._heartbeat_delay_seconds = 0.0
        self._latencies_ms: list[float] = []
        self._processing_ms: list[float] = []

    def record_tick(self, received_at: datetime, *, latency_ms: float) -> None:
        self._ticks_processed += 1
        self._message_times.append(received_at)
        self._latencies_ms.append(latency_ms)
        self._trim(received_at)

    def record_drop(self) -> None:
        self._dropped_ticks += 1

    def record_reconnect(self) -> None:
        self._reconnect_count += 1

    def record_heartbeat_delay(self, delay_seconds: float) -> None:
        self._heartbeat_delay_seconds = max(0.0, delay_seconds)

    def record_processing_time(self, milliseconds: float) -> None:
        self._processing_ms.append(max(0.0, milliseconds))

    def snapshot(self, as_of: datetime) -> LiveMetricsSnapshot:
        self._trim(as_of)
        avg_latency = (
            sum(self._latencies_ms) / len(self._latencies_ms) if self._latencies_ms else 0.0
        )
        avg_processing = (
            sum(self._processing_ms) / len(self._processing_ms) if self._processing_ms else 0.0
        )
        return LiveMetricsSnapshot(
            as_of=as_of,
            messages_per_second=round(float(len(self._message_times)), 6),
            ticks_processed=self._ticks_processed,
            dropped_ticks=self._dropped_ticks,
            reconnect_count=self._reconnect_count,
            heartbeat_delay_seconds=round(self._heartbeat_delay_seconds, 6),
            avg_latency_ms=round(avg_latency, 6),
            max_latency_ms=round(max(self._latencies_ms), 6) if self._latencies_ms else 0.0,
            avg_processing_ms=round(avg_processing, 6),
        )

    def _trim(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=1)
        while self._message_times and self._message_times[0] < cutoff:
            self._message_times.popleft()
