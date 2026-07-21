"""OMS order intent, planning, commands, and event-sourced order wrapper."""

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ceremyn.backtest.simulator import ExecutionSimulator
from ceremyn.domain import Order, OrderType, ProductType, Side, Signal
from ceremyn.domain.market_data import _require_aware
from ceremyn.oms.events import OMSEvent


class OMSExecutionState(StrEnum):
    NEW = "new"
    VALIDATED = "validated"
    ROUTED = "routed"
    PENDING = "pending"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCEL_PENDING = "cancel_pending"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    FAILED = "failed"
    EXPIRED = "expired"


class ExecutionStyle(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    BRACKET = "bracket"


class PlanOrderRole(StrEnum):
    ENTRY = "entry"
    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    COMPENSATION = "compensation"


class OrderIntent(BaseModel):
    model_config = ConfigDict(frozen=True)

    intent_id: UUID = Field(default_factory=uuid4)
    signal: Signal
    strategy_id: str = Field(min_length=1)
    signal_id: UUID
    correlation_id: UUID | None = None
    execution_style: ExecutionStyle = ExecutionStyle.MARKET
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    _aware = field_validator("created_at")(_require_aware)


class PlannedOrder(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: PlanOrderRole
    order: Order
    parent_order_id: UUID | None = None
    submit_immediately: bool = True


class OrderPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    plan_id: UUID = Field(default_factory=uuid4)
    intent_id: UUID
    strategy_id: str = Field(min_length=1)
    signal_id: UUID
    correlation_id: UUID | None = None
    orders: tuple[PlannedOrder, ...] = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    _aware = field_validator("created_at")(_require_aware)


class SubmitOrderCommand(BaseModel):
    model_config = ConfigDict(frozen=True)

    command_id: UUID = Field(default_factory=uuid4)
    oms_order_id: UUID
    correlation_id: UUID | None = None
    signal_id: UUID | None = None
    strategy_id: str = Field(min_length=1)
    broker_name: str = Field(min_length=1)
    request_hash: str = Field(min_length=1)
    order: Order
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    _aware = field_validator("requested_at")(_require_aware)


class CancelOrderCommand(BaseModel):
    model_config = ConfigDict(frozen=True)

    command_id: UUID = Field(default_factory=uuid4)
    oms_order_id: UUID
    external_order_id: str | None = None
    broker_name: str = Field(min_length=1)
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reason: str = ""

    _aware = field_validator("requested_at")(_require_aware)


class ReplaceOrderCommand(BaseModel):
    model_config = ConfigDict(frozen=True)

    command_id: UUID = Field(default_factory=uuid4)
    oms_order_id: UUID
    external_order_id: str | None = None
    broker_name: str = Field(min_length=1)
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    new_limit_price: Decimal | None = Field(default=None, gt=0)
    new_trigger_price: Decimal | None = Field(default=None, gt=0)
    reason: str = ""

    _aware = field_validator("requested_at")(_require_aware)


class OMSOrder(BaseModel):
    model_config = ConfigDict(frozen=True)

    oms_order_id: UUID = Field(default_factory=uuid4)
    plan_id: UUID
    intent_id: UUID
    parent_order_id: UUID | None = None
    role: PlanOrderRole = PlanOrderRole.ENTRY
    request_hash: str = Field(min_length=1)
    strategy_id: str = Field(min_length=1)
    signal_id: UUID | None = None
    correlation_id: UUID | None = None
    order: Order
    execution_state: OMSExecutionState = OMSExecutionState.NEW
    broker_name: str | None = None
    external_order_id: str | None = None
    filled_quantity: int = Field(default=0, ge=0)
    average_fill_price: Decimal | None = Field(default=None, gt=0)
    retry_count: int = Field(default=0, ge=0)
    duplicate_count: int = Field(default=0, ge=0)
    last_error: str = ""
    event_log: tuple[OMSEvent, ...] = ()
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    _aware_created = field_validator("created_at")(_require_aware)
    _aware_updated = field_validator("updated_at")(_require_aware)

    @property
    def remaining_quantity(self) -> int:
        return max(0, self.order.quantity - self.filled_quantity)

    @property
    def is_terminal(self) -> bool:
        return self.execution_state in {
            OMSExecutionState.FILLED,
            OMSExecutionState.CANCELLED,
            OMSExecutionState.REJECTED,
            OMSExecutionState.FAILED,
            OMSExecutionState.EXPIRED,
        }

    def with_event(self, event: OMSEvent) -> "OMSOrder":
        from ceremyn.oms.state_machine import reduce_order

        return reduce_order(self, event)


class OrderPlanner:
    def __init__(self) -> None:
        self._builder = ExecutionSimulator()

    def intent_from_signal(self, signal: Signal, *, now: datetime | None = None) -> OrderIntent:
        execution = signal.metadata.get("execution", {})
        style = ExecutionStyle(str(execution.get("style", "market")))
        timestamp = now or signal.market_timestamp or signal.created_at
        return OrderIntent(
            signal=signal,
            strategy_id=signal.strategy_id,
            signal_id=signal.signal_id,
            correlation_id=signal.correlation_id,
            execution_style=style,
            created_at=timestamp,
            metadata=execution,
        )

    def plan(self, intent: OrderIntent, *, now: datetime | None = None) -> OrderPlan:
        timestamp = now or intent.signal.market_timestamp or intent.signal.created_at
        base_orders = self._builder.orders_from_signal(intent.signal, created_at=timestamp)
        planned_orders = [
            PlannedOrder(role=PlanOrderRole.ENTRY, order=order) for order in base_orders
        ]
        if intent.execution_style is ExecutionStyle.BRACKET:
            planned_orders.extend(self._bracket_orders(base_orders, intent, timestamp))
        return OrderPlan(
            intent_id=intent.intent_id,
            strategy_id=intent.strategy_id,
            signal_id=intent.signal_id,
            correlation_id=intent.correlation_id,
            orders=tuple(planned_orders),
            created_at=timestamp,
        )

    def request_hash(self, plan: OrderPlan, planned_order: PlannedOrder) -> str:
        payload = [
            str(plan.signal_id),
            plan.strategy_id,
            str(plan.correlation_id),
            planned_order.role.value,
            planned_order.order.contract.tradingsymbol,
            planned_order.order.side.value,
            str(planned_order.order.quantity),
            planned_order.order.order_type.value,
            str(planned_order.order.limit_price),
            str(planned_order.order.trigger_price),
            planned_order.order.product.value,
            str(planned_order.parent_order_id),
        ]
        return hashlib.sha256("|".join(payload).encode()).hexdigest()

    def _bracket_orders(
        self,
        base_orders: tuple[Order, ...],
        intent: OrderIntent,
        timestamp: datetime,
    ) -> list[PlannedOrder]:
        bracket = intent.metadata.get("bracket", {})
        take_profit = bracket.get("take_profit_limit")
        stop_trigger = bracket.get("stop_trigger")
        stop_limit = bracket.get("stop_limit")
        planned: list[PlannedOrder] = []
        for order in base_orders:
            exit_side = Side.SELL if order.side is Side.BUY else Side.BUY
            if take_profit is not None:
                planned.append(
                    PlannedOrder(
                        role=PlanOrderRole.TAKE_PROFIT,
                        order=Order(
                            signal_id=order.signal_id,
                            contract=order.contract,
                            side=exit_side,
                            quantity=order.quantity,
                            order_type=OrderType.LIMIT,
                            product=order.product,
                            limit_price=Decimal(str(take_profit)),
                            status=order.status,
                            created_at=timestamp,
                        ),
                        parent_order_id=order.id,
                        submit_immediately=False,
                    )
                )
            if stop_trigger is not None:
                planned.append(
                    PlannedOrder(
                        role=PlanOrderRole.STOP_LOSS,
                        order=Order(
                            signal_id=order.signal_id,
                            contract=order.contract,
                            side=exit_side,
                            quantity=order.quantity,
                            order_type=(
                                OrderType.SL_LIMIT
                                if stop_limit is not None
                                else OrderType.SL_MARKET
                            ),
                            product=ProductType.NRML,
                            limit_price=(
                                Decimal(str(stop_limit)) if stop_limit is not None else None
                            ),
                            trigger_price=Decimal(str(stop_trigger)),
                            status=order.status,
                            created_at=timestamp,
                        ),
                        parent_order_id=order.id,
                        submit_immediately=False,
                    )
                )
        return planned
