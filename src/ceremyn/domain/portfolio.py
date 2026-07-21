"""Portfolio state exposed to strategies and the future risk engine."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from ceremyn.domain.enums import KillSwitchState
from ceremyn.domain.orders import Order
from ceremyn.domain.positions import Position


class PortfolioGreeks(BaseModel):
    model_config = ConfigDict(frozen=True)

    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    rho: float = 0.0


class PortfolioExposure(BaseModel):
    model_config = ConfigDict(frozen=True)

    gross_notional: Decimal = Field(default=Decimal("0"), ge=0)
    net_notional: Decimal = Decimal("0")
    short_option_units: int = 0
    net_option_units: int = 0
    by_underlying: dict[str, Decimal] = Field(default_factory=dict)


class PortfolioSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    positions: tuple[Position, ...] = ()
    pending_orders: tuple[Order, ...] = ()
    buying_power: Decimal = Decimal("0")
    margin_used: Decimal = Field(default=Decimal("0"), ge=0)
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    daily_pnl: Decimal = Decimal("0")
    portfolio_greeks: PortfolioGreeks = Field(default_factory=PortfolioGreeks)
    exposure: PortfolioExposure = Field(default_factory=PortfolioExposure)
    drawdown: Decimal = Field(default=Decimal("0"), ge=0)
    kill_switch_state: KillSwitchState = KillSwitchState.DISARMED
