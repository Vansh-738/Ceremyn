from decimal import Decimal
from typing import Any

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


def straddle_ctx(iv_rank: float | None = 80.0, **overrides: object) -> StrategyContext:
    defaults: dict[str, object] = {"chain": enriched_chain(), "iv_rank": iv_rank, "now": NOW}
    defaults.update(overrides)
    return StrategyContext.model_validate(defaults)


def make_strategy(**params: Any) -> Strategy[Any]:
    return create(make_definition("short_straddle", **params))


class TestEntry:
    def test_enters_two_leg_atm_straddle(self) -> None:
        signals = make_strategy().on_chain(straddle_ctx())
        assert len(signals) == 1
        signal = signals[0]
        assert signal.action is SignalAction.ENTER
        assert len(signal.legs) == 2
        assert all(leg.side is Side.SELL for leg in signal.legs)

        chain = enriched_chain()
        assert {leg.contract.strike for leg in signal.legs} == {chain.atm_strike}
        assert {leg.contract.option_type for leg in signal.legs} == {
            OptionType.CALL,
            OptionType.PUT,
        }

    def test_no_entry_when_iv_rank_low(self) -> None:
        assert make_strategy().on_chain(straddle_ctx(iv_rank=10.0)) == []

    def test_no_entry_when_already_holding(self) -> None:
        position = Position(
            contract=make_contract(strike=24000, option_type=OptionType.CALL, expiry=EXPIRY),
            quantity=-75,
            avg_price=Decimal("100"),
        )
        chain = marked_chain({(24000, OptionType.CALL): "95"})
        signals = make_strategy().on_chain(straddle_ctx(chain=chain, positions=(position,)))
        assert signals == []  # within band, no exit signal either


class TestExit:
    def test_profit_target_exit_includes_both_legs(self) -> None:
        legs = {
            (24000, OptionType.CALL): ("-75", "100"),
            (24000, OptionType.PUT): ("-75", "95"),
        }
        positions = tuple(
            Position(
                contract=make_contract(strike=strike, option_type=ot, expiry=EXPIRY),
                quantity=int(qty),
                avg_price=Decimal(avg),
            )
            for (strike, ot), (qty, avg) in legs.items()
        )
        chain = marked_chain({(24000, OptionType.CALL): "40", (24000, OptionType.PUT): "38"})
        signals = make_strategy().on_chain(straddle_ctx(chain=chain, positions=positions))
        assert len(signals) == 1
        signal = signals[0]
        assert signal.action is SignalAction.EXIT
        assert "profit target" in signal.reason
        assert len(signal.legs) == 2
        assert all(leg.side is Side.BUY for leg in signal.legs)
