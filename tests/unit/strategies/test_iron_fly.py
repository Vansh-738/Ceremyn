from datetime import date
from decimal import Decimal
from typing import Any

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


def fly_ctx(iv_rank: float | None = 80.0, **overrides: object) -> StrategyContext:
    defaults: dict[str, object] = {"chain": enriched_chain(), "iv_rank": iv_rank, "now": NOW}
    defaults.update(overrides)
    return StrategyContext.model_validate(defaults)


def make_strategy(**params: Any) -> Strategy[Any]:
    return create(make_definition("iron_fly", **params))


class TestEntry:
    def test_enters_four_leg_fly_with_atm_shorts(self) -> None:
        signals = make_strategy().on_chain(fly_ctx())
        assert len(signals) == 1
        signal = signals[0]
        assert signal.action is SignalAction.ENTER
        assert len(signal.legs) == 4

        chain = enriched_chain()
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

        assert short_call.contract.strike == chain.atm_strike
        assert short_put.contract.strike == chain.atm_strike
        assert long_call.contract.strike > short_call.contract.strike
        assert long_put.contract.strike < short_put.contract.strike

    def test_no_entry_when_iv_rank_low(self) -> None:
        assert make_strategy().on_chain(fly_ctx(iv_rank=10.0)) == []

    def test_no_entry_outside_dte_window(self) -> None:
        assert make_strategy(entry_dte_max=3).on_chain(fly_ctx()) == []  # DTE 8 by default


class TestExit:
    def test_profit_target_exit_includes_all_four_legs(self) -> None:
        legs = {
            (24000, OptionType.CALL): ("-75", "100"),  # short ATM call
            (24000, OptionType.PUT): ("-75", "95"),  # short ATM put
            (24700, OptionType.CALL): ("75", "30"),  # long wing
            (23300, OptionType.PUT): ("75", "28"),  # long wing
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
                (24000, OptionType.CALL): "40",
                (24000, OptionType.PUT): "38",
                (24700, OptionType.CALL): "10",
                (23300, OptionType.PUT): "9",
            }
        )
        signals = make_strategy().on_chain(fly_ctx(chain=chain, positions=positions))
        assert len(signals) == 1
        signal = signals[0]
        assert signal.action is SignalAction.EXIT
        assert "profit target" in signal.reason
        assert len(signal.legs) == 4

    def test_expiry_proximity_exit(self) -> None:
        position = Position(
            contract=make_contract(strike=24000, option_type=OptionType.CALL, expiry=EXPIRY),
            quantity=-75,
            avg_price=Decimal("100"),
        )
        chain = marked_chain({(24000, OptionType.CALL): "100"}, now=NOW)
        near_now = ist(date(2025, 7, 28), 10)  # DTE 1
        signals = make_strategy(exit_dte=1).on_chain(
            fly_ctx(chain=chain, positions=(position,), now=near_now)
        )
        assert len(signals) == 1
        assert "expiry proximity" in signals[0].reason


class TestAdjustment:
    def test_rolls_a_breached_short_leg(self) -> None:
        chain = enriched_chain()
        atm_call = chain.get(chain.atm_strike, OptionType.CALL)
        atm_put = chain.get(chain.atm_strike, OptionType.PUT)
        assert atm_call is not None and atm_put is not None
        call_mark = mark_price(atm_call)
        put_mark = mark_price(atm_put)
        assert call_mark is not None and put_mark is not None
        positions = (
            Position(contract=atm_call.contract, quantity=-75, avg_price=call_mark),
            Position(contract=atm_put.contract, quantity=-75, avg_price=put_mark),
        )
        strategy = make_strategy(adjustment_enabled=True, adjustment_breach_delta=0.35)

        signals = strategy.on_chain(fly_ctx(chain=chain, positions=positions))

        assert len(signals) == 1
        assert signals[0].action is SignalAction.ADJUST
