"""PaperMonitor: live operational metrics for a paper session.

Tracks order latency (submit → fill), fill rate, rejected and cancelled counts, and
per-strategy runtime. The engine feeds it events; it exposes an immutable snapshot.
"""

from collections import defaultdict

from pydantic import BaseModel, ConfigDict, Field

from ceremyn.paper.events import (
    OrderCancelled,
    OrderFilled,
    OrderRejected,
    OrderSubmitted,
    SignalGenerated,
)


class MonitorSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    submitted: int = 0
    filled: int = 0
    rejected: int = 0
    cancelled: int = 0
    signals: int = 0
    avg_latency_seconds: float = 0.0
    max_latency_seconds: float = 0.0
    fill_rate: float = 0.0  # filled / submitted, 0..1
    strategy_runtime_seconds: dict[str, float] = Field(default_factory=dict)


class PaperMonitor:
    def __init__(self) -> None:
        self._submitted = 0
        self._filled = 0
        self._rejected = 0
        self._cancelled = 0
        self._signals = 0
        self._latencies: list[float] = []
        self._runtime: dict[str, float] = defaultdict(float)

    def on_signal(self, event: SignalGenerated) -> None:
        self._signals += 1
        self._runtime[event.strategy_id] += event.runtime_seconds

    def on_submitted(self, event: OrderSubmitted) -> None:
        self._submitted += 1

    def on_filled(self, event: OrderFilled) -> None:
        self._filled += 1
        self._latencies.append(event.latency_seconds)

    def on_rejected(self, event: OrderRejected) -> None:
        self._rejected += 1

    def on_cancelled(self, event: OrderCancelled) -> None:
        self._cancelled += 1

    def snapshot(self) -> MonitorSnapshot:
        avg_latency = sum(self._latencies) / len(self._latencies) if self._latencies else 0.0
        return MonitorSnapshot(
            submitted=self._submitted,
            filled=self._filled,
            rejected=self._rejected,
            cancelled=self._cancelled,
            signals=self._signals,
            avg_latency_seconds=round(avg_latency, 6),
            max_latency_seconds=round(max(self._latencies), 6) if self._latencies else 0.0,
            fill_rate=round(self._filled / self._submitted, 6) if self._submitted else 0.0,
            strategy_runtime_seconds={k: round(v, 6) for k, v in self._runtime.items()},
        )
