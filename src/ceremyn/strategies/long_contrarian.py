"""Long contrarian: buy against the crowd on extreme options positioning.

A directional bet, not a volatility bet like `long_strangle` -- single BUY leg
(a long call or long put, never both), so it needs no margin the same way
`long_strangle` doesn't. Heuristic: a very high put-call OI ratio (the crowd
heavily put-hedged/bearish) is read as contrarian bullish; a very low ratio
(the crowd heavily call-buying/bullish) is read as contrarian bearish. This is
a real, if contested, options-positioning signal, and it's entirely computable
from a single chain snapshot (`OptionChainSnapshot.pcr`) -- no persisted
history needed, so it stays a pure function of `ctx` like every strategy here.

Entry: no open position, DTE inside the entry window, PCR past one of the two
thresholds, and a contract findable at the target delta on the implied side.
Exit: premium profit target, stop loss, or expiry proximity.
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ceremyn.domain import OptionType, Side, Signal, SignalAction, SignalLeg
from ceremyn.strategies.base import Strategy, StrategyContext
from ceremyn.strategies.common import (
    exit_legs,
    exit_reason_from_pnl_pct,
    find_by_delta,
    net_close_cost,
    net_entry_credit,
    net_pnl_pct,
)
from ceremyn.strategies.registry import register


class LongContrarianParams(BaseModel):
    model_config = ConfigDict(frozen=True)

    pcr_bullish_threshold: float = Field(default=1.3, gt=0)
    pcr_bearish_threshold: float = Field(default=0.7, gt=0)
    target_delta: float = Field(default=0.35, gt=0, lt=0.5)
    lots: int = Field(default=1, gt=0)
    entry_dte_min: int = Field(default=3, ge=0)
    entry_dte_max: int = Field(default=15, ge=0)
    profit_target_pct: float = Field(default=40.0, gt=0, le=100)
    stop_loss_pct: float = Field(default=40.0, gt=0)
    exit_dte: int = Field(default=1, ge=0)

    @model_validator(mode="after")
    def _sane_thresholds(self) -> "LongContrarianParams":
        if self.pcr_bearish_threshold >= self.pcr_bullish_threshold:
            raise ValueError("pcr_bearish_threshold must be below pcr_bullish_threshold")
        return self


@register("long_contrarian")
class LongContrarian(Strategy[LongContrarianParams]):
    params_model = LongContrarianParams

    def on_chain(self, ctx: StrategyContext) -> list[Signal]:
        if ctx.has_open_position:
            return self._maybe_exit(ctx)
        return self._maybe_enter(ctx)

    def _maybe_enter(self, ctx: StrategyContext) -> list[Signal]:
        p = self.params
        if not (p.entry_dte_min <= ctx.days_to_expiry <= p.entry_dte_max):
            return []
        pcr = ctx.chain.pcr
        if pcr is None:
            return []
        if pcr >= p.pcr_bullish_threshold:
            option_type = OptionType.CALL
        elif pcr <= p.pcr_bearish_threshold:
            option_type = OptionType.PUT
        else:
            return []
        entry = find_by_delta(ctx.chain, option_type, p.target_delta)
        if entry is None:
            return []
        return [
            self.emit(
                ctx,
                signal_type=SignalAction.ENTER,
                legs=(SignalLeg(contract=entry.contract, side=Side.BUY, lots=p.lots),),
                reason=(
                    f"PCR {pcr:.2f} contrarian {option_type.value}, "
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
