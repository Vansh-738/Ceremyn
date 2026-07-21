"""Expiry-day theta harvest: short ATM straddle on the expiry day itself.

Enters a short ATM straddle in a fixed intraday window on DTE-0 and exits by
time or premium threshold — never holds into the close/settlement.
Requires intraday chain snapshots (paper/live, or intraday backtest data).
"""

from datetime import time

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ceremyn.domain import OptionType, Side, Signal, SignalAction, SignalLeg
from ceremyn.strategies.base import Strategy, StrategyContext
from ceremyn.strategies.common import (
    exit_legs,
    find_atm,
    mark_price,
    net_close_cost,
    net_entry_credit,
    premium_exit_reason,
)
from ceremyn.strategies.registry import register


class ExpiryDayThetaParams(BaseModel):
    model_config = ConfigDict(frozen=True)

    lots: int = Field(default=1, gt=0)
    entry_after: time = time(10, 0)  # IST
    exit_by: time = time(14, 30)  # IST — always flat before the close
    profit_target_pct: float = Field(default=60.0, gt=0, le=100)
    stop_loss_pct: float = Field(default=40.0, gt=0)

    @model_validator(mode="after")
    def _window_valid(self) -> "ExpiryDayThetaParams":
        if self.entry_after >= self.exit_by:
            raise ValueError("entry_after must precede exit_by")
        return self


@register("expiry_day_theta")
class ExpiryDayTheta(Strategy[ExpiryDayThetaParams]):
    params_model = ExpiryDayThetaParams

    def on_chain(self, ctx: StrategyContext) -> list[Signal]:
        if ctx.days_to_expiry != 0:
            return []
        if ctx.has_open_position:
            return self._maybe_exit(ctx)
        return self._maybe_enter(ctx)

    def _maybe_enter(self, ctx: StrategyContext) -> list[Signal]:
        p = self.params
        if not (p.entry_after <= ctx.time_ist < p.exit_by):
            return []
        call = find_atm(ctx.chain, OptionType.CALL)
        put = find_atm(ctx.chain, OptionType.PUT)
        if mark_price(call) is None or mark_price(put) is None:
            return []
        assert call is not None and put is not None  # narrowed by the mark check
        return [
            self.emit(
                ctx,
                signal_type=SignalAction.ENTER,
                legs=(
                    SignalLeg(contract=call.contract, side=Side.SELL, lots=p.lots),
                    SignalLeg(contract=put.contract, side=Side.SELL, lots=p.lots),
                ),
                reason=(
                    f"expiry-day short straddle at {ctx.chain.atm_strike} "
                    f"({ctx.time_ist:%H:%M} IST)"
                ),
            )
        ]

    def _maybe_exit(self, ctx: StrategyContext) -> list[Signal]:
        p = self.params
        reason: str | None = None
        if ctx.time_ist >= p.exit_by:
            reason = f"time exit: {ctx.time_ist:%H:%M} >= {p.exit_by:%H:%M} IST"
        else:
            close_cost = net_close_cost(ctx.positions, ctx.chain)
            if close_cost is not None:
                reason = premium_exit_reason(
                    net_entry_credit(ctx.positions),
                    close_cost,
                    p.profit_target_pct,
                    p.stop_loss_pct,
                )
        if reason is None:
            return []
        return [
            self.emit(
                ctx,
                signal_type=SignalAction.EXIT,
                legs=exit_legs(ctx.positions),
                reason=reason,
            )
        ]
