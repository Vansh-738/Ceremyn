from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from alphaquant.domain import OptionType, Position, Side, SignalAction
from alphaquant.strategies import Strategy, create
from alphaquant.strategies.base import StrategyContext
from alphaquant.strategies.calendar_spread import CalendarSpread, _net_close_cost_across
from alphaquant.strategies.common import mark_price
from tests.unit.domain.conftest import make_contract
from tests.unit.strategies.conftest import EXPIRY, NOW, enriched_chain, ist, make_definition

FAR_EXPIRY = date(2025, 8, 26)


def make_strategy(**params: Any) -> Strategy[Any]:
    return create(make_definition("calendar_spread", **params))


def near_far_chains() -> tuple[Any, Any]:
    near = enriched_chain(expiry=EXPIRY, now=NOW)
    far = enriched_chain(expiry=FAR_EXPIRY, now=NOW)
    return near, far


class TestParams:
    def test_far_must_exceed_near(self) -> None:
        with pytest.raises(ValidationError, match="far_expiry_min_days_out"):
            make_strategy(near_expiry_dte_max=20, far_expiry_min_days_out=10)


class TestEntry:
    def test_enters_two_correlated_single_leg_signals(self) -> None:
        near, far = near_far_chains()
        strategy = make_strategy(near_expiry_dte_max=10)
        ctx = StrategyContext(chain=near, now=NOW, other_expiries={far.expiry: far})

        signals = strategy.on_chain(ctx)

        assert len(signals) == 2
        assert {s.expiry for s in signals} == {near.expiry, far.expiry}
        assert {s.action for s in signals} == {SignalAction.ENTER}
        # every signal is single-leg (Signal legs must share one expiry — see module docstring)
        assert all(len(s.legs) == 1 for s in signals)
        near_signal = next(s for s in signals if s.expiry == near.expiry)
        far_signal = next(s for s in signals if s.expiry == far.expiry)
        assert near_signal.legs[0].side is Side.SELL
        assert far_signal.legs[0].side is Side.BUY
        assert near_signal.legs[0].contract.strike == far_signal.legs[0].contract.strike
        # linked by a shared correlation_id
        assert near_signal.correlation_id == far_signal.correlation_id
        assert near_signal.correlation_id is not None

    def test_no_entry_without_a_far_chain(self) -> None:
        near, _ = near_far_chains()
        strategy = make_strategy(near_expiry_dte_max=10)
        ctx = StrategyContext(chain=near, now=NOW)  # other_expiries empty (paper/live today)
        assert strategy.on_chain(ctx) == []

    def test_no_entry_when_chain_is_not_a_near_candidate(self) -> None:
        near, far = near_far_chains()
        strategy = make_strategy(near_expiry_dte_max=10)
        # invoked with the FAR chain as ctx.chain -- DTE from far.expiry is far outside the
        # near-candidate window, so this invocation must no-op.
        ctx = StrategyContext(chain=far, now=NOW, other_expiries={near.expiry: near})
        assert strategy.on_chain(ctx) == []

    def test_no_far_chain_close_enough(self) -> None:
        near, _ = near_far_chains()
        too_close = enriched_chain(expiry=date(2025, 8, 1), now=NOW)  # only a few days further
        strategy = make_strategy(near_expiry_dte_max=10, far_expiry_min_days_out=20)
        ctx = StrategyContext(chain=near, now=NOW, other_expiries={too_close.expiry: too_close})
        assert strategy.on_chain(ctx) == []

    def test_no_entry_when_strike_missing_from_far_chain(self) -> None:
        near, _ = near_far_chains()
        # a far chain quoting a completely different, non-overlapping strike range
        disjoint_far = enriched_chain(expiry=FAR_EXPIRY, now=NOW, strikes=range(30000, 31000, 100))
        strategy = make_strategy(near_expiry_dte_max=10)
        ctx = StrategyContext(
            chain=near, now=NOW, other_expiries={disjoint_far.expiry: disjoint_far}
        )
        assert strategy.on_chain(ctx) == []


class TestExit:
    def _positions(self, near: Any, far: Any) -> tuple[Position, ...]:
        near_leg = near.get(near.atm_strike, OptionType.CALL)
        far_leg = far.get(far.atm_strike, OptionType.CALL)
        assert near_leg is not None and far_leg is not None
        return (
            Position(contract=near_leg.contract, quantity=-75, avg_price=Decimal("100")),
            Position(contract=far_leg.contract, quantity=75, avg_price=Decimal("150")),
        )

    def test_defers_when_invoked_with_the_far_chain(self) -> None:
        near, far = near_far_chains()
        strategy = make_strategy(near_expiry_dte_max=10)
        positions = self._positions(near, far)
        ctx = StrategyContext(
            chain=far, now=NOW, positions=positions, other_expiries={near.expiry: near}
        )
        assert strategy.on_chain(ctx) == []

    def test_expiry_proximity_exit_closes_both_legs_in_two_signals(self) -> None:
        near, far = near_far_chains()
        strategy = make_strategy(near_expiry_dte_max=10, exit_dte=1)
        positions = self._positions(near, far)
        near_expiring = enriched_chain(expiry=EXPIRY, now=ist(date(2025, 7, 28), 10))  # DTE 1
        ctx = StrategyContext(
            chain=near_expiring,
            now=ist(date(2025, 7, 28), 10),
            positions=positions,
            other_expiries={far.expiry: far},
        )

        signals = strategy.on_chain(ctx)

        assert len(signals) == 2
        assert {s.action for s in signals} == {SignalAction.EXIT}
        assert {s.expiry for s in signals} == {near.expiry, far.expiry}
        assert all("expiry proximity" in s.reason for s in signals)
        assert signals[0].correlation_id == signals[1].correlation_id

    def test_pnl_exit_when_far_chain_available(self) -> None:
        near, far = near_far_chains()
        strategy = make_strategy(near_expiry_dte_max=10, profit_target_pct=1.0)
        positions = self._positions(near, far)
        ctx = StrategyContext(
            chain=near, now=NOW, positions=positions, other_expiries={far.expiry: far}
        )

        signals = strategy.on_chain(ctx)

        assert len(signals) == 2
        assert {s.action for s in signals} == {SignalAction.EXIT}

    def test_holds_when_far_chain_unavailable_and_not_near_expiry(self) -> None:
        near, far = near_far_chains()
        strategy = make_strategy(near_expiry_dte_max=10)
        positions = self._positions(near, far)
        ctx = StrategyContext(chain=near, now=NOW, positions=positions)  # no other_expiries
        assert strategy.on_chain(ctx) == []

    def test_holds_when_pnl_within_bands(self) -> None:
        near, far = near_far_chains()
        near_leg = near.get(near.atm_strike, OptionType.CALL)
        far_leg = far.get(far.atm_strike, OptionType.CALL)
        assert near_leg is not None and far_leg is not None
        near_mark = mark_price(near_leg)
        far_mark = mark_price(far_leg)
        assert near_mark is not None and far_mark is not None
        # avg_price == current mark for both legs -> 0% P&L, well inside any band.
        positions = (
            Position(contract=near_leg.contract, quantity=-75, avg_price=near_mark),
            Position(contract=far_leg.contract, quantity=75, avg_price=far_mark),
        )
        strategy = make_strategy(near_expiry_dte_max=10)
        ctx = StrategyContext(
            chain=near, now=NOW, positions=positions, other_expiries={far.expiry: far}
        )
        assert strategy.on_chain(ctx) == []

    def test_exit_signals_skip_already_flat_positions(self) -> None:
        near, far = near_far_chains()
        strategy = make_strategy(near_expiry_dte_max=10, exit_dte=1)
        near_leg = near.get(near.atm_strike, OptionType.CALL)
        far_leg = far.get(far.atm_strike, OptionType.CALL)
        assert near_leg is not None and far_leg is not None
        positions = (
            Position(contract=near_leg.contract, quantity=-75, avg_price=Decimal("100")),
            Position(contract=far_leg.contract, quantity=75, avg_price=Decimal("150")),
            Position(  # already closed -- must be skipped, not turned into a third signal
                contract=make_contract(strike=25000, option_type=OptionType.PUT, expiry=EXPIRY),
                quantity=0,
                avg_price=Decimal("0"),
            ),
        )
        near_expiring = enriched_chain(expiry=EXPIRY, now=ist(date(2025, 7, 28), 10))
        ctx = StrategyContext(
            chain=near_expiring,
            now=ist(date(2025, 7, 28), 10),
            positions=positions,
            other_expiries={far.expiry: far},
        )
        signals = strategy.on_chain(ctx)
        assert len(signals) == 2  # only the two genuinely-open legs

    def test_no_exit_when_a_leg_cannot_be_priced(self) -> None:
        near, far = near_far_chains()
        strategy = make_strategy(near_expiry_dte_max=10)
        # a position at a strike neither chain quotes -> its mark can never be found
        unpriceable = Position(
            contract=make_contract(strike=99999, option_type=OptionType.CALL, expiry=EXPIRY),
            quantity=-75,
            avg_price=Decimal("10"),
        )
        ctx = StrategyContext(
            chain=near,
            now=NOW,
            positions=(unpriceable,),
            other_expiries={far.expiry: far},
        )
        assert strategy.on_chain(ctx) == []


class TestCurrentNearExpiry:
    def test_finds_the_short_leg_past_a_long_leg(self) -> None:
        near, far = near_far_chains()
        near_leg = near.get(near.atm_strike, OptionType.CALL)
        far_leg = far.get(far.atm_strike, OptionType.CALL)
        assert near_leg is not None and far_leg is not None
        positions = (
            Position(contract=far_leg.contract, quantity=75, avg_price=Decimal("150")),
            Position(contract=near_leg.contract, quantity=-75, avg_price=Decimal("100")),
        )
        assert CalendarSpread._current_near_expiry(positions) == near.expiry

    def test_none_when_no_short_leg(self) -> None:
        near, _ = near_far_chains()
        near_leg = near.get(near.atm_strike, OptionType.CALL)
        assert near_leg is not None
        positions = (Position(contract=near_leg.contract, quantity=75, avg_price=Decimal("100")),)
        assert CalendarSpread._current_near_expiry(positions) is None


class TestNetCloseCostAcross:
    def test_skips_flat_positions(self) -> None:
        near, _ = near_far_chains()
        near_leg = near.get(near.atm_strike, OptionType.CALL)
        assert near_leg is not None
        flat = Position(contract=near_leg.contract, quantity=0, avg_price=Decimal("0"))
        cost = _net_close_cost_across((flat,), {near.expiry: near})
        assert cost == Decimal("0")

    def test_none_when_expiry_unknown(self) -> None:
        near, _ = near_far_chains()
        near_leg = near.get(near.atm_strike, OptionType.CALL)
        assert near_leg is not None
        position = Position(contract=near_leg.contract, quantity=-75, avg_price=Decimal("100"))
        assert _net_close_cost_across((position,), {}) is None

    def test_none_when_mark_missing(self) -> None:
        near, _ = near_far_chains()
        unpriceable = Position(
            contract=make_contract(strike=99999, option_type=OptionType.CALL, expiry=EXPIRY),
            quantity=-75,
            avg_price=Decimal("10"),
        )
        assert _net_close_cost_across((unpriceable,), {near.expiry: near}) is None
