from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from ceremyn.domain import OptionType, Position, Side, SignalAction
from ceremyn.strategies import Strategy, create
from ceremyn.strategies.base import StrategyContext
from tests.unit.domain.conftest import make_contract
from tests.unit.strategies.conftest import (
    EXPIRY,
    NOW,
    enriched_chain,
    make_definition,
    marked_chain,
)


def condor_ctx(iv_rank: float | None = 80.0, **overrides: object) -> StrategyContext:
    defaults: dict[str, object] = {"chain": enriched_chain(), "iv_rank": iv_rank, "now": NOW}
    defaults.update(overrides)
    return StrategyContext.model_validate(defaults)


def make_strategy(**params: Any) -> Strategy[Any]:
    return create(make_definition("iron_condor", **params))


class TestEntry:
    def test_enters_four_leg_condor(self) -> None:
        signals = make_strategy().on_chain(condor_ctx())
        assert len(signals) == 1
        signal = signals[0]
        assert signal.action is SignalAction.ENTER
        assert len(signal.legs) == 4

        short_call = next(
            leg for leg in signal.legs if leg.side is Side.SELL and leg.contract.is_call
        )
        short_put = next(
            leg for leg in signal.legs if leg.side is Side.SELL and leg.contract.is_put
        )
        long_call = next(
            leg for leg in signal.legs if leg.side is Side.BUY and leg.contract.is_call
        )
        long_put = next(leg for leg in signal.legs if leg.side is Side.BUY and leg.contract.is_put)

        spot = Decimal(24000)
        assert short_put.contract.strike < spot < short_call.contract.strike
        assert long_call.contract.strike > short_call.contract.strike  # wing beyond short
        assert long_put.contract.strike < short_put.contract.strike

    def test_no_entry_when_iv_rank_low(self) -> None:
        assert make_strategy().on_chain(condor_ctx(iv_rank=10.0)) == []

    def test_wing_delta_must_be_below_short_delta(self) -> None:
        with pytest.raises(ValidationError, match="wing_delta"):
            make_strategy(short_delta=0.15, wing_delta=0.20)


class TestExit:
    def test_profit_target_exit_includes_all_four_legs(self) -> None:
        legs = {
            (24400, OptionType.CALL): ("-75", "150"),  # short call
            (23600, OptionType.PUT): ("-75", "140"),  # short put
            (24800, OptionType.CALL): ("75", "50"),  # long wing
            (23200, OptionType.PUT): ("75", "45"),  # long wing
        }
        positions = tuple(
            Position(
                contract=make_contract(strike=strike, option_type=ot, expiry=EXPIRY),
                quantity=int(qty),
                avg_price=Decimal(avg),
            )
            for (strike, ot), (qty, avg) in legs.items()
        )
        # Net credit/unit: 290 - 95 = 195. Marks below give close cost
        # (60+70) - (20+15) = 95 -> 51% profit >= 50% target.
        chain = marked_chain(
            {
                (24400, OptionType.CALL): "60",
                (23600, OptionType.PUT): "70",
                (24800, OptionType.CALL): "20",
                (23200, OptionType.PUT): "15",
            }
        )
        signals = make_strategy().on_chain(condor_ctx(chain=chain, positions=positions))
        assert len(signals) == 1
        signal = signals[0]
        assert signal.action is SignalAction.EXIT
        assert "profit target" in signal.reason
        sides = {(leg.contract.strike, leg.side) for leg in signal.legs}
        assert (Decimal(24400), Side.BUY) in sides  # buy back short call
        assert (Decimal(23200), Side.SELL) in sides  # sell long wing
        assert len(signal.legs) == 4
