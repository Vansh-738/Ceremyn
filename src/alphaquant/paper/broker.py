"""PaperBroker: a real-time fill simulator with an order queue and latency.

Fill mechanics — market / limit / stop orders, partial fills, slippage, and costs —
are entirely reused from the backtest `ExecutionSimulator`. What the paper broker adds
is real-time behaviour the backtester does not need:

- an **order queue**: submitted orders rest until a later `process` cycle;
- **latency**: an order is not eligible to fill until `submitted_at + latency` has passed.

Every fill is simulated locally. There is no broker order API and no live order ever leaves
this process.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from alphaquant.backtest.commission import IndianCostModel
from alphaquant.backtest.fills import ExecutionContext, PendingOrderState, VirtualFill
from alphaquant.backtest.simulator import ExecutionSimulator, SimulationConfig
from alphaquant.backtest.slippage import FixedBpsSlippageModel, SlippageModel
from alphaquant.domain import Order


class PaperBrokerConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    latency_seconds: float = Field(default=0.5, ge=0)
    slippage_bps: Decimal = Field(default=Decimal("5"), ge=0)
    max_volume_participation: float = Field(default=1.0, gt=0, le=1.0)


class _QueuedOrder(BaseModel):
    model_config = ConfigDict(frozen=True)

    state: PendingOrderState
    strategy_id: str
    submitted_at: datetime
    eligible_at: datetime


class PaperBroker:
    """Queues orders, then fills eligible ones through the reused simulator."""

    def __init__(
        self,
        config: PaperBrokerConfig | None = None,
        *,
        slippage_model: SlippageModel | None = None,
        commission_model: IndianCostModel | None = None,
    ) -> None:
        self.config = config or PaperBrokerConfig()
        self._simulator = ExecutionSimulator(
            config=SimulationConfig(max_volume_participation=self.config.max_volume_participation),
            slippage_model=slippage_model or FixedBpsSlippageModel(bps=self.config.slippage_bps),
            commission_model=commission_model or IndianCostModel(),
        )
        self._queue: dict[UUID, _QueuedOrder] = {}
        self.submitted_at: dict[UUID, datetime] = {}

    def submit(self, order: Order, *, strategy_id: str, now: datetime) -> None:
        """Enqueue an order; it becomes eligible to fill after the latency window."""
        self._queue[order.id] = _QueuedOrder(
            state=PendingOrderState(order=order, remaining_quantity=order.quantity),
            strategy_id=strategy_id,
            submitted_at=now,
            eligible_at=now + timedelta(seconds=self.config.latency_seconds),
        )
        self.submitted_at[order.id] = now

    def cancel(self, order_id: UUID) -> bool:
        """Remove a resting order from the queue; True if it was present."""
        return self._queue.pop(order_id, None) is not None

    @property
    def open_orders(self) -> tuple[Order, ...]:
        return tuple(queued.state.order for queued in self._queue.values())

    def process(self, *, context: ExecutionContext, now: datetime) -> tuple[VirtualFill, ...]:
        """Advance eligible queued orders through the simulator; return any fills."""
        fills: list[VirtualFill] = []
        for order_id, queued in list(self._queue.items()):
            if now < queued.eligible_at:
                continue
            remaining, order_fills = self._simulator.simulate_pending(
                (queued.state,),
                context=context,
                strategy_id=queued.strategy_id,
            )
            fills.extend(order_fills)
            if remaining:
                # Partially filled or still resting: keep the reduced state queued.
                self._queue[order_id] = queued.model_copy(update={"state": remaining[0]})
            else:
                del self._queue[order_id]
        return tuple(fills)

    def has_open(self, order_id: UUID) -> bool:
        return order_id in self._queue
