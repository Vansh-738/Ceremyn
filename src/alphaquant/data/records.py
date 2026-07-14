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
