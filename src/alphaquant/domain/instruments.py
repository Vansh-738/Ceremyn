"""Tradable instruments."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from alphaquant.domain.enums import Exchange, OptionType


class Instrument(BaseModel):
    """A tradable instrument identified by its exchange trading symbol."""

    model_config = ConfigDict(frozen=True)

    tradingsymbol: str = Field(min_length=1)
    exchange: Exchange
    tick_size: Decimal = Field(default=Decimal("0.05"), gt=0)
    # Broker-assigned numeric id (e.g. Kite instrument_token); optional because
    # historical/backtest instruments may never touch a broker.
    broker_token: int | None = None


class OptionContract(Instrument):
    """A single options contract on an index underlying."""

    underlying: str = Field(min_length=1)  # e.g. "NIFTY", "BANKNIFTY"
    expiry: date
    strike: Decimal = Field(gt=0)
    option_type: OptionType
    lot_size: int = Field(gt=0)

    @property
    def is_call(self) -> bool:
        return self.option_type is OptionType.CALL

    @property
    def is_put(self) -> bool:
        return self.option_type is OptionType.PUT
