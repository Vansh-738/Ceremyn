from dataclasses import dataclass, field
from decimal import Decimal

from alphaquant.domain import OptionType, Position, Side, SignalAction
from alphaquant.strategies import create
from alphaquant.strategies.base import StrategyContext
from alphaquant.strategies.common import mark_price
from alphaquant.strategies.legs import LegSpec
from alphaquant.strategies.multi_leg import drive
from alphaquant.strategies.rules import AdjustmentRule, EntryFilter, ExitRule
from tests.unit.domain.conftest import make_contract
from tests.unit.strategies.conftest import (
    EXPIRY,
    NOW,
    enriched_chain,
    make_definition,
    marked_chain,
)


@dataclass(frozen=True)
class _FakeParams:
    lots: int = 1
    legs: tuple[LegSpec, ...] = (
        LegSpec(option_type=OptionType.CALL, side=Side.SELL, selection="atm"),
    )
    entry: EntryFilter = field(default_factory=EntryFilter)
    exit_rule: ExitRule = field(default_factory=ExitRule)
    adjustment: AdjustmentRule = field(default_factory=AdjustmentRule)


def _ctx(**overrides: object) -> StrategyContext:
    defaults: dict[str, object] = {"chain": enriched_chain(), "iv_rank": 80.0, "now": NOW}
    defaults.update(overrides)
    return StrategyContext.model_validate(defaults)


def _strategy() -> object:
    # Any registered Strategy instance works as `drive()`'s `self` — it only uses `.emit()`
    # and `.definition`, never its own `on_chain`.
    return create(make_definition("short_straddle"))


class TestDriveEntry:
    def test_enters_when_flat_and_allowed(self) -> None:
        signals = drive(_strategy(), _ctx(), _FakeParams())
        assert len(signals) == 1
        assert signals[0].action is SignalAction.ENTER
        assert len(signals[0].legs) == 1

    def test_no_entry_when_filter_rejects(self) -> None:
        params = _FakeParams(entry=EntryFilter(min_iv_rank=90.0))
        assert drive(_strategy(), _ctx(iv_rank=80.0), params) == []

    def test_no_entry_when_legs_unresolvable(self) -> None:
        params = _FakeParams(
            legs=(
                LegSpec(
                    option_type=OptionType.CALL,
                    side=Side.SELL,
                    selection="delta",
                    target_delta=0.20,
                ),
            )
        )
        chain = marked_chain({(24000, OptionType.CALL): "100"})  # no greeks
        assert drive(_strategy(), _ctx(chain=chain), params) == []

    def test_entry_reason_mentions_iv_rank(self) -> None:
        signals = drive(_strategy(), _ctx(iv_rank=72.0), _FakeParams())
        assert "IV rank 72" in signals[0].reason


class TestDriveExit:
    def test_exits_on_profit_target(self) -> None:
        position = Position(
            contract=make_contract(strike=24000, option_type=OptionType.CALL, expiry=EXPIRY),
            quantity=-75,
            avg_price=Decimal("100"),
        )
        chain = marked_chain({(24000, OptionType.CALL): "40"})
        ctx = _ctx(chain=chain, positions=(position,))
        params = _FakeParams(exit_rule=ExitRule(profit_target_pct=50.0))

        signals = drive(_strategy(), ctx, params)

        assert len(signals) == 1
        assert signals[0].action is SignalAction.EXIT

    def test_no_signal_when_holding(self) -> None:
        position = Position(
            contract=make_contract(strike=24000, option_type=OptionType.CALL, expiry=EXPIRY),
            quantity=-75,
            avg_price=Decimal("100"),
        )
        chain = marked_chain({(24000, OptionType.CALL): "95"})  # tiny move
        ctx = _ctx(chain=chain, positions=(position,))
        assert drive(_strategy(), ctx, _FakeParams()) == []


class TestDriveAdjustment:
    def test_adjusts_when_exit_silent_and_adjustment_enabled(self) -> None:
        chain = enriched_chain()
        atm_entry = chain.get(chain.atm_strike, OptionType.CALL)
        assert atm_entry is not None
        mark = mark_price(atm_entry)
        assert mark is not None
        position = Position(contract=atm_entry.contract, quantity=-75, avg_price=mark)
        ctx = _ctx(chain=chain, positions=(position,))
        params = _FakeParams(adjustment=AdjustmentRule(enabled=True, breach_delta=0.35))

        signals = drive(_strategy(), ctx, params)

        assert len(signals) == 1
        assert signals[0].action is SignalAction.ADJUST
        assert len(signals[0].legs) == 2

    def test_no_signal_when_adjustment_disabled_and_no_exit(self) -> None:
        chain = enriched_chain()
        atm_entry = chain.get(chain.atm_strike, OptionType.CALL)
        assert atm_entry is not None
        mark = mark_price(atm_entry)
        assert mark is not None
        position = Position(contract=atm_entry.contract, quantity=-75, avg_price=mark)
        ctx = _ctx(chain=chain, positions=(position,))
        assert drive(_strategy(), ctx, _FakeParams()) == []
