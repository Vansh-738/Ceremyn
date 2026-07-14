"""Feature registry: the catalog of available named features.

Features register a default instance under their stable name. The registry mirrors
the strategy/risk registry pattern. ``register`` is used as a decorator on Feature
subclasses that take no constructor arguments; parameterized families register their
default instances explicitly via ``default_registry.add(...)``.
"""

from typing import TypeVar

from alphaquant.core.exceptions import ConfigurationError
from alphaquant.features.base import Feature

F = TypeVar("F", bound=type[Feature])


class FeatureRegistry:
    def __init__(self) -> None:
        self._features: dict[str, Feature] = {}

    def add(self, feature: Feature) -> Feature:
        if feature.name in self._features:
            raise ConfigurationError(f"feature {feature.name!r} already registered")
        self._features[feature.name] = feature
        return feature

    def get(self, name: str) -> Feature:
        try:
            return self._features[name]
        except KeyError as exc:
            raise ConfigurationError(
                f"unknown feature {name!r}; available: {self.available()}"
            ) from exc

    def available(self) -> tuple[str, ...]:
        return tuple(sorted(self._features))

    def all_features(self) -> tuple[Feature, ...]:
        return tuple(self._features[name] for name in self.available())


default_registry = FeatureRegistry()


def register(cls: F) -> F:
    """Class decorator: register a default (zero-arg) instance of a Feature."""
    default_registry.add(cls())
    return cls
