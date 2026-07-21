"""Broker abstraction and normalized execution report models."""

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ceremyn.domain.market_data import _require_aware
from ceremyn.oms.orders import CancelOrderCommand, ReplaceOrderCommand, SubmitOrderCommand


class BrokerOrderStatus(StrEnum):
    ACKNOWLEDGED = "acknowledged"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCEL_PENDING = "cancel_pending"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    FAILED = "failed"
    EXPIRED = "expired"


class BrokerCapabilities(BaseModel):
    model_config = ConfigDict(frozen=True)

    supports_cancel: bool = True
    supports_replace: bool = False
    supports_brackets: bool = False
    supports_stop: bool = True
    supports_stop_limit: bool = True
    supports_partial_fills: bool = True
    supports_tags: bool = False


class BrokerSubmissionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    external_order_id: str = Field(min_length=1)
    acknowledged: bool = True
    broker_timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: BrokerOrderStatus = BrokerOrderStatus.ACKNOWLEDGED
    message: str = ""
    broker_latency_seconds: float = Field(default=0.0, ge=0)

    _aware = field_validator("broker_timestamp")(_require_aware)


class BrokerCancelResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    accepted: bool = True
    broker_timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    message: str = ""
    broker_latency_seconds: float = Field(default=0.0, ge=0)

    _aware = field_validator("broker_timestamp")(_require_aware)


class BrokerReplaceResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    accepted: bool = True
    broker_timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    message: str = ""
    broker_latency_seconds: float = Field(default=0.0, ge=0)

    _aware = field_validator("broker_timestamp")(_require_aware)


class BrokerOrderSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    external_order_id: str = Field(min_length=1)
    status: BrokerOrderStatus
    broker_timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    filled_quantity: int = Field(default=0, ge=0)
    remaining_quantity: int = Field(default=0, ge=0)
    average_price: Decimal | None = Field(default=None, gt=0)
    correlation_id: str | None = None
    request_hash: str | None = None
    message: str = ""

    _aware = field_validator("broker_timestamp")(_require_aware)


class BrokerExecutionReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    external_order_id: str = Field(min_length=1)
    status: BrokerOrderStatus
    broker_timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    fill_id: str | None = None
    last_fill_quantity: int = Field(default=0, ge=0)
    fill_price: Decimal | None = Field(default=None, gt=0)
    remaining_quantity: int = Field(default=0, ge=0)
    broker_latency_seconds: float = Field(default=0.0, ge=0)
    message: str = ""

    _aware = field_validator("broker_timestamp")(_require_aware)


class BrokerPositionSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    tradingsymbol: str = Field(min_length=1)
    quantity: int
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")


class BrokerCashSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    available_cash: Decimal
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")


@runtime_checkable
class BrokerAdapter(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def capabilities(self) -> BrokerCapabilities: ...

    def submit(self, command: SubmitOrderCommand) -> BrokerSubmissionResult: ...

    def cancel(self, command: CancelOrderCommand) -> BrokerCancelResult: ...

    def replace(self, command: ReplaceOrderCommand) -> BrokerReplaceResult: ...

    def lookup_order(self, command: SubmitOrderCommand) -> BrokerOrderSnapshot | None: ...

    def fetch_orders(self) -> Sequence[BrokerOrderSnapshot]: ...

    def fetch_fills(self) -> Sequence[BrokerExecutionReport]: ...

    def fetch_positions(self) -> Sequence[BrokerPositionSnapshot]: ...

    def fetch_cash(self) -> BrokerCashSnapshot: ...
