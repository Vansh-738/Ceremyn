from datetime import date
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
    ist,
    make_definition,
    marked_chain,
)


def strangle_ctx(iv_rank: float | None = 80.0, **ctx_overrides: object) -> StrategyContext:
    defaults: dict[str, object] = {"chain": enriched_chain(), "iv_rank": iv_rank, "now": NOW}
    defaults.update(ctx_overrides)
    return StrategyContext.model_validate(defaults)


def make_strategy() -> Strategy[Any]:
    return create(make_definition("short_strangle"))


def open_positions(call_avg: str, put_avg: str) -> tuple[Position, ...]:
    call = make_contract(strike=24400, option_type=OptionType.CALL, expiry=EXPIRY)
    put = make_contract(strike=23600, option_type=OptionType.PUT, expiry=EXPIRY)
    return (
        Position(contract=call, quantity=-75, avg_price=Decimal(call_avg)),
        Position(contract=put, quantity=-75, avg_price=Decimal(put_avg)),
    )


class TestEntry:
    def test_enters_delta_targeted_strangle(self) -> None:
        signals = make_strategy().on_chain(strangle_ctx())
        assert len(signals) == 1
        signal = signals[0]
        assert signal.action is SignalAction.ENTER
        assert signal.strategy_id == "short_strangle_test"
        assert signal.strategy_version == "1"
        assert signal.underlying == "NIFTY"
        assert signal.expiry == EXPIRY
        assert signal.market_timestamp == NOW
        call_leg = next(leg for leg in signal.legs if leg.contract.is_call)
        put_leg = next(leg for leg in signal.legs if leg.contract.is_put)
        assert call_leg.side is Side.SELL and put_leg.side is Side.SELL
        assert put_leg.contract.strike < Decimal(24000) < call_leg.contract.strike
        assert "IV rank 80" in signal.reason

    def test_selected_strikes_are_deterministic(self) -> None:
        first = make_strategy().on_chain(strangle_ctx())
        second = make_strategy().on_chain(strangle_ctx())
        assert [leg.contract.strike for leg in first[0].legs] == [
            leg.contract.strike for leg in second[0].legs
        ]

    def test_no_entry_when_iv_rank_low_or_missing(self) -> None:
        assert make_strategy().on_chain(strangle_ctx(iv_rank=30.0)) == []
        assert make_strategy().on_chain(strangle_ctx(iv_rank=None)) == []

    def test_no_entry_outside_dte_window(self) -> None:
        # DTE 22 with default window [3, 15].
        early = strangle_ctx(now=ist(date(2025, 7, 7), 10))
        assert make_strategy().on_chain(early) == []
        # DTE 1 is below entry_dte_min.
        late = strangle_ctx(now=ist(date(2025, 7, 28), 10))
        assert make_strategy().on_chain(late) == []

    def test_no_entry_without_greeks(self) -> None:
        chain = marked_chain({(24000, OptionType.CALL): "150", (24000, OptionType.PUT): "140"})
        assert make_strategy().on_chain(strangle_ctx(chain=chain)) == []


class TestExit:
    def test_profit_target_exit(self) -> None:
        # Credit 290/unit; close cost 130/unit -> 55% profit >= 50% target.
        ctx = strangle_ctx(
            chain=marked_chain({(24400, OptionType.CALL): "60", (23600, OptionType.PUT): "70"}),
            positions=open_positions("150", "140"),
        )
        signals = make_strategy().on_chain(ctx)
        assert len(signals) == 1
        assert signals[0].action is SignalAction.EXIT
        assert "profit target" in signals[0].reason
        assert all(leg.side is Side.BUY for leg in signals[0].legs)
        assert all(leg.lots == 1 for leg in signals[0].legs)

    def test_stop_loss_exit(self) -> None:
        # Close cost 600/unit vs credit 290 -> ~107% loss >= 100% stop.
        ctx = strangle_ctx(
            chain=marked_chain({(24400, OptionType.CALL): "400", (23600, OptionType.PUT): "200"}),
            positions=open_positions("150", "140"),
        )
        signals = make_strategy().on_chain(ctx)
        assert len(signals) == 1
        assert "stop loss" in signals[0].reason

    def test_holds_between_thresholds(self) -> None:
        # Close cost 220 vs credit 290 -> 24% profit: neither target nor stop.
        ctx = strangle_ctx(
            chain=marked_chain({(24400, OptionType.CALL): "120", (23600, OptionType.PUT): "100"}),
            positions=open_positions("150", "140"),
        )
        assert make_strategy().on_chain(ctx) == []

    def test_expiry_proximity_exit_needs_no_marks(self) -> None:
        # DTE 1 (== default exit_dte): exits even without marks for the held strikes.
        now = ist(date(2025, 7, 28), 10)
        ctx = strangle_ctx(
            chain=marked_chain({(25500, OptionType.CALL): "1"}, now=now),
            positions=open_positions("150", "140"),
            now=now,
        )
        signals = make_strategy().on_chain(ctx)
        assert len(signals) == 1
        assert "expiry proximity" in signals[0].reason
