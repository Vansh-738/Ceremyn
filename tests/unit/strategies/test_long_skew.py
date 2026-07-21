from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from alphaquant.domain import OptionType, Position, Side, SignalAction
from alphaquant.strategies import Strategy, create
from alphaquant.strategies.base import StrategyContext
from tests.unit.domain.conftest import make_contract
from tests.unit.strategies.conftest import (
    EXPIRY,
    NOW,
    enriched_chain,
    ist,
    make_definition,
    marked_chain,
)


def skewed_iv_chain(*, call_sigma: float, put_sigma: float):
    """Two-sided enriched chains (one priced at each sigma) merged by option type,
    so calls carry `call_sigma`'s IV and puts carry `put_sigma`'s."""
    calls = enriched_chain(sigma=call_sigma)
    puts = enriched_chain(sigma=put_sigma)
    entries = tuple(entry for entry in calls.entries if entry.contract.is_call) + tuple(
        entry for entry in puts.entries if entry.contract.is_put
    )
    return calls.model_copy(update={"entries": entries})


def skew_ctx(chain: Any = None, **ctx_overrides: object) -> StrategyContext:
    defaults: dict[str, object] = {"chain": chain or enriched_chain(), "now": NOW}
    defaults.update(ctx_overrides)
    return StrategyContext.model_validate(defaults)


def make_strategy(**params: Any) -> Strategy[Any]:
    return create(make_definition("long_skew", **params))


def open_call_position(avg: str) -> tuple[Position, ...]:
    call = make_contract(strike=24400, option_type=OptionType.CALL, expiry=EXPIRY)
    return (Position(contract=call, quantity=75, avg_price=Decimal(avg)),)


class TestParams:
    def test_rejects_bearish_threshold_at_or_above_bullish(self) -> None:
        with pytest.raises(ValidationError):
            make_strategy(skew_bullish_threshold=1.0, skew_bearish_threshold=1.0)


class TestEntry:
    def test_steep_put_skew_buys_a_call(self) -> None:
        # Puts priced much richer (higher sigma) than calls -> skew ratio > 1.15.
        chain = skewed_iv_chain(call_sigma=0.12, put_sigma=0.20)
        signals = make_strategy().on_chain(skew_ctx(chain))
        assert len(signals) == 1
        signal = signals[0]
        assert signal.action is SignalAction.ENTER
        assert signal.strategy_id == "long_skew_test"
        leg = signal.legs[0]
        assert leg.contract.is_call
        assert leg.side is Side.BUY
        assert "IV skew" in signal.reason

    def test_inverted_call_skew_buys_a_put(self) -> None:
        chain = skewed_iv_chain(call_sigma=0.20, put_sigma=0.12)
        signals = make_strategy().on_chain(skew_ctx(chain))
        assert len(signals) == 1
        leg = signals[0].legs[0]
        assert leg.contract.is_put
        assert leg.side is Side.BUY

    def test_no_entry_when_skew_is_normal(self) -> None:
        chain = skewed_iv_chain(call_sigma=0.15, put_sigma=0.16)
        assert make_strategy().on_chain(skew_ctx(chain)) == []

    def test_no_entry_outside_dte_window(self) -> None:
        chain = skewed_iv_chain(call_sigma=0.12, put_sigma=0.20)
        early = skew_ctx(chain, now=ist(date(2025, 7, 7), 10))
        assert make_strategy().on_chain(early) == []
        late = skew_ctx(chain, now=ist(date(2025, 7, 28), 10))
        assert make_strategy().on_chain(late) == []

    def test_no_entry_without_greeks(self) -> None:
        chain = marked_chain({(24000, OptionType.CALL): "150", (24000, OptionType.PUT): "140"})
        assert make_strategy().on_chain(skew_ctx(chain)) == []


class TestExit:
    def test_profit_target_exit(self) -> None:
        # Debit paid 7500 (75 units @ 100); close value 11250 -> 50% profit >= 40%.
        ctx = skew_ctx(
            marked_chain({(24400, OptionType.CALL): "150"}),
            positions=open_call_position("100"),
        )
        signals = make_strategy().on_chain(ctx)
        assert len(signals) == 1
        assert signals[0].action is SignalAction.EXIT
        assert "profit target" in signals[0].reason
        assert signals[0].legs[0].side is Side.SELL

    def test_stop_loss_exit(self) -> None:
        # Debit paid 7500; close value 3750 -> 50% loss >= 40% stop.
        ctx = skew_ctx(
            marked_chain({(24400, OptionType.CALL): "50"}),
            positions=open_call_position("100"),
        )
        signals = make_strategy().on_chain(ctx)
        assert len(signals) == 1
        assert "stop loss" in signals[0].reason

    def test_holds_between_thresholds(self) -> None:
        ctx = skew_ctx(
            marked_chain({(24400, OptionType.CALL): "110"}),
            positions=open_call_position("100"),
        )
        assert make_strategy().on_chain(ctx) == []

    def test_expiry_proximity_exit_needs_no_marks(self) -> None:
        now = ist(date(2025, 7, 28), 10)
        ctx = skew_ctx(
            marked_chain({(25500, OptionType.CALL): "1"}, now=now),
            positions=open_call_position("100"),
            now=now,
        )
        signals = make_strategy().on_chain(ctx)
        assert len(signals) == 1
        assert "expiry proximity" in signals[0].reason
