"""Parameter space enumeration and sampling for optimization.

- ``ParameterGrid`` — full Cartesian product (grid search / parameter sweep).
- ``random_search_samples`` — deterministic random sampling of the space.
- ``sweep`` — vary a single parameter over a list of values.

A configurable ``max_combinations`` guard makes the 100 / 1,000 / 10,000 combination
scales explicit and prevents an accidental combinatorial explosion.
"""

import random
from collections.abc import Iterator, Sequence
from itertools import product
from math import prod
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_MAX_COMBINATIONS = 10_000


class ParameterGridError(ValueError):
    """Raised when a parameter space is invalid or exceeds the combination cap."""


class ParameterGrid(BaseModel):
    """A named parameter -> candidate-values mapping enumerated as a Cartesian product."""

    model_config = ConfigDict(frozen=True)

    space: dict[str, tuple[Any, ...]] = Field(default_factory=dict)
    max_combinations: int = Field(default=DEFAULT_MAX_COMBINATIONS, gt=0)

    def model_post_init(self, _context: Any) -> None:
        for name, values in self.space.items():
            if not values:
                raise ParameterGridError(f"parameter {name!r} has no candidate values")

    def size(self) -> int:
        if not self.space:
            return 0
        return prod(len(values) for values in self.space.values())

    def combinations(self) -> Iterator[dict[str, Any]]:
        """Yield every parameter combination, guarded by ``max_combinations``."""
        total = self.size()
        if total > self.max_combinations:
            raise ParameterGridError(
                f"grid has {total} combinations, exceeding the cap of {self.max_combinations}; "
                f"raise max_combinations or use random_search_samples"
            )
        if not self.space:
            return
        keys = tuple(self.space)
        for values in product(*(self.space[key] for key in keys)):
            yield dict(zip(keys, values, strict=True))


def random_search_samples(
    space: dict[str, Sequence[Any]],
    *,
    n: int,
    seed: int = 7,
) -> list[dict[str, Any]]:
    """Draw ``n`` deterministic random samples from the parameter space.

    Sampling is with replacement across draws but de-duplicated, so the result has at
    most ``min(n, |space|)`` unique combinations. Fully reproducible for a given seed.
    """
    if n <= 0:
        raise ParameterGridError("n must be positive")
    for name, values in space.items():
        if not values:
            raise ParameterGridError(f"parameter {name!r} has no candidate values")
    rng = random.Random(seed)
    keys = tuple(space)
    seen: set[tuple[Any, ...]] = set()
    samples: list[dict[str, Any]] = []
    max_unique = prod(len(space[key]) for key in keys) if keys else 0
    attempts = 0
    attempt_cap = n * 20 + 50
    while len(samples) < n and len(seen) < max_unique and attempts < attempt_cap:
        attempts += 1
        choice = tuple(rng.choice(list(space[key])) for key in keys)
        if choice in seen:
            continue
        seen.add(choice)
        samples.append(dict(zip(keys, choice, strict=True)))
    return samples


def sweep(parameter: str, values: Sequence[Any]) -> list[dict[str, Any]]:
    """Vary a single parameter over ``values`` (one-dimensional parameter sweep)."""
    if not values:
        raise ParameterGridError(f"sweep of {parameter!r} needs at least one value")
    return [{parameter: value} for value in values]
