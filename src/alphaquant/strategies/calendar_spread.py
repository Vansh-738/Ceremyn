"""Calendar spread: sell a near-dated ATM option, buy a matching far-dated ATM option.

Profits from the near leg's faster time decay relative to the far leg — a net-debit trade,
structurally different from every other strategy in this package because it needs TWO
expiries' chains at once (see `StrategyContext.other_expiries`). Backtest/research only this
milestone: paper/live never populate `other_expiries` today (the live/paper data pipeline
tracks one expiry per underlying), so this strategy safely never enters in those modes rather
than acting on an incomplete chain — consistent with the platform never fabricating data.

`Signal` requires every leg within it to share one expiry (`domain/signals.py::
_derive_scope`) — a deliberate, foundational domain invariant this milestone does not relax.
So a calendar spread's two legs can't live in one `Signal`; instead each entry/exit emits a
*pair* of single-leg signals, one per expiry, linked by a shared `correlation_id` so the
journal/audit trail still reads as one calendar-spread decision. The consequence: the risk
engine evaluates each leg's signal independently rather than as one atomic 2-leg decision —
unlike the 3-and-4-leg strategies in this package, it's possible for one leg to be approved and
the other rejected, leaving a single naked leg. This is an explicit, documented limitation of
representing a cross-expiry structure within the current domain model, not an oversight.

A multi-expiry backtest re-invokes `on_chain` once per tracked expiry's `OptionChainEvent`, so
this strategy explicitly checks whether `ctx.chain` is the leg it should be acting on (the near
leg pre-entry, or the position's actual near leg post-entry) before doing anything, and no-ops
otherwise — avoiding duplicate or conflicting signals from the "other" invocation.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from alphaquant.domain import (
    OptionChainSnapshot,
    OptionContract,
    OptionType,
    Position,
    Side,
    Signal,
    SignalAction,
    SignalLeg,
)
from alphaquant.strategies.base import Strategy, StrategyContext
from alphaquant.strategies.common import (
    exit_legs,
    exit_reason_from_pnl_pct,
    find_atm,
    mark_price,
    net_entry_credit,
    net_pnl_pct,
)
from alphaquant.strategies.registry import register


class CalendarSpreadParams(BaseModel):
    model_config = ConfigDict(frozen=True)

    option_type: OptionType = OptionType.CALL
    lots: int = Field(default=1, gt=0)
    near_expiry_dte_max: int = Field(default=7, ge=0)
    far_expiry_min_days_out: int = Field(default=20, gt=0)
    profit_target_pct: float = Field(default=30.0, gt=0, le=100)
    stop_loss_pct: float = Field(default=50.0, gt=0)
    exit_dte: int = Field(default=1, ge=0)

    @model_validator(mode="after")
    def _far_further_than_near(self) -> "CalendarSpreadParams":
        if self.far_expiry_min_days_out <= self.near_expiry_dte_max:
            raise ValueError("far_expiry_min_days_out must exceed near_expiry_dte_max")
        return self


def _net_close_cost_across(
    positions: tuple[Position, ...], chains_by_expiry: dict[date, OptionChainSnapshot]
) -> Decimal | None:
    """Like `common.net_close_cost`, but looks each position up in whichever of the known
    chains matches its own expiry — needed because a calendar spread's two legs live in two
    different `OptionChainSnapshot`s, never one."""
    total = Decimal(0)
    for position in positions:
        if position.is_flat:
            continue
        if not isinstance(position.contract, OptionContract):
            return None
        chain = chains_by_expiry.get(position.contract.expiry)
        if chain is None:
            return None
        entry = chain.get(position.contract.strike, position.contract.option_type)
        mark = mark_price(entry)
        if mark is None:
            return None
        total += -mark * position.quantity
    return total


@register("calendar_spread")
class CalendarSpread(Strategy[CalendarSpreadParams]):
    params_model = CalendarSpreadParams

    def on_chain(self, ctx: StrategyContext) -> list[Signal]:
        if ctx.has_open_position:
            near_expiry = self._current_near_expiry(ctx.positions)
            if near_expiry is not None and ctx.chain.expiry != near_expiry:
                return []  # this invocation is for the far leg's chain event; defer
            return self._maybe_exit(ctx)
        if ctx.days_to_expiry > self.params.near_expiry_dte_max:
            return []  # ctx.chain isn't a near-leg candidate
        return self._maybe_enter(ctx)

    @staticmethod
    def _current_near_expiry(positions: tuple[Position, ...]) -> date | None:
        for position in positions:
            if not position.is_flat and position.is_short:
                return position.contract.expiry
        return None

    def _far_chain(self, ctx: StrategyContext) -> OptionChainSnapshot | None:
        p = self.params
        candidates = [
            chain
            for expiry, chain in ctx.other_expiries.items()
            if (expiry - ctx.chain.expiry).days >= p.far_expiry_min_days_out
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda c: c.expiry)

    def _signal(
        self,
        ctx: StrategyContext,
        *,
        signal_type: SignalAction,
        expiry: date,
        underlying: str,
        legs: tuple[SignalLeg, ...],
        reason: str,
        correlation_id: UUID,
    ) -> Signal:
        return Signal(
            strategy_id=self.definition.id,
            strategy_version=self.definition.version,
            signal_type=signal_type,
            created_at=ctx.now,
            market_timestamp=ctx.chain.timestamp,
            underlying=underlying,
            expiry=expiry,
            reason=reason,
            legs=legs,
            correlation_id=correlation_id,
        )

    def _maybe_enter(self, ctx: StrategyContext) -> list[Signal]:
        p = self.params
        far_chain = self._far_chain(ctx)
        if far_chain is None:
            return []  # no far expiry known (always true in paper/live today) -> safe no-op
        near_leg = find_atm(ctx.chain, p.option_type)
        far_leg = far_chain.get(ctx.chain.atm_strike, p.option_type)
        if near_leg is None or far_leg is None:
            return []
        correlation_id = uuid4()
        reason = (
            f"calendar spread at {ctx.chain.atm_strike}: sell {ctx.chain.expiry}, "
            f"buy {far_chain.expiry}"
        )
        return [
            self._signal(
                ctx,
                signal_type=SignalAction.ENTER,
                expiry=ctx.chain.expiry,
                underlying=ctx.chain.underlying,
                legs=(SignalLeg(contract=near_leg.contract, side=Side.SELL, lots=p.lots),),
                reason=reason,
                correlation_id=correlation_id,
            ),
            self._signal(
                ctx,
                signal_type=SignalAction.ENTER,
                expiry=far_chain.expiry,
                underlying=far_chain.underlying,
                legs=(SignalLeg(contract=far_leg.contract, side=Side.BUY, lots=p.lots),),
                reason=reason,
                correlation_id=correlation_id,
            ),
        ]

    def _maybe_exit(self, ctx: StrategyContext) -> list[Signal]:
        p = self.params
        if ctx.days_to_expiry <= p.exit_dte:
            return self._exit_signals(
                ctx, f"near-leg expiry proximity: DTE {ctx.days_to_expiry} <= {p.exit_dte}"
            )
        far_chain = self._far_chain(ctx)
        if far_chain is None:
            return []  # can't price the far leg without its chain; stay in rather than guess
        chains_by_expiry = {ctx.chain.expiry: ctx.chain, far_chain.expiry: far_chain}
        close_cost = _net_close_cost_across(ctx.positions, chains_by_expiry)
        if close_cost is None:
            return []
        pnl_pct = net_pnl_pct(net_entry_credit(ctx.positions), -close_cost)
        reason = exit_reason_from_pnl_pct(pnl_pct, p.profit_target_pct, p.stop_loss_pct)
        if reason is None:
            return []
        return self._exit_signals(ctx, reason)

    def _exit_signals(self, ctx: StrategyContext, reason: str) -> list[Signal]:
        by_expiry: dict[date, list[Position]] = {}
        for position in ctx.positions:
            if position.is_flat or not isinstance(position.contract, OptionContract):
                continue
            by_expiry.setdefault(position.contract.expiry, []).append(position)
        correlation_id = uuid4()
        return [
            self._signal(
                ctx,
                signal_type=SignalAction.EXIT,
                expiry=expiry,
                underlying=ctx.chain.underlying,
                legs=exit_legs(tuple(positions)),
                reason=reason,
                correlation_id=correlation_id,
            )
            for expiry, positions in by_expiry.items()
        ]
