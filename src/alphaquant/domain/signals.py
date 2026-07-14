"""Strategy signals.

A Signal is a strategy's *intent* — it is not an order. Only the OMS turns
signals into orders, and only after the risk engine validates them. Strategies
therefore never need (and never get) a broker handle.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from alphaquant.domain.enums import Side, SignalAction
from alphaquant.domain.instruments import OptionContract


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

    id: UUID = Field(default_factory=uuid4)
    strategy_id: str = Field(min_length=1)
    action: SignalAction
    legs: tuple[SignalLeg, ...] = Field(min_length=1)
    reason: str = ""  # human-readable rationale, shown in the journal
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
