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


def lizard_ctx(iv_rank: float | None = 80.0, **overrides: object) -> StrategyContext:
    defaults: dict[str, object] = {"chain": enriched_chain(), "iv_rank": iv_rank, "now": NOW}
    defaults.update(overrides)
    return StrategyContext.model_validate(defaults)


def make_strategy(**params: Any) -> Strategy[Any]:
    return create(make_definition("jade_lizard", **params))


class TestEntry:
    def test_enters_naked_put_plus_call_credit_spread(self) -> None:
        signals = make_strategy().on_chain(lizard_ctx())
        assert len(signals) == 1
        signal = signals[0]
        assert signal.action is SignalAction.ENTER
        assert len(signal.legs) == 3

        short_put = next(leg for leg in signal.legs if leg.contract.is_put)
        assert short_put.side is Side.SELL

        short_call = next(
            leg for leg in signal.legs if leg.contract.is_call and leg.side is Side.SELL
        )
        long_call = next(
            leg for leg in signal.legs if leg.contract.is_call and leg.side is Side.BUY
        )
        assert long_call.contract.strike > short_call.contract.strike

    def test_no_entry_when_iv_rank_low(self) -> None:
        assert make_strategy().on_chain(lizard_ctx(iv_rank=10.0)) == []

    def test_no_entry_outside_dte_window(self) -> None:
        assert make_strategy(entry_dte_max=3).on_chain(lizard_ctx()) == []  # DTE 8 by default

    def test_rejects_call_spread_shaped_as_a_debit(self) -> None:
        with pytest.raises(ValidationError, match="call_long_delta must be below call_short_delta"):
            make_strategy(call_short_delta=0.10, call_long_delta=0.25)


class TestExit:
    def test_profit_target_exit_includes_all_three_legs(self) -> None:
        legs = {
            (23300, OptionType.PUT): ("-75", "70"),  # short put (naked)
            (24600, OptionType.CALL): ("-75", "55"),  # short call
            (24900, OptionType.CALL): ("75", "20"),  # long call (further OTM)
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
                (23300, OptionType.PUT): "25",
                (24600, OptionType.CALL): "18",
                (24900, OptionType.CALL): "6",
            }
        )
        signals = make_strategy().on_chain(lizard_ctx(chain=chain, positions=positions))
        assert len(signals) == 1
        signal = signals[0]
        assert signal.action is SignalAction.EXIT
        assert len(signal.legs) == 3

    def test_expiry_proximity_exit(self) -> None:
        position = Position(
            contract=make_contract(strike=23300, option_type=OptionType.PUT, expiry=EXPIRY),
            quantity=-75,
            avg_price=Decimal("70"),
        )
        chain = marked_chain({(23300, OptionType.PUT): "70"}, now=NOW)
        near_now = ist(date(2025, 7, 28), 10)  # DTE 1
        signals = make_strategy(exit_dte=1).on_chain(
            lizard_ctx(chain=chain, positions=(position,), now=near_now)
        )
        assert len(signals) == 1
        assert "expiry proximity" in signals[0].reason


class TestAdjustment:
    def test_rolls_the_naked_put_when_breached(self) -> None:
        chain = enriched_chain()
        atm_put = chain.get(chain.atm_strike, OptionType.PUT)
        assert atm_put is not None
        put_mark = mark_price(atm_put)
        assert put_mark is not None
        positions = (Position(contract=atm_put.contract, quantity=-75, avg_price=put_mark),)
        strategy = make_strategy(adjustment_enabled=True, adjustment_breach_delta=0.35)

        signals = strategy.on_chain(lizard_ctx(chain=chain, positions=positions))

        assert len(signals) == 1
        assert signals[0].action is SignalAction.ADJUST
