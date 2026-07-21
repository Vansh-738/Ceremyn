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


def strangle_ctx(iv_rank: float | None = None, **ctx_overrides: object) -> StrategyContext:
    defaults: dict[str, object] = {"chain": enriched_chain(), "iv_rank": iv_rank, "now": NOW}
    defaults.update(ctx_overrides)
    return StrategyContext.model_validate(defaults)


def make_strategy(**params: Any) -> Strategy[Any]:
    return create(make_definition("long_strangle", **params))


def open_positions(call_avg: str, put_avg: str) -> tuple[Position, ...]:
    call = make_contract(strike=24400, option_type=OptionType.CALL, expiry=EXPIRY)
    put = make_contract(strike=23600, option_type=OptionType.PUT, expiry=EXPIRY)
    return (
        Position(contract=call, quantity=75, avg_price=Decimal(call_avg)),
        Position(contract=put, quantity=75, avg_price=Decimal(put_avg)),
    )


class TestEntry:
    def test_enters_delta_targeted_strangle_with_no_iv_rank(self) -> None:
        signals = make_strategy().on_chain(strangle_ctx())
        assert len(signals) == 1
        signal = signals[0]
        assert signal.action is SignalAction.ENTER
        assert signal.strategy_id == "long_strangle_test"
        assert signal.underlying == "NIFTY"
        assert signal.expiry == EXPIRY
        assert signal.market_timestamp == NOW
        call_leg = next(leg for leg in signal.legs if leg.contract.is_call)
        put_leg = next(leg for leg in signal.legs if leg.contract.is_put)
        assert call_leg.side is Side.BUY and put_leg.side is Side.BUY
        assert put_leg.contract.strike < Decimal(24000) < call_leg.contract.strike
        assert "no margin" in signal.reason

    def test_no_iv_rank_gate_by_default(self) -> None:
        # `max_iv_rank` defaults to None: enters regardless of IV rank, unlike
        # `short_strangle`'s mandatory `min_iv_rank` gate.
        assert len(make_strategy().on_chain(strangle_ctx(iv_rank=5.0))) == 1
        assert len(make_strategy().on_chain(strangle_ctx(iv_rank=95.0))) == 1

    def test_max_iv_rank_blocks_entry_when_premium_already_rich(self) -> None:
        strategy = make_strategy(max_iv_rank=40.0)
        assert strategy.on_chain(strangle_ctx(iv_rank=80.0)) == []
        assert len(strategy.on_chain(strangle_ctx(iv_rank=20.0))) == 1

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
        # Debit paid 8250/unit; close value 13500 -> ~63.6% profit >= 50% target.
        ctx = strangle_ctx(
            chain=marked_chain({(24400, OptionType.CALL): "100", (23600, OptionType.PUT): "80"}),
            positions=open_positions("60", "50"),
        )
        signals = make_strategy().on_chain(ctx)
        assert len(signals) == 1
        assert signals[0].action is SignalAction.EXIT
        assert "profit target" in signals[0].reason
        assert all(leg.side is Side.SELL for leg in signals[0].legs)
        assert all(leg.lots == 1 for leg in signals[0].legs)

    def test_stop_loss_exit(self) -> None:
        # Debit paid 8250/unit; close value 3000 -> ~63.6% loss >= 50% stop.
        ctx = strangle_ctx(
            chain=marked_chain({(24400, OptionType.CALL): "20", (23600, OptionType.PUT): "20"}),
            positions=open_positions("60", "50"),
        )
        signals = make_strategy().on_chain(ctx)
        assert len(signals) == 1
        assert "stop loss" in signals[0].reason

    def test_holds_between_thresholds(self) -> None:
        # Debit paid 8250/unit; close value 9750 -> ~18.2% profit: neither target nor stop.
        ctx = strangle_ctx(
            chain=marked_chain({(24400, OptionType.CALL): "70", (23600, OptionType.PUT): "60"}),
            positions=open_positions("60", "50"),
        )
        assert make_strategy().on_chain(ctx) == []

    def test_expiry_proximity_exit_needs_no_marks(self) -> None:
        # DTE 1 (== default exit_dte): exits even without marks for the held strikes.
        now = ist(date(2025, 7, 28), 10)
        ctx = strangle_ctx(
            chain=marked_chain({(25500, OptionType.CALL): "1"}, now=now),
            positions=open_positions("60", "50"),
            now=now,
        )
        signals = make_strategy().on_chain(ctx)
        assert len(signals) == 1
        assert "expiry proximity" in signals[0].reason
