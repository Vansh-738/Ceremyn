from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from alphaquant.domain import OptionType, Position, Side
from alphaquant.strategies.base import StrategyContext
from alphaquant.strategies.rules import (
    AdjustmentRule,
    EntryFilter,
    ExitRule,
    entry_allowed,
    evaluate_adjustment,
    evaluate_exit,
)
from tests.unit.domain.conftest import make_contract
from tests.unit.strategies.conftest import EXPIRY, NOW, enriched_chain, ist, marked_chain


def _ctx(**overrides: object) -> StrategyContext:
    defaults: dict[str, object] = {"chain": enriched_chain(), "now": NOW}
    defaults.update(overrides)
    return StrategyContext.model_validate(defaults)


class TestEntryFilter:
    def test_rejects_inverted_dte_window(self) -> None:
        with pytest.raises(ValidationError, match="entry_dte_min"):
            EntryFilter(entry_dte_min=10, entry_dte_max=5)


class TestAdjustmentRule:
    def test_rejects_roll_target_not_tighter_than_breach(self) -> None:
        with pytest.raises(ValidationError, match="roll_to_delta"):
            AdjustmentRule(enabled=True, breach_delta=0.20, roll_to_delta=0.30)

    def test_disabled_by_default(self) -> None:
        assert AdjustmentRule().enabled is False


class TestEntryAllowed:
    def test_true_within_iv_and_dte_window(self) -> None:
        ctx = _ctx(iv_rank=80.0)
        filt = EntryFilter(min_iv_rank=50.0, entry_dte_min=0, entry_dte_max=30)
        assert entry_allowed(ctx, filt)

    def test_false_when_iv_rank_missing_and_filter_requires_it(self) -> None:
        ctx = _ctx(iv_rank=None)
        assert not entry_allowed(ctx, EntryFilter(min_iv_rank=50.0))

    def test_false_outside_dte_window(self) -> None:
        ctx = _ctx(iv_rank=80.0)  # DTE 8 by default (NOW vs EXPIRY)
        assert not entry_allowed(ctx, EntryFilter(entry_dte_min=0, entry_dte_max=3))

    def test_no_iv_filter_when_min_iv_rank_is_none(self) -> None:
        ctx = _ctx(iv_rank=None)
        assert entry_allowed(ctx, EntryFilter(min_iv_rank=None))


class TestEvaluateExit:
    def test_expiry_proximity_takes_priority(self) -> None:
        near_expiry = ist(date(2025, 7, 28), 10)  # DTE 1 vs EXPIRY 2025-07-29
        ctx = _ctx(now=near_expiry)
        reason = evaluate_exit(ctx, (), ExitRule(exit_dte=1))
        assert reason is not None
        assert "expiry proximity" in reason

    def test_none_when_marks_missing(self) -> None:
        position = Position(
            contract=make_contract(strike=24000, option_type=OptionType.CALL, expiry=EXPIRY),
            quantity=-75,
            avg_price=Decimal("100"),
        )
        chain = marked_chain({(23000, OptionType.PUT): "10"})  # no matching entry
        ctx = _ctx(chain=chain)
        assert evaluate_exit(ctx, (position,), ExitRule()) is None

    def test_none_when_position_expiry_differs_from_chain_expiry(self) -> None:
        """Same rationale as the adjustment-path regression: `chain.get()` matches
        by strike + option_type only, so a stale-expiry position must be treated
        as unpriceable (None), not silently marked against a different expiry's
        contract at the same strike."""
        position = Position(
            contract=make_contract(
                strike=24000, option_type=OptionType.CALL, expiry=date(2025, 8, 5)
            ),
            quantity=-75,
            avg_price=Decimal("100"),
        )
        chain = marked_chain({(24000, OptionType.CALL): "40"})  # marked_chain's default EXPIRY
        ctx = _ctx(chain=chain)
        assert evaluate_exit(ctx, (position,), ExitRule()) is None

    def test_credit_position_profit_target(self) -> None:
        position = Position(
            contract=make_contract(strike=24000, option_type=OptionType.CALL, expiry=EXPIRY),
            quantity=-75,
            avg_price=Decimal("100"),  # sold for credit 7500
        )
        chain = marked_chain({(24000, OptionType.CALL): "40"})  # close cost 3000 -> 60% profit
        ctx = _ctx(chain=chain)
        reason = evaluate_exit(ctx, (position,), ExitRule(profit_target_pct=50.0))
        assert reason is not None
        assert "profit target" in reason

    def test_credit_position_stop_loss(self) -> None:
        position = Position(
            contract=make_contract(strike=24000, option_type=OptionType.CALL, expiry=EXPIRY),
            quantity=-75,
            avg_price=Decimal("100"),
        )
        chain = marked_chain({(24000, OptionType.CALL): "250"})  # tripled -> deep loss
        ctx = _ctx(chain=chain)
        reason = evaluate_exit(ctx, (position,), ExitRule(stop_loss_pct=100.0))
        assert reason is not None
        assert "stop loss" in reason

    def test_debit_position_profit_target(self) -> None:
        """A net-debit position (long): premium_exit_reason's old credit<=0 guard would have
        silently never fired here — the sign-safe net_pnl_pct-based path must."""
        position = Position(
            contract=make_contract(strike=24000, option_type=OptionType.CALL, expiry=EXPIRY),
            quantity=75,
            avg_price=Decimal("100"),  # paid 7500
        )
        chain = marked_chain({(24000, OptionType.CALL): "160"})  # now worth 12000 -> 60% profit
        ctx = _ctx(chain=chain)
        reason = evaluate_exit(ctx, (position,), ExitRule(profit_target_pct=50.0))
        assert reason is not None
        assert "profit target" in reason

    def test_debit_position_stop_loss(self) -> None:
        position = Position(
            contract=make_contract(strike=24000, option_type=OptionType.CALL, expiry=EXPIRY),
            quantity=75,
            avg_price=Decimal("100"),  # paid 7500
        )
        chain = marked_chain({(24000, OptionType.CALL): "40"})  # now worth 3000 -> -60%
        ctx = _ctx(chain=chain)
        reason = evaluate_exit(ctx, (position,), ExitRule(stop_loss_pct=50.0))
        assert reason is not None
        assert "stop loss" in reason

    def test_no_signal_within_bands(self) -> None:
        position = Position(
            contract=make_contract(strike=24000, option_type=OptionType.CALL, expiry=EXPIRY),
            quantity=-75,
            avg_price=Decimal("100"),
        )
        chain = marked_chain({(24000, OptionType.CALL): "95"})  # tiny move
        ctx = _ctx(chain=chain)
        assert evaluate_exit(ctx, (position,), ExitRule()) is None


class TestEvaluateAdjustment:
    def test_disabled_returns_none(self) -> None:
        position = Position(
            contract=make_contract(strike=24000, option_type=OptionType.CALL, expiry=EXPIRY),
            quantity=-75,
            avg_price=Decimal("100"),
        )
        ctx = _ctx()
        assert evaluate_adjustment(ctx, (position,), AdjustmentRule(enabled=False)) is None

    def test_rolls_a_breached_short_leg_further_otm(self) -> None:
        chain = enriched_chain()
        ctx = _ctx(chain=chain)
        atm_entry = chain.get(chain.atm_strike, OptionType.CALL)
        assert atm_entry is not None and atm_entry.greeks is not None
        position = Position(contract=atm_entry.contract, quantity=-75, avg_price=Decimal("100"))
        rule = AdjustmentRule(enabled=True, breach_delta=0.35, roll_to_delta=0.20)

        legs = evaluate_adjustment(ctx, (position,), rule)

        assert legs is not None
        assert len(legs) == 2
        closing = next(leg for leg in legs if leg.side is Side.BUY)
        opening = next(leg for leg in legs if leg.side is Side.SELL)
        assert closing.contract.strike == atm_entry.contract.strike
        assert opening.contract.strike != atm_entry.contract.strike
        assert opening.contract.option_type is OptionType.CALL

    def test_no_adjustment_when_delta_not_breached(self) -> None:
        chain = enriched_chain()
        ctx = _ctx(chain=chain)
        far_otm = min(
            (e for e in chain.entries if e.contract.is_call and e.greeks is not None),
            key=lambda e: abs(e.greeks.delta) if e.greeks else 1.0,
        )
        position = Position(contract=far_otm.contract, quantity=-75, avg_price=Decimal("10"))
        rule = AdjustmentRule(enabled=True, breach_delta=0.35, roll_to_delta=0.20)
        assert evaluate_adjustment(ctx, (position,), rule) is None

    def test_skips_long_positions(self) -> None:
        chain = enriched_chain()
        ctx = _ctx(chain=chain)
        atm_entry = chain.get(chain.atm_strike, OptionType.CALL)
        assert atm_entry is not None
        position = Position(contract=atm_entry.contract, quantity=75, avg_price=Decimal("100"))
        rule = AdjustmentRule(enabled=True, breach_delta=0.35, roll_to_delta=0.20)
        assert evaluate_adjustment(ctx, (position,), rule) is None

    def test_skips_flat_positions(self) -> None:
        chain = enriched_chain()
        ctx = _ctx(chain=chain)
        atm_entry = chain.get(chain.atm_strike, OptionType.CALL)
        assert atm_entry is not None
        position = Position(contract=atm_entry.contract, quantity=0, avg_price=Decimal("0"))
        rule = AdjustmentRule(enabled=True, breach_delta=0.35, roll_to_delta=0.20)
        assert evaluate_adjustment(ctx, (position,), rule) is None

    def test_skips_position_from_a_different_expiry(self) -> None:
        """A position held across an expiry-listing change (the exchange starts
        quoting a new date for the same weekly series) must never get rolled
        against a chain that doesn't actually describe it -- `chain.get()` only
        matches by strike + option_type, so without this guard the "replacement"
        leg would come from a different expiry than the leg being closed, and
        `Signal`'s own validation rejects legs that don't share an expiry."""
        chain = enriched_chain()
        ctx = _ctx(chain=chain)
        atm_entry = chain.get(chain.atm_strike, OptionType.CALL)
        assert atm_entry is not None
        stale_contract = atm_entry.contract.model_copy(
            update={"expiry": date(2025, 8, 5)}  # a week later than `chain.expiry`
        )
        position = Position(contract=stale_contract, quantity=-75, avg_price=Decimal("100"))
        rule = AdjustmentRule(enabled=True, breach_delta=0.35, roll_to_delta=0.20)

        assert evaluate_adjustment(ctx, (position,), rule) is None

    def test_skips_short_leg_not_found_in_chain(self) -> None:
        chain = enriched_chain()
        ctx = _ctx(chain=chain)
        # a contract at a strike this chain doesn't quote at all
        position = Position(
            contract=make_contract(strike=99999, option_type=OptionType.CALL, expiry=EXPIRY),
            quantity=-75,
            avg_price=Decimal("10"),
        )
        rule = AdjustmentRule(enabled=True, breach_delta=0.35, roll_to_delta=0.20)
        assert evaluate_adjustment(ctx, (position,), rule) is None

    def test_rolls_even_with_an_extreme_roll_target(self) -> None:
        # find_by_delta always returns the *nearest* candidate, never None, once at least one
        # entry has greeks -- confirmed even for a deliberately unrealistic roll_to_delta.
        chain = enriched_chain()
        ctx = _ctx(chain=chain)
        atm_entry = chain.get(chain.atm_strike, OptionType.CALL)
        assert atm_entry is not None
        position = Position(contract=atm_entry.contract, quantity=-75, avg_price=Decimal("100"))
        rule = AdjustmentRule(enabled=True, breach_delta=0.35, roll_to_delta=0.001)
        legs = evaluate_adjustment(ctx, (position,), rule)
        assert legs is not None
