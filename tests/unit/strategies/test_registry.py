import pytest

from ceremyn.core.exceptions import ConfigurationError
from ceremyn.strategies import Strategy, available_types, create
from ceremyn.strategies.base import StrategyContext
from ceremyn.strategies.registry import catalog_entries, register, strategy_class
from tests.unit.strategies.conftest import make_definition


def test_available_types_includes_all_registered_strategies() -> None:
    types = available_types()
    assert types == tuple(sorted(types))  # sorted, per available_types()'s contract
    for expected in (
        "iron_condor",
        "short_strangle",
        "expiry_day_theta",
        "iron_fly",
        "short_straddle",
        "vertical_spread",
        "bull_put_spread",
        "bear_call_spread",
        "calendar_spread",
    ):
        assert expected in types


def test_strategy_class_returns_the_registered_class() -> None:
    cls = strategy_class("iron_condor")
    assert cls.__name__ == "IronCondor"


def test_strategy_class_unknown_type_raises() -> None:
    with pytest.raises(ConfigurationError, match="unknown strategy type"):
        strategy_class("does_not_exist")


def test_create_unknown_type_raises() -> None:
    with pytest.raises(ConfigurationError, match="unknown strategy type"):
        create(make_definition("does_not_exist"))


def test_register_rejects_duplicate_strategy_type() -> None:
    with pytest.raises(ConfigurationError, match="already registered"):

        @register("iron_condor")
        class _Dummy(Strategy[object]):  # type: ignore[type-var]
            def on_chain(self, ctx: StrategyContext) -> list[object]:
                return []


def test_catalog_entries_covers_every_registered_type() -> None:
    entries = catalog_entries()
    assert len(entries) == len(available_types())
    by_type = {entry["strategy_type"]: entry for entry in entries}
    assert set(by_type) == set(available_types())
    iron_condor_entry = by_type["iron_condor"]
    assert iron_condor_entry["class_name"] == "IronCondor"
    assert "properties" in iron_condor_entry["params_schema"]
