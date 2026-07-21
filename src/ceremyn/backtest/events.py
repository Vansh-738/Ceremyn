"""Backtest event stream models."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ceremyn.domain import Candle, OptionChainSnapshot, Quote
from ceremyn.domain.market_data import _require_aware


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
