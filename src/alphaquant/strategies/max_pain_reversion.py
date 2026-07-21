"""Max-pain reversion: buy toward the strike where option writers' payout is minimal.

Max-pain theory: as expiry approaches, the underlying tends to drift toward the
strike that minimises option writers' total payout (`max_pain` in
`data.services.chain_analytics`, computed purely from the chain's open interest).
When spot has moved far away from that strike, this strategy buys the option that
profits from the drift back: spot well ABOVE max pain -> buy a put; spot well
BELOW -> buy a call.

Like `long_contrarian`, this is a single BUY leg (debit-only, no margin -- just
premium paid) and a pure function of the observed chain snapshot: no persisted
history, no I/O, so backtest/paper/live behave identically.

Entry: no open position, DTE inside the window, |spot - max_pain| / spot past the
distance threshold, and a contract findable at the target delta on the implied
side. Exit: premium profit target, stop loss, or expiry proximity.
"""

from pydantic import BaseModel, ConfigDict, Field

from alphaquant.data.services.chain_analytics import max_pain
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


class MaxPainReversionParams(BaseModel):
    model_config = ConfigDict(frozen=True)

    # Minimum |spot - max_pain| as a fraction of spot before the pull is considered
    # strong enough to trade (1% of NIFTY ~ 240 points).
    min_distance_pct: float = Field(default=0.01, gt=0, lt=0.2)
    target_delta: float = Field(default=0.35, gt=0, lt=0.5)
    lots: int = Field(default=1, gt=0)
    entry_dte_min: int = Field(default=1, ge=0)
    entry_dte_max: int = Field(default=7, ge=0)
    profit_target_pct: float = Field(default=40.0, gt=0, le=100)
    stop_loss_pct: float = Field(default=40.0, gt=0)
    exit_dte: int = Field(default=0, ge=0)


@register("max_pain_reversion")
class MaxPainReversion(Strategy[MaxPainReversionParams]):
    params_model = MaxPainReversionParams

    def on_chain(self, ctx: StrategyContext) -> list[Signal]:
        if ctx.has_open_position:
            return self._maybe_exit(ctx)
        return self._maybe_enter(ctx)

    def _maybe_enter(self, ctx: StrategyContext) -> list[Signal]:
        p = self.params
        if not (p.entry_dte_min <= ctx.days_to_expiry <= p.entry_dte_max):
            return []
        pain = max_pain(ctx.chain)
        distance = float((ctx.chain.spot - pain) / ctx.chain.spot)
        if abs(distance) < p.min_distance_pct:
            return []
        # Spot above max pain -> expected drift down -> buy a put; below -> buy a call.
        option_type = OptionType.PUT if distance > 0 else OptionType.CALL
        entry = find_by_delta(ctx.chain, option_type, p.target_delta)
        if entry is None:
            return []
        return [
            self.emit(
                ctx,
                signal_type=SignalAction.ENTER,
                legs=(SignalLeg(contract=entry.contract, side=Side.BUY, lots=p.lots),),
                reason=(
                    f"spot {ctx.chain.spot} vs max pain {pain} ({distance:+.2%}), "
                    f"long {p.target_delta:.2f}-delta {option_type.value} "
                    f"(no margin: debit-only)"
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
