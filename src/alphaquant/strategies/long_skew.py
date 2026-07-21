"""Long skew: buy against an extreme put-call IV skew.

A third directional signal source, distinct from `long_contrarian` (open-interest
positioning) and `max_pain_reversion` (max-pain gravitational pull): index options
normally price OTM puts richer than equidistant OTM calls (crash-hedging demand).
When that skew becomes unusually stretched in either direction, this reads it as
overdone and buys against it -- steep put skew (everyone paying up for downside
protection) is read as contrarian bullish; the rarer inverted call skew (chasing
upside) is read as contrarian bearish.

Single BUY leg (debit-only, no margin -- just the premium paid), computed entirely
from one chain snapshot's own greeks (`ChainEntry.greeks.iv`), so it needs no
persisted history and stays a pure function of `ctx` like every strategy here.

Entry: no open position, DTE inside the entry window, put/call IV ratio (both
sampled at the same target delta) past one of the two thresholds, and a contract
findable at that delta on the implied side. Exit: premium profit target, stop
loss, or expiry proximity.
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class LongSkewParams(BaseModel):
    model_config = ConfigDict(frozen=True)

    target_delta: float = Field(default=0.25, gt=0, lt=0.5)
    skew_bullish_threshold: float = Field(default=1.15, gt=1.0)
    skew_bearish_threshold: float = Field(default=0.87, gt=0, lt=1.0)
    lots: int = Field(default=1, gt=0)
    entry_dte_min: int = Field(default=3, ge=0)
    entry_dte_max: int = Field(default=15, ge=0)
    profit_target_pct: float = Field(default=40.0, gt=0, le=100)
    stop_loss_pct: float = Field(default=40.0, gt=0)
    exit_dte: int = Field(default=1, ge=0)

    @model_validator(mode="after")
    def _sane_thresholds(self) -> "LongSkewParams":
        if self.skew_bearish_threshold >= self.skew_bullish_threshold:
            raise ValueError("skew_bearish_threshold must be below skew_bullish_threshold")
        return self


@register("long_skew")
class LongSkew(Strategy[LongSkewParams]):
    params_model = LongSkewParams

    def on_chain(self, ctx: StrategyContext) -> list[Signal]:
        if ctx.has_open_position:
            return self._maybe_exit(ctx)
        return self._maybe_enter(ctx)

    def _maybe_enter(self, ctx: StrategyContext) -> list[Signal]:
        p = self.params
        if not (p.entry_dte_min <= ctx.days_to_expiry <= p.entry_dte_max):
            return []
        call = find_by_delta(ctx.chain, OptionType.CALL, p.target_delta)
        put = find_by_delta(ctx.chain, OptionType.PUT, p.target_delta)
        if call is None or put is None or call.greeks is None or put.greeks is None:
            return []
        call_iv, put_iv = call.greeks.iv, put.greeks.iv
        if call_iv is None or put_iv is None or call_iv <= 0:
            return []
        skew_ratio = put_iv / call_iv
        if skew_ratio >= p.skew_bullish_threshold:
            entry, option_type = call, OptionType.CALL
        elif skew_ratio <= p.skew_bearish_threshold:
            entry, option_type = put, OptionType.PUT
        else:
            return []
        return [
            self.emit(
                ctx,
                signal_type=SignalAction.ENTER,
                legs=(SignalLeg(contract=entry.contract, side=Side.BUY, lots=p.lots),),
                reason=(
                    f"put/call IV skew {skew_ratio:.2f}, long {option_type.value} "
                    f"{p.target_delta:.2f} delta (no margin: debit-only)"
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
