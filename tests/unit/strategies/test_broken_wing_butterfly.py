from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from alphaquant.domain import OptionType, Position, Side, SignalAction
from alphaquant.strategies import Strategy, create
from alphaquant.strategies.base import StrategyContext
from alphaquant.strategies.common import mark_price
from tests.unit.domain.conftest import make_contract
from tests.unit.strategies.conftest import (
    EXPIRY,
    NOW,
    enriched_chain,
    ist,
    make_definition,
    marked_chain,
)


def bwb_ctx(iv_rank: float | None = 80.0, **overrides: object) -> StrategyContext:
    defaults: dict[str, object] = {"chain": enriched_chain(), "iv_rank": iv_rank, "now": NOW}
    defaults.update(overrides)
    return StrategyContext.model_validate(defaults)


def make_strategy(**params: Any) -> Strategy[Any]:
    return create(make_definition("broken_wing_butterfly", **params))


class TestEntry:
    def test_enters_three_leg_structure_with_unequal_wings(self) -> None:
        signals = make_strategy().on_chain(bwb_ctx())
        assert len(signals) == 1
        signal = signals[0]
        assert signal.action is SignalAction.ENTER
        assert len(signal.legs) == 3
        assert all(leg.contract.is_put for leg in signal.legs)

        body = next(leg for leg in signal.legs if leg.side is Side.SELL)
        # Ascending strike: the far wing (lower delta, further OTM) sits at the lower
        # strike; the near wing (higher delta, closer to spot) sits at the higher one.
        far_wing, near_wing = sorted(
            (leg for leg in signal.legs if leg.side is Side.BUY),
            key=lambda leg: leg.contract.strike,
        )
        assert body.lots == 2 * near_wing.lots
        # near wing sits closer to spot (higher strike) than the body; far wing sits
        # further from spot (lower strike) than the body -- the body is bracketed.
        assert far_wing.contract.strike < body.contract.strike < near_wing.contract.strike
        # unequal wing widths -- the whole point of "broken wing".
        assert (near_wing.contract.strike - body.contract.strike) != (
            body.contract.strike - far_wing.contract.strike
        )

    def test_call_side_variant_uses_calls(self) -> None:
        signals = make_strategy(option_type="CE").on_chain(bwb_ctx())
        assert len(signals) == 1
        assert all(leg.contract.is_call for leg in signals[0].legs)

    def test_no_entry_when_iv_rank_low(self) -> None:
        assert make_strategy().on_chain(bwb_ctx(iv_rank=10.0)) == []

    def test_no_entry_outside_dte_window(self) -> None:
        assert make_strategy(entry_dte_max=3).on_chain(bwb_ctx()) == []  # DTE 8 by default

    def test_rejects_wings_that_do_not_bracket_the_body(self) -> None:
        with pytest.raises(ValidationError, match="far_wing_delta < body_delta < near_wing_delta"):
            make_strategy(near_wing_delta=0.15, body_delta=0.20, far_wing_delta=0.08)


class TestExit:
    def test_profit_target_exit_includes_all_three_legs(self) -> None:
        legs = {
            (24500, OptionType.PUT): ("75", "60"),  # near wing (long)
            (24000, OptionType.PUT): ("-150", "95"),  # body (short, 2 lots)
            (23200, OptionType.PUT): ("75", "20"),  # far wing (long)
        }
        positions = tuple(
            Position(
                contract=make_contract(strike=strike, option_type=ot, expiry=EXPIRY),
                quantity=int(qty),
                avg_price=Decimal(avg),
            )
            for (strike, ot), (qty, avg) in legs.items()
        )
        chain = marked_chain(
            {
                (24500, OptionType.PUT): "25",
                (24000, OptionType.PUT): "38",
                (23200, OptionType.PUT): "8",
            }
        )
        signals = make_strategy().on_chain(bwb_ctx(chain=chain, positions=positions))
        assert len(signals) == 1
        signal = signals[0]
        assert signal.action is SignalAction.EXIT
        assert len(signal.legs) == 3

    def test_expiry_proximity_exit(self) -> None:
        position = Position(
            contract=make_contract(strike=24000, option_type=OptionType.PUT, expiry=EXPIRY),
            quantity=-150,
            avg_price=Decimal("95"),
        )
        chain = marked_chain({(24000, OptionType.PUT): "95"}, now=NOW)
        near_now = ist(date(2025, 7, 28), 10)  # DTE 1
        signals = make_strategy(exit_dte=1).on_chain(
            bwb_ctx(chain=chain, positions=(position,), now=near_now)
        )
        assert len(signals) == 1
        assert "expiry proximity" in signals[0].reason


class TestAdjustment:
    def test_rolls_a_breached_short_leg(self) -> None:
        chain = enriched_chain()
        atm_put = chain.get(chain.atm_strike, OptionType.PUT)
        assert atm_put is not None
        put_mark = mark_price(atm_put)
        assert put_mark is not None
        positions = (Position(contract=atm_put.contract, quantity=-150, avg_price=put_mark),)
        strategy = make_strategy(adjustment_enabled=True, adjustment_breach_delta=0.35)

        signals = strategy.on_chain(bwb_ctx(chain=chain, positions=positions))

        assert len(signals) == 1
        assert signals[0].action is SignalAction.ADJUST
