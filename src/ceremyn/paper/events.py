"""Paper-trading events.

`MarketTick` is the input the engine consumes each cycle; the lifecycle events are
published on the reused `core.EventBus` so the monitor and journal can observe the
session without the engine depending on them directly.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ceremyn.backtest.commission import CostBreakdown
from ceremyn.domain import Candle, Fill, OptionChainSnapshot, Order, Signal
from ceremyn.domain.market_data import _require_aware
from ceremyn.risk import RiskDecision


class MarketTick(BaseModel):
    """One real-time observation for a single underlying."""

    model_config = ConfigDict(frozen=True)

    as_of: datetime
    underlying: str = Field(min_length=1)
    chain: OptionChainSnapshot
    candles: tuple[Candle, ...] = ()
    iv_history: tuple[float, ...] = ()

    _aware = field_validator("as_of")(_require_aware)


class SignalGenerated(BaseModel):
    model_config = ConfigDict(frozen=True)

    signal: Signal
    strategy_id: str
    runtime_seconds: float = Field(ge=0)


class RiskEvaluated(BaseModel):
    model_config = ConfigDict(frozen=True)

    signal: Signal
    decision: RiskDecision


class OrderSubmitted(BaseModel):
    model_config = ConfigDict(frozen=True)

    order: Order
    submitted_at: datetime

    _aware = field_validator("submitted_at")(_require_aware)


class OrderFilled(BaseModel):
    model_config = ConfigDict(frozen=True)

    order: Order
    fill: Fill
    costs: CostBreakdown
    submitted_at: datetime
    strategy_id: str

    _aware = field_validator("submitted_at")(_require_aware)

    @property
    def latency_seconds(self) -> float:
        return (self.fill.timestamp - self.submitted_at).total_seconds()


class OrderRejected(BaseModel):
    model_config = ConfigDict(frozen=True)

    signal: Signal
    reason: str


class OrderCancelled(BaseModel):
    model_config = ConfigDict(frozen=True)

    order_id: UUID
    reason: str = ""


class PositionClosed(BaseModel):
    model_config = ConfigDict(frozen=True)

    tradingsymbol: str
    strategy_id: str
    net_pnl: str  # Decimal serialized as string for event transport
