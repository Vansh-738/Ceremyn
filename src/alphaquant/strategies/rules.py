"""Declarative entry/exit/adjustment configuration and their pure evaluators.

Shared by the multi-leg engine (`multi_leg.py`); every field has a conservative default so a
strategy only needs to override what it actually wants to configure.
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from alphaquant.domain import OptionContract, Position, Side, SignalLeg
from alphaquant.strategies.base import StrategyContext
from alphaquant.strategies.common import (
    exit_reason_from_pnl_pct,
    find_by_delta,
    net_close_cost,
    net_entry_credit,
    net_pnl_pct,
)


class EntryFilter(BaseModel):
    model_config = ConfigDict(frozen=True)

    min_iv_rank: float | None = Field(default=None, ge=0, le=100)
    entry_dte_min: int = Field(default=0, ge=0)
    entry_dte_max: int = Field(default=45, ge=0)

    @model_validator(mode="after")
    def _window_valid(self) -> "EntryFilter":
        if self.entry_dte_min > self.entry_dte_max:
            raise ValueError("entry_dte_min must be <= entry_dte_max")
        return self


class ExitRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    profit_target_pct: float = Field(default=50.0, gt=0, le=100)
    stop_loss_pct: float = Field(default=100.0, gt=0)
    exit_dte: int = Field(default=1, ge=0)


class AdjustmentRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    breach_delta: float = Field(default=0.35, gt=0, lt=1.0)
    roll_to_delta: float = Field(default=0.20, gt=0, lt=0.5)

    @model_validator(mode="after")
    def _roll_target_is_tighter(self) -> "AdjustmentRule":
        if self.roll_to_delta >= self.breach_delta:
            raise ValueError("roll_to_delta must be below breach_delta (rolling further OTM)")
        return self


def entry_allowed(ctx: StrategyContext, filt: EntryFilter) -> bool:
    if filt.min_iv_rank is not None and (ctx.iv_rank is None or ctx.iv_rank < filt.min_iv_rank):
        return False
    return filt.entry_dte_min <= ctx.days_to_expiry <= filt.entry_dte_max


def evaluate_exit(
    ctx: StrategyContext, positions: tuple[Position, ...], rule: ExitRule
) -> str | None:
    """Expiry-proximity exit takes priority; otherwise a P&L-based exit, correct for both
    net-credit and net-debit entries (see `common.net_pnl_pct`)."""
    if ctx.days_to_expiry <= rule.exit_dte:
        return f"expiry proximity: DTE {ctx.days_to_expiry} <= {rule.exit_dte}"
    close_cost = net_close_cost(positions, ctx.chain)
    if close_cost is None:
        return None
    pnl_pct = net_pnl_pct(net_entry_credit(positions), -close_cost)
    return exit_reason_from_pnl_pct(pnl_pct, rule.profit_target_pct, rule.stop_loss_pct)


def evaluate_adjustment(
    ctx: StrategyContext,
    positions: tuple[Position, ...],
    rule: AdjustmentRule,
) -> tuple[SignalLeg, ...] | None:
    """Roll the first short leg whose |delta| has breached `rule.breach_delta` further OTM, or
    None if no leg needs adjusting (or adjustments are disabled for this strategy)."""
    if not rule.enabled:
        return None
    for position in positions:
        if not position.is_short:
            continue
        if not isinstance(position.contract, OptionContract):
            # Adjustment rolls are an options-chain concept; nothing to roll for a
            # non-option position (no strategy produces one yet).
            continue
        if position.contract.expiry != ctx.chain.expiry:
            # `chain.get()` matches by strike + option_type only, not expiry -- a
            # position held across an expiry-listing change (e.g. the exchange
            # shifts which weekly date a series trades on) would otherwise silently
            # resolve to a *different* expiry's contract at the same strike, and
            # rolling it would build a signal mixing two expiries (rejected by
            # `Signal`'s own validation). Nothing else can currently re-evaluate
            # this leg either, so it's left alone rather than adjusted against data
            # that doesn't actually describe it.
            continue
        entry = ctx.chain.get(position.contract.strike, position.contract.option_type)
        if entry is None or entry.greeks is None:
            continue
        if abs(entry.greeks.delta) < rule.breach_delta:
            continue
        replacement = find_by_delta(ctx.chain, position.contract.option_type, rule.roll_to_delta)
        if replacement is None:  # pragma: no cover - unreachable: `entry` (found above, with
            # greeks) is itself always a candidate for this same option_type's delta search,
            # so find_by_delta can never return None here. Kept for mypy's None-narrowing.
            continue
        lots = abs(position.quantity) // position.contract.lot_size
        return (
            SignalLeg(contract=position.contract, side=Side.BUY, lots=lots),
            SignalLeg(contract=replacement.contract, side=Side.SELL, lots=lots),
        )
    return None
