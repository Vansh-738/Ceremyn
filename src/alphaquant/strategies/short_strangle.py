"""Short strangle: sell an OTM call and an OTM put when volatility is rich.

Entry: no open position, IV rank above threshold, days-to-expiry inside the
entry window, and both legs findable at the target delta.
Exit: premium profit target, stop loss, or expiry proximity.
"""

from pydantic import BaseModel, ConfigDict, Field

from alphaquant.domain import OptionType, Side, Signal, SignalAction, SignalLeg
from alphaquant.strategies.base import Strategy, StrategyContext
from alphaquant.strategies.common import (
    exit_legs,
    find_by_delta,
    net_close_cost,
    net_entry_credit,
    premium_exit_reason,
)
from alphaquant.strategies.registry import register


class ShortStrangleParams(BaseModel):
    model_config = ConfigDict(frozen=True)

    target_delta: float = Field(default=0.20, gt=0, lt=0.5)
    lots: int = Field(default=1, gt=0)
    min_iv_rank: float = Field(default=50.0, ge=0, le=100)
    entry_dte_min: int = Field(default=3, ge=0)
    entry_dte_max: int = Field(default=15, ge=0)
    profit_target_pct: float = Field(default=50.0, gt=0, le=100)
    stop_loss_pct: float = Field(default=100.0, gt=0)
    exit_dte: int = Field(default=1, ge=0)


@register("short_strangle")
class ShortStrangle(Strategy[ShortStrangleParams]):
    params_model = ShortStrangleParams

    def on_chain(self, ctx: StrategyContext) -> list[Signal]:
        if ctx.has_open_position:
            return self._maybe_exit(ctx)
        return self._maybe_enter(ctx)

    def _maybe_enter(self, ctx: StrategyContext) -> list[Signal]:
        p = self.params
        if ctx.iv_rank is None or ctx.iv_rank < p.min_iv_rank:
            return []
        if not (p.entry_dte_min <= ctx.days_to_expiry <= p.entry_dte_max):
            return []
        call = find_by_delta(ctx.chain, OptionType.CALL, p.target_delta)
        put = find_by_delta(ctx.chain, OptionType.PUT, p.target_delta)
        if call is None or put is None:
            return []
        if not (put.contract.strike < ctx.chain.spot < call.contract.strike):
            return []  # degenerate chain (e.g. too few strikes with greeks)
        return [
            self.emit(
                ctx,
                signal_type=SignalAction.ENTER,
                legs=(
                    SignalLeg(contract=call.contract, side=Side.SELL, lots=p.lots),
                    SignalLeg(contract=put.contract, side=Side.SELL, lots=p.lots),
                ),
                reason=(
                    f"IV rank {ctx.iv_rank:.0f} >= {p.min_iv_rank:.0f}, "
                    f"DTE {ctx.days_to_expiry}, short {p.target_delta:.2f}-delta strangle"
                ),
            )
        ]

    def _maybe_exit(self, ctx: StrategyContext) -> list[Signal]:
        p = self.params
        reason: str | None = None
        if ctx.days_to_expiry <= p.exit_dte:
            reason = f"expiry proximity: DTE {ctx.days_to_expiry} <= {p.exit_dte}"
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
