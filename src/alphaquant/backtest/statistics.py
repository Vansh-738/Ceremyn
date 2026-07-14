"""Backtest statistics models."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from alphaquant.domain.market_data import _require_aware


class EquityPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    cash: Decimal
    equity: Decimal
    drawdown: Decimal = Field(ge=0)

    _aware = field_validator("timestamp")(_require_aware)


class ReturnBucket(BaseModel):
    model_config = ConfigDict(frozen=True)

    period: str = Field(min_length=1)
    return_pct: float


class BacktestStatistics(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_return: float = 0.0
    cagr: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    calmar: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    maximum_drawdown: float = 0.0
    average_win: float = 0.0
    average_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    win_rate: float = 0.0
    loss_rate: float = 0.0
    average_holding_time_hours: float = 0.0
    monthly_returns: tuple[ReturnBucket, ...] = ()
    yearly_returns: tuple[ReturnBucket, ...] = ()
