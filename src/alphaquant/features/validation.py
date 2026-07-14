"""Feature output validation.

Each feature name maps to an output constraint (numeric bounds or an allowed set of
categorical labels). The validator checks computed values before they enter a
FeatureSet, so a broken computation surfaces loudly instead of silently poisoning
downstream consumers. Null values are always allowed (a feature may be uncomputable).
"""

from collections.abc import Iterable

from alphaquant.core.exceptions import AlphaQuantError
from alphaquant.features.models import FeatureScalar, FeatureValue


class FeatureValidationError(AlphaQuantError):
    """A computed feature value violated its declared constraint."""


class Bounds:
    """A numeric constraint: value must lie within [low, high] (inclusive)."""

    def __init__(self, low: float | None = None, high: float | None = None) -> None:
        self.low = low
        self.high = high

    def check(self, name: str, value: FeatureScalar) -> None:
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise FeatureValidationError(f"{name}: expected a number, got {value!r}")
        number = float(value)
        if self.low is not None and number < self.low:
            raise FeatureValidationError(f"{name}: {number} below minimum {self.low}")
        if self.high is not None and number > self.high:
            raise FeatureValidationError(f"{name}: {number} above maximum {self.high}")


class Categorical:
    """A categorical constraint: value must be one of `allowed`."""

    def __init__(self, allowed: Iterable[str]) -> None:
        self.allowed = frozenset(allowed)

    def check(self, name: str, value: FeatureScalar) -> None:
        if value not in self.allowed:
            raise FeatureValidationError(
                f"{name}: {value!r} not in allowed set {sorted(self.allowed)}"
            )


class FeatureValidator:
    def __init__(self) -> None:
        self._constraints: dict[str, Bounds | Categorical] = {}

    def set_constraint(self, name: str, constraint: Bounds | Categorical) -> None:
        self._constraints[name] = constraint

    def validate(self, value: FeatureValue) -> FeatureValue:
        """Validate a value against its registered constraint; pass through nulls."""
        if value.is_null:
            return value
        constraint = self._constraints.get(value.name)
        if constraint is not None:
            constraint.check(value.name, value.value)
        return value

    def has_constraint(self, name: str) -> bool:
        return name in self._constraints
