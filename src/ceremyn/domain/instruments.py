"""Tradable instruments."""

from datetime import date
from decimal import Decimal
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from ceremyn.domain.enums import AssetClass, Exchange, OptionType


class Instrument(BaseModel):
    """A tradable instrument identified by its exchange trading symbol.

    Asset-class-specific subclasses (`OptionContract`, `EquityInstrument`,
    `FutureContract`, `ETFInstrument`) add only the fields their asset class
    actually needs; `Position`/`Order`/`SignalLeg`/`Trade` hold a plain
    `Instrument` so the same domain/risk/OMS code works across asset classes.
    """

    model_config = ConfigDict(frozen=True)

    asset_class: ClassVar[AssetClass]

    tradingsymbol: str = Field(min_length=1)
    exchange: Exchange
    tick_size: Decimal = Field(default=Decimal("0.05"), gt=0)
    # Broker-assigned numeric id (e.g. Kite instrument_token); optional because
    # historical/backtest instruments may never touch a broker.
    broker_token: int | None = None
    # What this instrument is fundamentally exposed to: an index/stock name for a
    # derivative, or its own tradingsymbol for a plain equity/ETF. Required (not
    # defaulted) so callers are always explicit about it -- lets `Signal._derive_scope`
    # and underlying-grouping logic in risk/backtest stay generic across asset classes.
    underlying: str = Field(min_length=1)
    expiry: date | None = None
    lot_size: int = Field(default=1, gt=0)


class OptionContract(Instrument):
    """A single options contract on an index underlying."""

    asset_class: ClassVar[AssetClass] = AssetClass.OPTION

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


class EquityInstrument(Instrument):
    """A cash equity (stock)."""

    asset_class: ClassVar[AssetClass] = AssetClass.EQUITY

    isin: str | None = None


class ETFInstrument(Instrument):
    """An exchange-traded fund, traded like a cash equity."""

    asset_class: ClassVar[AssetClass] = AssetClass.ETF

    isin: str | None = None


class FutureContract(Instrument):
    """A futures contract on an index or stock underlying."""

    asset_class: ClassVar[AssetClass] = AssetClass.FUTURES

    expiry: date
    lot_size: int = Field(gt=0)


class CommodityContract(Instrument):
    """A futures contract on a commodity underlying (crude oil, gold, silver, ...),
    traded on MCX. Same shape as `FutureContract` -- kept as a distinct asset class
    (not reused as FUTURES) because commodity margin/lot conventions differ from
    index/stock futures and the domain already reserves `AssetClass.COMMODITY`
    for that distinction."""

    asset_class: ClassVar[AssetClass] = AssetClass.COMMODITY

    expiry: date
    lot_size: int = Field(gt=0)
