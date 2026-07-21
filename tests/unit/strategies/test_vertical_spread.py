from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from ceremyn.domain import OptionType, Position, Side, SignalAction
from ceremyn.strategies import Strategy, create
from ceremyn.strategies.base import StrategyContext
from ceremyn.strategies.common import find_by_delta, mark_price
from tests.unit.domain.conftest import make_contract
from tests.unit.strategies.conftest import (
    EXPIRY,
    NOW,
    enriched_chain,
    make_definition,
    marked_chain,
)


def spread_ctx(iv_rank: float | None = None, **overrides: object) -> StrategyContext:
    defaults: dict[str, object] = {"chain": enriched_chain(), "iv_rank": iv_rank, "now": NOW}
    defaults.update(overrides)
    return StrategyContext.model_validate(defaults)


def make_strategy(strategy_type: str, **params: Any) -> Strategy[Any]:
    return create(make_definition(strategy_type, **params))


class TestGenericVerticalSpread:
    def test_credit_spread_two_legs(self) -> None:
        signals = make_strategy(
            "vertical_spread", option_type="PE", short_delta=0.30, long_delta=0.15
        ).on_chain(spread_ctx())
        assert len(signals) == 1
        signal = signals[0]
        assert len(signal.legs) == 2
        short_leg = next(leg for leg in signal.legs if leg.side is Side.SELL)
        long_leg = next(leg for leg in signal.legs if leg.side is Side.BUY)
        assert short_leg.contract.strike > long_leg.contract.strike  # put: nearer money = higher
        assert all(leg.contract.is_put for leg in signal.legs)

    def test_debit_spread_reversed_deltas(self) -> None:
        # short_delta < long_delta -> sell further OTM, buy nearer the money -> net debit
        signals = make_strategy(
            "vertical_spread", option_type="CE", short_delta=0.15, long_delta=0.30
        ).on_chain(spread_ctx())
        assert len(signals) == 1
        assert len(signals[0].legs) == 2

    def test_no_iv_filter_by_default(self) -> None:
        # min_iv_rank defaults to None -> entry is not blocked even with iv_rank=None
        signals = make_strategy("vertical_spread").on_chain(spread_ctx(iv_rank=None))
        assert len(signals) == 1

    def test_adjustment_rolls_breached_short_leg(self) -> None:
        chain = enriched_chain()
        short_entry = find_by_delta(chain, OptionType.PUT, 0.30)
        assert short_entry is not None
        mark = mark_price(short_entry)
        assert mark is not None
        position = Position(contract=short_entry.contract, quantity=-75, avg_price=mark)
        strategy = make_strategy(
            "vertical_spread",
            option_type="PE",
            short_delta=0.30,
            long_delta=0.15,
            adjustment_enabled=True,
            adjustment_breach_delta=0.25,
            adjustment_roll_to_delta=0.15,
        )

        signals = strategy.on_chain(spread_ctx(chain=chain, positions=(position,)))

        assert len(signals) == 1
        assert signals[0].action is SignalAction.ADJUST


class TestBullPutSpread:
    def test_enters_put_credit_spread(self) -> None:
        signals = make_strategy("bull_put_spread").on_chain(spread_ctx())
        assert len(signals) == 1
        signal = signals[0]
        assert all(leg.contract.is_put for leg in signal.legs)
        short_leg = next(leg for leg in signal.legs if leg.side is Side.SELL)
        long_leg = next(leg for leg in signal.legs if leg.side is Side.BUY)
        assert short_leg.contract.strike > long_leg.contract.strike

    def test_rejects_call_option_type(self) -> None:
        with pytest.raises(ValidationError, match="PUT"):
            make_strategy("bull_put_spread", option_type="CE")

    def test_rejects_non_credit_delta_ordering(self) -> None:
        with pytest.raises(ValidationError, match="short_delta"):
            make_strategy("bull_put_spread", short_delta=0.15, long_delta=0.30)


class TestBearCallSpread:
    def test_enters_call_credit_spread(self) -> None:
        signals = make_strategy("bear_call_spread").on_chain(spread_ctx())
        assert len(signals) == 1
        signal = signals[0]
        assert all(leg.contract.is_call for leg in signal.legs)
        short_leg = next(leg for leg in signal.legs if leg.side is Side.SELL)
        long_leg = next(leg for leg in signal.legs if leg.side is Side.BUY)
        assert short_leg.contract.strike < long_leg.contract.strike

    def test_rejects_put_option_type(self) -> None:
        with pytest.raises(ValidationError, match="CALL"):
            make_strategy("bear_call_spread", option_type="PE")

    def test_rejects_non_credit_delta_ordering(self) -> None:
        with pytest.raises(ValidationError, match="short_delta"):
            make_strategy("bear_call_spread", short_delta=0.15, long_delta=0.30)

    def test_exit_closes_both_legs(self) -> None:
        legs = {
            (24300, OptionType.CALL): ("-75", "60"),
            (24600, OptionType.CALL): ("75", "20"),
        }
        positions = tuple(
            Position(
                contract=make_contract(strike=strike, option_type=ot, expiry=EXPIRY),
                quantity=int(qty),
                avg_price=Decimal(avg),
            )
            for (strike, ot), (qty, avg) in legs.items()
        )
        chain = marked_chain({(24300, OptionType.CALL): "20", (24600, OptionType.CALL): "5"})
        signals = make_strategy("bear_call_spread").on_chain(
            spread_ctx(chain=chain, positions=positions)
        )
        assert len(signals) == 1
        assert signals[0].action is SignalAction.EXIT
        assert len(signals[0].legs) == 2
