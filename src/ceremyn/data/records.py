"""Data-transfer records used between providers, repositories, and services."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class EodOptionRecord(BaseModel):
    """One option contract's end-of-day row (bhavcopy granularity)."""

    model_config = ConfigDict(frozen=True)

    trade_date: date
    underlying: str = Field(min_length=1)
    expiry: date
    strike: Decimal = Field(gt=0)
    option_type: str = Field(pattern=r"^(CE|PE)$")
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    close: Decimal | None = None
    settle: Decimal | None = None
    volume: int = Field(default=0, ge=0)
    open_interest: int = Field(default=0, ge=0)
    oi_change: int = 0
    underlying_close: Decimal | None = None
    # NSE revises this periodically per SEBI's lot-size framework -- it is NOT a
    # constant across a multi-year backtest window (NIFTY alone was 25, then 75,
    # then 65 across 2024-2026). Read per-row from bhavcopy's own `NewBrdLotQty`
    # column rather than hardcoded, or historical P&L/margin figures silently use
    # the wrong contract size for whichever months don't match today's value.
    lot_size: int = Field(gt=0)


class EodFutureRecord(BaseModel):
    """One future contract's end-of-day row (bhavcopy granularity)."""

    model_config = ConfigDict(frozen=True)

    trade_date: date
    underlying: str = Field(min_length=1)
    expiry: date
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    close: Decimal | None = None
    settle: Decimal | None = None
    volume: int = Field(default=0, ge=0)
    open_interest: int = Field(default=0, ge=0)
    oi_change: int = 0
    underlying_close: Decimal | None = None
    # Same NSE per-underlying/periodic-revision caveat as `EodOptionRecord.lot_size`.
    lot_size: int = Field(gt=0)


class EodEquityRecord(BaseModel):
    """One cash-equity's end-of-day row (bhavcopy granularity, `SctySrs == "EQ"`).

    No expiry/strike/lot-size concept -- a plain equity settles T+1 in whole shares.
    """

    model_config = ConfigDict(frozen=True)

    trade_date: date
    tradingsymbol: str = Field(min_length=1)
    isin: str | None = None
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    close: Decimal | None = None
    volume: int = Field(default=0, ge=0)
