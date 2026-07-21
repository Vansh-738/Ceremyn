"""Slippage models for virtual execution."""

from abc import ABC, abstractmethod
from decimal import Decimal

from ceremyn.domain.enums import Side


class SlippageModel(ABC):
    @abstractmethod
    def apply(
        self,
        *,
        side: Side,
        reference_price: Decimal,
        spread: Decimal | None = None,
    ) -> Decimal:
        """Return a slipped execution price."""


class NoSlippageModel(SlippageModel):
    def apply(
        self,
        *,
        side: Side,
        reference_price: Decimal,
        spread: Decimal | None = None,
    ) -> Decimal:
        return reference_price


class FixedBpsSlippageModel(SlippageModel):
    def __init__(self, bps: Decimal = Decimal("5")) -> None:
        self.bps = bps

    def apply(
        self,
        *,
        side: Side,
        reference_price: Decimal,
        spread: Decimal | None = None,
    ) -> Decimal:
        multiplier = Decimal("1") + (self.bps / Decimal("10000"))
        if side is Side.BUY:
            return reference_price * multiplier
        return reference_price / multiplier
