"""Backtest event stream models."""

from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ceremyn.domain import Candle, CorporateAction, OptionChainSnapshot, Quote
from ceremyn.domain.market_data import _require_aware
from ceremyn.strategies.bars import BarContext


class BacktestEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: datetime

    _aware = field_validator("timestamp")(_require_aware)


class OptionChainEvent(BacktestEvent):
    chain: OptionChainSnapshot


class QuoteEvent(BacktestEvent):
    quote: Quote


class CandleEvent(BacktestEvent):
    candle: Candle


class MarketSignalEvent(BacktestEvent):
    name: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class BarEvent(BacktestEvent):
    """A completed equity bar and only the evidence available by that close."""

    context: BarContext
    actions: tuple[CorporateAction, ...] = ()

    @model_validator(mode="after")
    def consistent_time(self) -> Self:
        if self.timestamp != self.context.as_of:
            raise ValueError("bar event time must match context")
        return self
