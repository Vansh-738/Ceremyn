"""Fill simulation primitives."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ceremyn.backtest.commission import CostBreakdown
from ceremyn.domain import Candle, Fill, OptionChainSnapshot, Order, Quote
from ceremyn.domain.enums import OrderStatus
from ceremyn.domain.market_data import _require_aware


class PendingOrderState(BaseModel):
    model_config = ConfigDict(frozen=True)

    order: Order
    remaining_quantity: int = Field(gt=0)
    triggered: bool = False


class VirtualFill(BaseModel):
    model_config = ConfigDict(frozen=True)

    order: Order
    fill: Fill
    updated_order: Order
    cost_breakdown: CostBreakdown
    signal_id: UUID | None = None
    strategy_id: str = Field(min_length=1)


class ExecutionContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    chain: OptionChainSnapshot | None = None
    quotes: dict[str, Quote] = Field(default_factory=dict)
    candles: dict[str, Candle] = Field(default_factory=dict)

    _aware = field_validator("timestamp")(_require_aware)

    def quote_for(self, tradingsymbol: str) -> Quote | None:
        quote = self.quotes.get(tradingsymbol)
        if quote is not None:
            return quote
        if self.chain is None:
            return None
        for entry in self.chain.entries:
            if entry.contract.tradingsymbol == tradingsymbol:
                return entry.quote
        return None

    def candle_for(self, tradingsymbol: str) -> Candle | None:
        return self.candles.get(tradingsymbol)


def terminal_status(remaining_quantity: int) -> OrderStatus:
    return OrderStatus.FILLED if remaining_quantity == 0 else OrderStatus.PARTIALLY_FILLED
