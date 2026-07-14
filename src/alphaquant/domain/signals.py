"""Strategy signals.

A Signal is a strategy's *intent* — it is not an order. Only the OMS turns
signals into orders, and only after the risk engine validates them. Strategies
therefore never need (and never get) a broker handle.
"""

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from alphaquant.domain.enums import Side, SignalAction
from alphaquant.domain.instruments import OptionContract


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value


class SignalLeg(BaseModel):
    model_config = ConfigDict(frozen=True)

    contract: OptionContract
    side: Side
    lots: int = Field(gt=0)

    @property
    def quantity(self) -> int:
        """Quantity in units (lots times lot size), as brokers expect."""
        return self.lots * self.contract.lot_size


class Signal(BaseModel):
    """A (possibly multi-leg) trading intent emitted by a strategy."""

    model_config = ConfigDict(frozen=True)

    signal_id: UUID = Field(
        default_factory=uuid4,
        validation_alias=AliasChoices("signal_id", "id"),
    )
    strategy_id: str = Field(min_length=1)
    strategy_version: str = Field(default="1", min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    market_timestamp: datetime | None = None
    underlying: str | None = Field(default=None, min_length=1)
    expiry: date | None = None
    signal_type: SignalAction = Field(validation_alias=AliasChoices("signal_type", "action"))
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    priority: int = Field(default=50, ge=0, le=100)
    reason: str = ""  # human-readable rationale, shown in the journal
    metadata: dict[str, Any] = Field(default_factory=dict)
    correlation_id: UUID | None = None
    replay_id: str | None = None
    legs: tuple[SignalLeg, ...] = Field(min_length=1)

    _aware_created = field_validator("created_at")(_require_aware)
    _aware_market = field_validator("market_timestamp")(_require_aware)

    @model_validator(mode="after")
    def _derive_scope(self) -> "Signal":
        underlying = self.underlying or self.legs[0].contract.underlying
        expiry = self.expiry or self.legs[0].contract.expiry
        if any(leg.contract.underlying != underlying for leg in self.legs):
            raise ValueError("signal legs must share the same underlying")
        if any(leg.contract.expiry != expiry for leg in self.legs):
            raise ValueError("signal legs must share the same expiry")
        market_timestamp = self.market_timestamp or self.created_at
        object.__setattr__(self, "underlying", underlying)
        object.__setattr__(self, "expiry", expiry)
        object.__setattr__(self, "market_timestamp", market_timestamp)
        return self

    @property
    def id(self) -> UUID:
        return self.signal_id

    @property
    def action(self) -> SignalAction:
        return self.signal_type
