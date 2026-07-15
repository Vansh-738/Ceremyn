import pytest
from pydantic import ValidationError

from alphaquant.domain import OptionType, Side
from alphaquant.strategies.legs import LegSpec, resolve_leg, resolve_legs
from tests.unit.strategies.conftest import enriched_chain, marked_chain


class TestLegSpec:
    def test_delta_selection_requires_target_delta(self) -> None:
        with pytest.raises(ValidationError, match="target_delta"):
            LegSpec(option_type=OptionType.CALL, side=Side.SELL, selection="delta")

    def test_atm_selection_does_not_require_target_delta(self) -> None:
        spec = LegSpec(option_type=OptionType.CALL, side=Side.SELL, selection="atm")
        assert spec.target_delta is None

    def test_delta_selection_with_target_is_valid(self) -> None:
        spec = LegSpec(
            option_type=OptionType.PUT, side=Side.BUY, selection="delta", target_delta=0.15
        )
        assert spec.target_delta == 0.15


class TestResolveLeg:
    def test_delta_selection_finds_nearest_delta(self) -> None:
        chain = enriched_chain()
        spec = LegSpec(
            option_type=OptionType.CALL, side=Side.SELL, selection="delta", target_delta=0.20
        )
        entry = resolve_leg(chain, spec)
        assert entry is not None
        assert entry.contract.is_call
        assert entry.greeks is not None
        assert abs(abs(entry.greeks.delta) - 0.20) < 0.05

    def test_atm_selection_finds_atm_strike(self) -> None:
        chain = enriched_chain()
        spec = LegSpec(option_type=OptionType.PUT, side=Side.SELL, selection="atm")
        entry = resolve_leg(chain, spec)
        assert entry is not None
        assert entry.contract.strike == chain.atm_strike

    def test_returns_none_when_no_greeks_available(self) -> None:
        chain = marked_chain({(24000, OptionType.CALL): "100"})
        spec = LegSpec(
            option_type=OptionType.CALL, side=Side.SELL, selection="delta", target_delta=0.20
        )
        assert resolve_leg(chain, spec) is None


class TestResolveLegs:
    def test_resolves_every_leg_scaled_by_lots(self) -> None:
        chain = enriched_chain()
        specs = (
            LegSpec(option_type=OptionType.CALL, side=Side.SELL, selection="atm"),
            LegSpec(option_type=OptionType.PUT, side=Side.SELL, selection="atm"),
        )
        legs = resolve_legs(chain, specs, lots=3)
        assert legs is not None
        assert len(legs) == 2
        assert all(leg.lots == 3 for leg in legs)
        assert {leg.side for leg in legs} == {Side.SELL}

    def test_applies_lots_multiplier(self) -> None:
        chain = enriched_chain()
        specs = (
            LegSpec(option_type=OptionType.CALL, side=Side.BUY, selection="atm", lots_multiplier=2),
        )
        legs = resolve_legs(chain, specs, lots=3)
        assert legs is not None
        assert legs[0].lots == 6

    def test_none_when_any_leg_unresolvable(self) -> None:
        chain = marked_chain({(24000, OptionType.CALL): "100"})
        specs = (
            LegSpec(option_type=OptionType.CALL, side=Side.SELL, selection="atm"),
            LegSpec(
                option_type=OptionType.PUT, side=Side.SELL, selection="delta", target_delta=0.20
            ),
        )
        assert resolve_legs(chain, specs, lots=1) is None
