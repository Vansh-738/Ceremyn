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
    enriched_chain,
    ist,
    make_definition,
    marked_chain,
)


def make_strategy(**params: Any) -> Strategy[Any]:
    return create(make_definition("expiry_day_theta", **params))


def expiry_day_ctx(hour: int, minute: int = 0, **overrides: object) -> StrategyContext:
    now = ist(EXPIRY, hour, minute)
    defaults: dict[str, object] = {"now": now}
    defaults.update(overrides)
    if "chain" not in defaults:
        defaults["chain"] = enriched_chain(now=now, expiry=EXPIRY)
    return StrategyContext.model_validate(defaults)


def straddle_positions(avg: str = "120") -> tuple[Position, ...]:
    return tuple(
        Position(
            contract=make_contract(strike=24000, option_type=ot, expiry=EXPIRY),
            quantity=-75,
            avg_price=Decimal(avg),
        )
        for ot in (OptionType.CALL, OptionType.PUT)
    )


class TestEntry:
    def test_enters_atm_straddle_in_window(self) -> None:
        signals = make_strategy().on_chain(expiry_day_ctx(10, 30))
        assert len(signals) == 1
        signal = signals[0]
        assert signal.action is SignalAction.ENTER
        assert len(signal.legs) == 2
        assert all(leg.side is Side.SELL for leg in signal.legs)
        assert {leg.contract.strike for leg in signal.legs} == {Decimal(24000)}
        assert {leg.contract.option_type for leg in signal.legs} == {
            OptionType.CALL,
            OptionType.PUT,
        }

    def test_no_entry_before_window(self) -> None:
        assert make_strategy().on_chain(expiry_day_ctx(9, 30)) == []

    def test_no_entry_after_exit_time(self) -> None:
        assert make_strategy().on_chain(expiry_day_ctx(14, 45)) == []

    def test_inactive_on_non_expiry_days(self) -> None:
        now = ist(EXPIRY.replace(day=24), 10, 30)  # DTE 5
        ctx = StrategyContext(chain=enriched_chain(now=now), now=now)
        assert make_strategy().on_chain(ctx) == []

    def test_window_params_validated(self) -> None:
        with pytest.raises(ValidationError, match="entry_after"):
            make_strategy(entry_after="15:00", exit_by="10:00")


class TestExit:
    def test_time_exit(self) -> None:
        ctx = expiry_day_ctx(14, 30, positions=straddle_positions())
        signals = make_strategy().on_chain(ctx)
        assert len(signals) == 1
        assert signals[0].action is SignalAction.EXIT
        assert "time exit" in signals[0].reason
        assert all(leg.side is Side.BUY for leg in signals[0].legs)

    def test_profit_exit_before_time(self) -> None:
        # Credit 240/unit; marks 40+40=80 -> 66% >= 60% target.
        chain = marked_chain(
            {(24000, OptionType.CALL): "40", (24000, OptionType.PUT): "40"},
            now=ist(EXPIRY, 12),
            expiry=EXPIRY,
        )
        ctx = expiry_day_ctx(12, chain=chain, positions=straddle_positions("120"))
        signals = make_strategy().on_chain(ctx)
        assert len(signals) == 1
        assert "profit target" in signals[0].reason

    def test_stop_exit(self) -> None:
        # Marks 200+140=340 vs credit 240 -> ~42% loss >= 40% stop.
        chain = marked_chain(
            {(24000, OptionType.CALL): "200", (24000, OptionType.PUT): "140"},
            now=ist(EXPIRY, 12),
            expiry=EXPIRY,
        )
        ctx = expiry_day_ctx(12, chain=chain, positions=straddle_positions("120"))
        signals = make_strategy().on_chain(ctx)
        assert len(signals) == 1
        assert "stop loss" in signals[0].reason

    def test_holds_when_flat_pnl(self) -> None:
        chain = marked_chain(
            {(24000, OptionType.CALL): "110", (24000, OptionType.PUT): "115"},
            now=ist(EXPIRY, 12),
            expiry=EXPIRY,
        )
        ctx = expiry_day_ctx(12, chain=chain, positions=straddle_positions("120"))
        assert make_strategy().on_chain(ctx) == []
