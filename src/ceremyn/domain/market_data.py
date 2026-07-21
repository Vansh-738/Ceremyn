"""Market-data value objects: quotes and candles."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ceremyn.domain.enums import TimeFrame


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value


class Quote(BaseModel):
    """A point-in-time quote for one instrument."""

    model_config = ConfigDict(frozen=True)

    tradingsymbol: str = Field(min_length=1)
    timestamp: datetime
    last_price: Decimal = Field(ge=0)
    bid: Decimal | None = Field(default=None, ge=0)
    ask: Decimal | None = Field(default=None, ge=0)
    volume: int = Field(default=0, ge=0)
    open_interest: int = Field(default=0, ge=0)

    _aware = field_validator("timestamp")(_require_aware)

    @property
    def mid(self) -> Decimal | None:
        """Bid/ask midpoint; None unless both sides are quoted."""
        if self.bid is None or self.ask is None:
            return None
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> Decimal | None:
        if self.bid is None or self.ask is None:
            return None
        return self.ask - self.bid


class Candle(BaseModel):
    """One OHLCV bar. `timestamp` is the bar's open time (timezone-aware)."""

    model_config = ConfigDict(frozen=True)

    tradingsymbol: str = Field(min_length=1)
    timeframe: TimeFrame
    timestamp: datetime
    open: Decimal = Field(ge=0)
    high: Decimal = Field(ge=0)
    low: Decimal = Field(ge=0)
    close: Decimal = Field(ge=0)
    volume: int = Field(default=0, ge=0)
    open_interest: int = Field(default=0, ge=0)

    _aware = field_validator("timestamp")(_require_aware)

    @model_validator(mode="after")
    def _check_ohlc_consistency(self) -> "Candle":
        if self.high < self.low:
            raise ValueError("high < low")
        if not (self.low <= self.open <= self.high):
            raise ValueError("open outside [low, high]")
        if not (self.low <= self.close <= self.high):
            raise ValueError("close outside [low, high]")
        return self
