"""Iron condor: a short strangle protected by long wings.

Same volatility-rich entry logic as the strangle, plus long call/put wings at a
lower delta capping the tail risk. Defined-risk premium selling.
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class IronCondorParams(BaseModel):
    model_config = ConfigDict(frozen=True)

    short_delta: float = Field(default=0.20, gt=0, lt=0.5)
    wing_delta: float = Field(default=0.10, gt=0, lt=0.5)
    lots: int = Field(default=1, gt=0)
    min_iv_rank: float = Field(default=50.0, ge=0, le=100)
    entry_dte_min: int = Field(default=3, ge=0)
    entry_dte_max: int = Field(default=20, ge=0)
    profit_target_pct: float = Field(default=50.0, gt=0, le=100)
    stop_loss_pct: float = Field(default=100.0, gt=0)
    exit_dte: int = Field(default=1, ge=0)

    @model_validator(mode="after")
    def _wings_further_out(self) -> "IronCondorParams":
        if self.wing_delta >= self.short_delta:
            raise ValueError("wing_delta must be below short_delta (wings further OTM)")
        return self


@register("iron_condor")
class IronCondor(Strategy[IronCondorParams]):
    params_model = IronCondorParams

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
        short_call = find_by_delta(ctx.chain, OptionType.CALL, p.short_delta)
        short_put = find_by_delta(ctx.chain, OptionType.PUT, p.short_delta)
        long_call = find_by_delta(ctx.chain, OptionType.CALL, p.wing_delta)
        long_put = find_by_delta(ctx.chain, OptionType.PUT, p.wing_delta)
        if short_call is None or short_put is None or long_call is None or long_put is None:
            return []
        # Structural sanity: shorts straddle spot, wings strictly beyond shorts.
        if not (short_put.contract.strike < ctx.chain.spot < short_call.contract.strike):
            return []
        if not (
            long_call.contract.strike > short_call.contract.strike
            and long_put.contract.strike < short_put.contract.strike
        ):
            return []
        return [
            self.emit(
                ctx,
                signal_type=SignalAction.ENTER,
                legs=(
                    SignalLeg(contract=short_call.contract, side=Side.SELL, lots=p.lots),
                    SignalLeg(contract=short_put.contract, side=Side.SELL, lots=p.lots),
                    SignalLeg(contract=long_call.contract, side=Side.BUY, lots=p.lots),
                    SignalLeg(contract=long_put.contract, side=Side.BUY, lots=p.lots),
                ),
                reason=(
                    f"IV rank {ctx.iv_rank:.0f} >= {p.min_iv_rank:.0f}, DTE "
                    f"{ctx.days_to_expiry}, condor {p.short_delta:.2f}Δ/{p.wing_delta:.2f}Δ"
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
