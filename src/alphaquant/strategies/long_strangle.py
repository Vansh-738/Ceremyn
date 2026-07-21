"""Long strangle: buy an OTM call and an OTM put -- a debit-only complement to
`short_strangle.py`. Every other registered strategy sells at least one leg, which
consumes margin; buying options only costs the premium paid, so this is the one
strategy that fits an account too small to clear a short leg's margin requirement.

Entry: no open position, days-to-expiry inside the entry window, both legs
findable at the target delta, and (optionally) IV rank not already too rich to
buy. Exit: premium profit target, stop loss, or expiry proximity.
"""

from pydantic import BaseModel, ConfigDict, Field

from alphaquant.domain import OptionType, Side, Signal, SignalAction, SignalLeg
from alphaquant.strategies.base import Strategy, StrategyContext
from alphaquant.strategies.common import (
    exit_legs,
    exit_reason_from_pnl_pct,
    find_by_delta,
    net_close_cost,
    net_entry_credit,
    net_pnl_pct,
)
from alphaquant.strategies.registry import register


class LongStrangleParams(BaseModel):
    model_config = ConfigDict(frozen=True)

    target_delta: float = Field(default=0.20, gt=0, lt=0.5)
    lots: int = Field(default=1, gt=0)
    # Unlike `short_strangle`'s `min_iv_rank` (only sell when premium is rich), this
    # caps how expensive premium may be before buying it; `None` (default) applies no
    # IV gate at all, since paying a fair, non-extreme price for premium doesn't need
    # a rank history the way selling it profitably does.
    max_iv_rank: float | None = Field(default=None, ge=0, le=100)
    entry_dte_min: int = Field(default=3, ge=0)
    entry_dte_max: int = Field(default=15, ge=0)
    profit_target_pct: float = Field(default=50.0, gt=0, le=100)
    stop_loss_pct: float = Field(default=50.0, gt=0)
    exit_dte: int = Field(default=1, ge=0)


@register("long_strangle")
class LongStrangle(Strategy[LongStrangleParams]):
    params_model = LongStrangleParams

    def on_chain(self, ctx: StrategyContext) -> list[Signal]:
        if ctx.has_open_position:
            return self._maybe_exit(ctx)
        return self._maybe_enter(ctx)

    def _maybe_enter(self, ctx: StrategyContext) -> list[Signal]:
        p = self.params
        if p.max_iv_rank is not None and ctx.iv_rank is not None and ctx.iv_rank > p.max_iv_rank:
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
                    SignalLeg(contract=call.contract, side=Side.BUY, lots=p.lots),
                    SignalLeg(contract=put.contract, side=Side.BUY, lots=p.lots),
                ),
                reason=(
                    f"DTE {ctx.days_to_expiry}, long {p.target_delta:.2f}-delta strangle"
                    f" (no margin: debit-only)"
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
                pnl_pct = net_pnl_pct(net_entry_credit(ctx.positions), -close_cost)
                reason = exit_reason_from_pnl_pct(pnl_pct, p.profit_target_pct, p.stop_loss_pct)
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
