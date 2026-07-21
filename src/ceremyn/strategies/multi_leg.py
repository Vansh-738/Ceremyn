"""Shared entry/exit/adjustment driver for declarative multi-leg strategies.

Concrete strategies (iron_fly.py, short_straddle.py, vertical_spread.py, ...) declare a flat,
grid-search-friendly params model (matching the existing IronCondorParams/ShortStrangleParams
shape, so the Research Lab optimizer can sweep every field individually) that computes
`legs`/`entry`/`exit_rule`/`adjustment` on demand, and delegate `on_chain` to `drive()`. This is
a driver function, not a required base class — a strategy whose legs don't fit this shape (e.g.
calendar_spread.py's cross-expiry legs) simply doesn't use it.
"""

from typing import Any, Protocol

from ceremyn.domain import Signal, SignalAction
from ceremyn.strategies.base import Strategy, StrategyContext
from ceremyn.strategies.common import exit_legs
from ceremyn.strategies.legs import LegSpec, resolve_legs
from ceremyn.strategies.rules import (
    AdjustmentRule,
    EntryFilter,
    ExitRule,
    entry_allowed,
    evaluate_adjustment,
    evaluate_exit,
)


class MultiLegParams(Protocol):
    lots: int

    @property
    def legs(self) -> tuple[LegSpec, ...]: ...

    @property
    def entry(self) -> EntryFilter: ...

    @property
    def exit_rule(self) -> ExitRule: ...

    @property
    def adjustment(self) -> AdjustmentRule: ...


def drive(strategy: Strategy[Any], ctx: StrategyContext, params: MultiLegParams) -> list[Signal]:
    """The common on_chain shape: enter when flat, exit or adjust when a position is open."""
    if ctx.has_open_position:
        return _exit_or_adjust(strategy, ctx, params)
    return _maybe_enter(strategy, ctx, params)


def _maybe_enter(
    strategy: Strategy[Any], ctx: StrategyContext, params: MultiLegParams
) -> list[Signal]:
    if not entry_allowed(ctx, params.entry):
        return []
    legs = resolve_legs(ctx.chain, params.legs, params.lots)
    if legs is None:
        return []
    reason = f"{len(params.legs)}-leg entry, DTE {ctx.days_to_expiry}"
    if ctx.iv_rank is not None:
        reason += f", IV rank {ctx.iv_rank:.0f}"
    return [strategy.emit(ctx, signal_type=SignalAction.ENTER, legs=legs, reason=reason)]


def _exit_or_adjust(
    strategy: Strategy[Any], ctx: StrategyContext, params: MultiLegParams
) -> list[Signal]:
    reason = evaluate_exit(ctx, ctx.positions, params.exit_rule)
    if reason is not None:
        return [
            strategy.emit(
                ctx, signal_type=SignalAction.EXIT, legs=exit_legs(ctx.positions), reason=reason
            )
        ]
    adjustment_legs = evaluate_adjustment(ctx, ctx.positions, params.adjustment)
    if adjustment_legs is not None:
        return [
            strategy.emit(
                ctx,
                signal_type=SignalAction.ADJUST,
                legs=adjustment_legs,
                reason="adjustment: rolled a breached short leg further OTM",
            )
        ]
    return []
