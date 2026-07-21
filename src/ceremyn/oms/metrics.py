"""Operational metrics for the OMS."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ceremyn.domain.market_data import _require_aware


class OMSMetricsSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    as_of: datetime
    orders_submitted: int = Field(ge=0)
    orders_filled: int = Field(ge=0)
    partial_fills: int = Field(ge=0)
    rejections: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    average_latency_seconds: float = Field(ge=0)
    broker_latency_seconds: float = Field(ge=0)
    p95_latency_seconds: float = Field(ge=0)
    p99_latency_seconds: float = Field(ge=0)
    fill_ratio: float = Field(ge=0)
    duplicate_suppressed: int = Field(ge=0)
    retry_success_rate: float = Field(ge=0)
    broker_uptime_ratio: float = Field(ge=0)

    _aware = field_validator("as_of")(_require_aware)


class OMSMetrics:
    def __init__(self) -> None:
        self.orders_submitted = 0
        self.orders_filled = 0
        self.partial_fills = 0
        self.rejections = 0
        self.retry_count = 0
        self.duplicate_suppressed = 0
        self.retry_successes = 0
        self.broker_successes = 0
        self.broker_failures = 0
        self._latencies: list[float] = []
        self._broker_latencies: list[float] = []

    def record_submission(self, latency_seconds: float, *, broker_latency_seconds: float) -> None:
        self.orders_submitted += 1
        self._latencies.append(latency_seconds)
        self._broker_latencies.append(broker_latency_seconds)

    def record_fill(self, *, partial: bool) -> None:
        if partial:
            self.partial_fills += 1
        else:
            self.orders_filled += 1

    def record_rejection(self) -> None:
        self.rejections += 1

    def record_retry(self, *, success: bool) -> None:
        self.retry_count += 1
        if success:
            self.retry_successes += 1

    def record_duplicate(self) -> None:
        self.duplicate_suppressed += 1

    def record_broker_health(self, *, success: bool) -> None:
        if success:
            self.broker_successes += 1
        else:
            self.broker_failures += 1

    def snapshot(self, as_of: datetime) -> OMSMetricsSnapshot:
        return OMSMetricsSnapshot(
            as_of=as_of,
            orders_submitted=self.orders_submitted,
            orders_filled=self.orders_filled,
            partial_fills=self.partial_fills,
            rejections=self.rejections,
            retry_count=self.retry_count,
            average_latency_seconds=_average(self._latencies),
            broker_latency_seconds=_average(self._broker_latencies),
            p95_latency_seconds=_percentile(self._latencies, 95),
            p99_latency_seconds=_percentile(self._latencies, 99),
            fill_ratio=(
                (self.orders_filled + self.partial_fills) / self.orders_submitted
                if self.orders_submitted
                else 0.0
            ),
            duplicate_suppressed=self.duplicate_suppressed,
            retry_success_rate=(
                self.retry_successes / self.retry_count if self.retry_count else 0.0
            ),
            broker_uptime_ratio=(
                self.broker_successes / (self.broker_successes + self.broker_failures)
                if (self.broker_successes + self.broker_failures)
                else 1.0
            ),
        )


def _average(values: list[float]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((percentile / 100) * (len(ordered) - 1)))))
    return round(ordered[index], 6)
