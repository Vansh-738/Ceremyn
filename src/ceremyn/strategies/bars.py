"""Completed-bar context shared by research and runtime drivers."""

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from ceremyn.domain import Candle, EquityInstrument, Pattern, PortfolioSnapshot, Position
from ceremyn.domain.fundamentals import FundamentalScore
from ceremyn.domain.market_data import _require_aware


class BarContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    as_of: datetime
    instrument: EquityInstrument
    candles: tuple[Candle, ...]
    patterns: tuple[Pattern, ...] = ()
    fundamentals: FundamentalScore | None = None
    positions: tuple[Position, ...] = ()
    portfolio: PortfolioSnapshot | None = None

    @model_validator(mode="after")
    def no_future_data(self) -> Self:
        _require_aware(self.as_of)
        symbol = self.instrument.tradingsymbol
        if not self.candles or self.candles[-1].timestamp != self.as_of:
            raise ValueError("context must end at its completed bar")
        if any(c.tradingsymbol != symbol for c in self.candles):
            raise ValueError("mixed candle symbols")
        if any(
            a.timestamp >= b.timestamp for a, b in zip(self.candles, self.candles[1:], strict=False)
        ):
            raise ValueError("candles must be strictly chronological")
        if any(p.detected_at > self.as_of or p.tradingsymbol != symbol for p in self.patterns):
            raise ValueError("future or mismatched pattern")
        if self.fundamentals and (
            self.fundamentals.as_of > self.as_of or self.fundamentals.symbol != symbol
        ):
            raise ValueError("future or mismatched fundamentals")
        return self
