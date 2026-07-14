"""Positions and closed trades.

Position quantity is signed: positive = long, negative = short. Positions are
immutable; `apply_fill` returns the updated position with realized P&L booked
using weighted-average-cost accounting.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from alphaquant.domain.enums import Side
from alphaquant.domain.instruments import OptionContract
from alphaquant.domain.market_data import _require_aware


class Position(BaseModel):
    model_config = ConfigDict(frozen=True)

    contract: OptionContract
    quantity: int = 0  # signed units
    avg_price: Decimal = Decimal("0")  # of the open quantity; 0 when flat
    realized_pnl: Decimal = Decimal("0")  # gross, before transaction costs

    @property
    def is_flat(self) -> bool:
        return self.quantity == 0

    @property
    def is_long(self) -> bool:
        return self.quantity > 0

    @property
    def is_short(self) -> bool:
        return self.quantity < 0

    def unrealized_pnl(self, last_price: Decimal) -> Decimal:
        return (last_price - self.avg_price) * self.quantity

    def apply_fill(self, side: Side, quantity: int, price: Decimal) -> "Position":
        """Return the position after a fill of `quantity` units at `price`."""
        if quantity <= 0:
            raise ValueError("fill quantity must be positive")
        if price <= 0:
            raise ValueError("fill price must be positive")

        signed = quantity if side is Side.BUY else -quantity
        current = self.quantity

        if current == 0:
            return self.model_copy(update={"quantity": signed, "avg_price": price})

        if (current > 0) == (signed > 0):
            # Same direction: extend at weighted-average cost.
            new_qty = current + signed
            new_avg = (self.avg_price * abs(current) + price * abs(signed)) / abs(new_qty)
            return self.model_copy(update={"quantity": new_qty, "avg_price": new_avg})

        # Opposite direction: close (part of) the position, book realized P&L.
        closed = min(abs(current), abs(signed))
        direction = 1 if current > 0 else -1
        realized = self.realized_pnl + (price - self.avg_price) * closed * direction
        remaining = current + signed

        if remaining == 0:
            return self.model_copy(
                update={"quantity": 0, "avg_price": Decimal("0"), "realized_pnl": realized}
            )
        if abs(remaining) < abs(current):
            # Reduced but not closed: average price of the remainder unchanged.
            return self.model_copy(update={"quantity": remaining, "realized_pnl": realized})
        # Flipped through zero: remainder is a fresh position at the fill price.
        return self.model_copy(
            update={"quantity": remaining, "avg_price": price, "realized_pnl": realized}
        )


class Trade(BaseModel):
    """A closed round-trip, as recorded in the journal."""

    model_config = ConfigDict(frozen=True)

    contract: OptionContract
    strategy_id: str = Field(min_length=1)
    quantity: int = Field(gt=0)  # units traded (absolute)
    direction: Side  # side of the opening leg
    entry_price: Decimal = Field(gt=0)
    exit_price: Decimal = Field(gt=0)
    entry_at: datetime
    exit_at: datetime
    gross_pnl: Decimal
    costs: Decimal = Field(default=Decimal("0"), ge=0)

    _aware_entry = field_validator("entry_at")(_require_aware)
    _aware_exit = field_validator("exit_at")(_require_aware)

    @property
    def net_pnl(self) -> Decimal:
        return self.gross_pnl - self.costs
