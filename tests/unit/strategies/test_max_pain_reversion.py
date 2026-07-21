from datetime import date
from decimal import Decimal
from typing import Any

from ceremyn.domain import OptionType, Position, Side, SignalAction
from ceremyn.strategies import Strategy, create
from ceremyn.strategies.base import StrategyContext
from tests.unit.domain.conftest import make_contract
from tests.unit.strategies.conftest import (
    EXPIRY,
    enriched_chain,
    ist,
    make_definition,
    marked_chain,
)

# Default entry window is DTE 1-7 (max-pain drift is a near-expiry effect);
# the shared NOW (DTE 8) sits outside it, so these tests pin DTE 6.
NOW_DTE6 = ist(date(2025, 7, 23), 10)


def reversion_ctx(chain: Any = None, **ctx_overrides: object) -> StrategyContext:
    defaults: dict[str, object] = {"chain": chain or enriched_chain(now=NOW_DTE6), "now": NOW_DTE6}
    defaults.update(ctx_overrides)
    return StrategyContext.model_validate(defaults)


def make_strategy(**params: Any) -> Strategy[Any]:
    return create(make_definition("max_pain_reversion", **params))


def open_put_position(avg: str) -> tuple[Position, ...]:
    put = make_contract(strike=23800, option_type=OptionType.PUT, expiry=EXPIRY)
    return (Position(contract=put, quantity=75, avg_price=Decimal(avg)),)


class TestEntry:
    def test_spot_above_max_pain_buys_a_put(self) -> None:
        # Uniform OI over strikes 22500-25500 puts max pain ~24000; spot 24500 is
        # ~+2% above it -> expected drift down -> long put.
        chain = enriched_chain(spot=24500, now=NOW_DTE6)
        signals = make_strategy().on_chain(reversion_ctx(chain))
        assert len(signals) == 1
        signal = signals[0]
        assert signal.action is SignalAction.ENTER
        assert signal.strategy_id == "max_pain_reversion_test"
        leg = signal.legs[0]
        assert leg.contract.is_put
        assert leg.side is Side.BUY
        assert "max pain" in signal.reason

    def test_spot_below_max_pain_buys_a_call(self) -> None:
        chain = enriched_chain(spot=23500, now=NOW_DTE6)
        signals = make_strategy().on_chain(reversion_ctx(chain))
        assert len(signals) == 1
        leg = signals[0].legs[0]
        assert leg.contract.is_call
        assert leg.side is Side.BUY

    def test_no_entry_when_spot_is_near_max_pain(self) -> None:
        chain = enriched_chain(spot=24000, now=NOW_DTE6)
        assert make_strategy().on_chain(reversion_ctx(chain)) == []

    def test_no_entry_outside_dte_window(self) -> None:
        # DTE 8 with the default window [1, 7].
        late_now = ist(date(2025, 7, 21), 10)
        chain = enriched_chain(spot=24500, now=late_now)
        assert make_strategy().on_chain(reversion_ctx(chain, now=late_now)) == []

    def test_no_entry_without_greeks(self) -> None:
        chain = marked_chain(
            {(24000, OptionType.CALL): "150", (24000, OptionType.PUT): "140"},
            spot=24500,
            now=NOW_DTE6,
        )
        assert make_strategy().on_chain(reversion_ctx(chain)) == []


class TestExit:
    def test_profit_target_exit(self) -> None:
        # Debit paid 7500 (75 units @ 100); close value 11250 -> 50% profit >= 40%.
        ctx = reversion_ctx(
            marked_chain({(23800, OptionType.PUT): "150"}, now=NOW_DTE6),
            positions=open_put_position("100"),
        )
        signals = make_strategy().on_chain(ctx)
        assert len(signals) == 1
        assert signals[0].action is SignalAction.EXIT
        assert "profit target" in signals[0].reason
        assert signals[0].legs[0].side is Side.SELL

    def test_stop_loss_exit(self) -> None:
        # Debit paid 7500; close value 3750 -> 50% loss >= 40% stop.
        ctx = reversion_ctx(
            marked_chain({(23800, OptionType.PUT): "50"}, now=NOW_DTE6),
            positions=open_put_position("100"),
        )
        signals = make_strategy().on_chain(ctx)
        assert len(signals) == 1
        assert "stop loss" in signals[0].reason

    def test_holds_between_thresholds(self) -> None:
        # Close value 8250 vs debit 7500 -> 10% profit: neither target nor stop.
        ctx = reversion_ctx(
            marked_chain({(23800, OptionType.PUT): "110"}, now=NOW_DTE6),
            positions=open_put_position("100"),
        )
        assert make_strategy().on_chain(ctx) == []

    def test_expiry_day_exit_needs_no_marks(self) -> None:
        # DTE 0 (== default exit_dte): exits even without marks for the held strike.
        now = ist(date(2025, 7, 29), 10)
        ctx = reversion_ctx(
            marked_chain({(25500, OptionType.CALL): "1"}, now=now),
            positions=open_put_position("100"),
            now=now,
        )
        signals = make_strategy().on_chain(ctx)
        assert len(signals) == 1
        assert "expiry proximity" in signals[0].reason
