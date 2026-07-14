import pytest
from pydantic import ValidationError

from alphaquant.research.parameter_grid import (
    ParameterGrid,
    ParameterGridError,
    random_search_samples,
    sweep,
)


class TestParameterGrid:
    def test_size_is_cartesian_product(self) -> None:
        grid = ParameterGrid(space={"a": (1, 2, 3), "b": (10, 20)})
        assert grid.size() == 6

    def test_empty_space_size_zero(self) -> None:
        assert ParameterGrid(space={}).size() == 0
        assert list(ParameterGrid(space={}).combinations()) == []

    def test_combinations_enumerated(self) -> None:
        grid = ParameterGrid(space={"a": (1, 2), "b": (10,)})
        combos = list(grid.combinations())
        assert combos == [{"a": 1, "b": 10}, {"a": 2, "b": 10}]

    def test_supports_large_scales(self) -> None:
        # 10 x 10 x 10 = 1,000 combinations under the default cap.
        tens = tuple(range(10))
        grid = ParameterGrid(space={"a": tens, "b": tens, "c": tens})
        assert grid.size() == 1000
        assert sum(1 for _ in grid.combinations()) == 1000

    def test_cap_enforced(self) -> None:
        grid = ParameterGrid(space={"a": tuple(range(200))}, max_combinations=100)
        with pytest.raises(ParameterGridError, match="exceeding the cap"):
            list(grid.combinations())

    def test_empty_values_rejected(self) -> None:
        # ParameterGridError is raised in the validator; pydantic wraps it.
        with pytest.raises(ValidationError, match="no candidate values"):
            ParameterGrid(space={"a": ()})


class TestRandomSearch:
    def test_deterministic_for_seed(self) -> None:
        space = {"a": [1, 2, 3, 4, 5], "b": [10, 20, 30]}
        first = random_search_samples(space, n=5, seed=42)
        second = random_search_samples(space, n=5, seed=42)
        assert first == second

    def test_different_seeds_differ(self) -> None:
        space = {"a": list(range(20)), "b": list(range(20))}
        assert random_search_samples(space, n=8, seed=1) != random_search_samples(
            space, n=8, seed=2
        )

    def test_samples_are_unique(self) -> None:
        samples = random_search_samples({"a": [1, 2, 3]}, n=10, seed=1)
        # Only 3 unique combinations exist; dedup caps the result.
        assert len(samples) == 3
        assert all(s in [{"a": 1}, {"a": 2}, {"a": 3}] for s in samples)

    def test_requires_positive_n(self) -> None:
        with pytest.raises(ParameterGridError, match="n must be positive"):
            random_search_samples({"a": [1]}, n=0)

    def test_empty_values_rejected(self) -> None:
        with pytest.raises(ParameterGridError, match="no candidate values"):
            random_search_samples({"a": []}, n=3)


class TestSweep:
    def test_single_parameter_values(self) -> None:
        assert sweep("lots", [1, 2, 3]) == [{"lots": 1}, {"lots": 2}, {"lots": 3}]

    def test_empty_values_rejected(self) -> None:
        with pytest.raises(ParameterGridError, match="at least one value"):
            sweep("lots", [])
