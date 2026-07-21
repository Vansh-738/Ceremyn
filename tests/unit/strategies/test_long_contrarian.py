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


def skewed_chain(*, put_oi: int, call_oi: int):
    base = enriched_chain()
    entries = tuple(
        entry.model_copy(
            update={
                "quote": entry.quote.model_copy(
                    update={"open_interest": put_oi if entry.contract.is_put else call_oi}
                )
            }
        )
        for entry in base.entries
    )
    return base.model_copy(update={"entries": entries})


def contrarian_ctx(chain: Any = None, **ctx_overrides: object) -> StrategyContext:
    defaults: dict[str, object] = {"chain": chain or enriched_chain(), "now": NOW}
    defaults.update(ctx_overrides)
    return StrategyContext.model_validate(defaults)


def make_strategy(**params: Any) -> Strategy[Any]:
    return create(make_definition("long_contrarian", **params))


def open_call_position(avg: str) -> tuple[Position, ...]:
    call = make_contract(strike=24400, option_type=OptionType.CALL, expiry=EXPIRY)
    return (Position(contract=call, quantity=75, avg_price=Decimal(avg)),)


class TestParams:
    def test_rejects_bearish_threshold_at_or_above_bullish(self) -> None:
        with pytest.raises(ValidationError):
            make_strategy(pcr_bullish_threshold=1.0, pcr_bearish_threshold=1.0)


class TestEntry:
    def test_high_pcr_buys_a_call(self) -> None:
        chain = skewed_chain(put_oi=200_000, call_oi=100_000)  # pcr = 2.0
        signals = make_strategy().on_chain(contrarian_ctx(chain))
        assert len(signals) == 1
        signal = signals[0]
        assert signal.action is SignalAction.ENTER
        assert signal.strategy_id == "long_contrarian_test"
        leg = signal.legs[0]
        assert leg.contract.is_call
        assert leg.side is Side.BUY
        assert "PCR 2.00 contrarian CE" in signal.reason

    def test_low_pcr_buys_a_put(self) -> None:
        chain = skewed_chain(put_oi=50_000, call_oi=100_000)  # pcr = 0.5
        signals = make_strategy().on_chain(contrarian_ctx(chain))
        assert len(signals) == 1
        leg = signals[0].legs[0]
        assert leg.contract.is_put
        assert leg.side is Side.BUY

    def test_no_entry_when_pcr_is_neutral(self) -> None:
        chain = skewed_chain(put_oi=100_000, call_oi=100_000)  # pcr = 1.0
        assert make_strategy().on_chain(contrarian_ctx(chain)) == []

    def test_no_entry_outside_dte_window(self) -> None:
        chain = skewed_chain(put_oi=200_000, call_oi=100_000)
        early = contrarian_ctx(chain, now=ist(date(2025, 7, 7), 10))
        assert make_strategy().on_chain(early) == []
        late = contrarian_ctx(chain, now=ist(date(2025, 7, 28), 10))
        assert make_strategy().on_chain(late) == []

    def test_no_entry_without_greeks(self) -> None:
        chain = marked_chain({(24000, OptionType.CALL): "150", (24000, OptionType.PUT): "140"})
        assert make_strategy().on_chain(contrarian_ctx(chain)) == []


class TestExit:
    def test_profit_target_exit(self) -> None:
        # Debit paid 7500 (75 units @ 100); close value 11250 -> 50% profit >= 40% target.
        ctx = contrarian_ctx(
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
        ctx = contrarian_ctx(
            marked_chain({(24400, OptionType.CALL): "50"}),
            positions=open_call_position("100"),
        )
        signals = make_strategy().on_chain(ctx)
        assert len(signals) == 1
        assert "stop loss" in signals[0].reason

    def test_holds_between_thresholds(self) -> None:
        # Close value 8250 vs debit 7500 -> 10% profit: neither target nor stop.
        ctx = contrarian_ctx(
            marked_chain({(24400, OptionType.CALL): "110"}),
            positions=open_call_position("100"),
        )
        assert make_strategy().on_chain(ctx) == []

    def test_expiry_proximity_exit_needs_no_marks(self) -> None:
        now = ist(date(2025, 7, 28), 10)
        ctx = contrarian_ctx(
            marked_chain({(25500, OptionType.CALL): "1"}, now=now),
            positions=open_call_position("100"),
            now=now,
        )
        signals = make_strategy().on_chain(ctx)
        assert len(signals) == 1
        assert "expiry proximity" in signals[0].reason
