"""Configurable NSE delivery charges, checked against Zerodha on 2026-10-20."""

from decimal import Decimal

from pydantic import BaseModel, Field


class EquityCostSettings(BaseModel):
    brokerage: Decimal = Field(default=Decimal("0"), ge=0)
    stt_rate: Decimal = Field(default=Decimal("0.001"), ge=0)
    exchange_rate: Decimal = Field(default=Decimal("0.0000307"), ge=0)
    sebi_rate: Decimal = Field(default=Decimal("0.000001"), ge=0)
    stamp_buy_rate: Decimal = Field(default=Decimal("0.00015"), ge=0)
    gst_rate: Decimal = Field(default=Decimal("0.18"), ge=0)
    dp_sell_charge: Decimal = Field(default=Decimal("15.34"), ge=0)
