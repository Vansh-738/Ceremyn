"""Orders and fills, with an explicit status state machine.

Orders are immutable; every status change goes through `transition_to`, which
returns a new Order and rejects illegal transitions. This keeps the audit trail
honest — there is no way to silently flip an order's state.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ceremyn.domain.enums import (
    TERMINAL_ORDER_STATUSES,
    OrderStatus,
    OrderType,
    ProductType,
    Side,
)
from ceremyn.domain.errors import OrderTransitionError
from ceremyn.domain.instruments import Instrument
from ceremyn.domain.market_data import _require_aware

VALID_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.CREATED: frozenset({OrderStatus.VALIDATED, OrderStatus.REJECTED}),
    OrderStatus.VALIDATED: frozenset(
        {OrderStatus.SUBMITTED, OrderStatus.REJECTED, OrderStatus.CANCELLED}
    ),
    OrderStatus.SUBMITTED: frozenset(
        {
            OrderStatus.OPEN,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,  # market orders can fill on arrival
            OrderStatus.REJECTED,
            OrderStatus.CANCELLED,
        }
    ),
    OrderStatus.OPEN: frozenset(
        {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
        }
    ),
    OrderStatus.PARTIALLY_FILLED: frozenset({OrderStatus.FILLED, OrderStatus.CANCELLED}),
    OrderStatus.FILLED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.REJECTED: frozenset(),
}


class Order(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    signal_id: UUID | None = None
    contract: Instrument
    side: Side
    quantity: int = Field(gt=0)  # units, must be a whole number of lots
    order_type: OrderType
    product: ProductType = ProductType.NRML
    limit_price: Decimal | None = Field(default=None, gt=0)
    trigger_price: Decimal | None = Field(default=None, gt=0)
    status: OrderStatus = OrderStatus.CREATED
    status_reason: str = ""  # e.g. which risk rule rejected it
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    _aware = field_validator("created_at")(_require_aware)

    @model_validator(mode="after")
    def _check_invariants(self) -> "Order":
        if self.quantity % self.contract.lot_size != 0:
            raise ValueError(
                f"quantity {self.quantity} is not a multiple of "
                f"lot size {self.contract.lot_size}"
            )
        if self.order_type in (OrderType.LIMIT, OrderType.SL_LIMIT) and self.limit_price is None:
            raise ValueError(f"{self.order_type} order requires limit_price")
        if (
            self.order_type in (OrderType.SL_LIMIT, OrderType.SL_MARKET)
            and self.trigger_price is None
        ):
            raise ValueError(f"{self.order_type} order requires trigger_price")
        return self

    @property
    def lots(self) -> int:
        return self.quantity // self.contract.lot_size

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_ORDER_STATUSES

    def transition_to(self, new_status: OrderStatus, reason: str = "") -> "Order":
        if new_status not in VALID_TRANSITIONS[self.status]:
            raise OrderTransitionError(
                f"order {self.id}: illegal transition {self.status} -> {new_status}"
            )
        return self.model_copy(update={"status": new_status, "status_reason": reason})


class Fill(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    order_id: UUID
    quantity: int = Field(gt=0)
    price: Decimal = Field(gt=0)
    timestamp: datetime

    _aware = field_validator("timestamp")(_require_aware)
