"""Strategy registry: maps a strategy_type key to its implementing class."""

from collections.abc import Callable
from typing import Any, TypeVar

from alphaquant.core.exceptions import ConfigurationError
from alphaquant.domain import StrategyDefinition
from alphaquant.strategies.base import Strategy

S = TypeVar("S", bound=type[Strategy[Any]])

_REGISTRY: dict[str, type[Strategy[Any]]] = {}


def register(strategy_type: str) -> Callable[[S], S]:
    def decorator(cls: S) -> S:
        if strategy_type in _REGISTRY:
            raise ConfigurationError(f"strategy type {strategy_type!r} already registered")
        cls.strategy_type = strategy_type
        _REGISTRY[strategy_type] = cls
        return cls

    return decorator


def create(definition: StrategyDefinition) -> Strategy[Any]:
    """Instantiate the strategy class for `definition` (params are validated)."""
    try:
        cls = _REGISTRY[definition.strategy_type]
    except KeyError as exc:
        raise ConfigurationError(
            f"unknown strategy type {definition.strategy_type!r}; "
            f"available: {sorted(_REGISTRY)}"
        ) from exc
    return cls(definition)


def available_types() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def strategy_class(strategy_type: str) -> type[Strategy[Any]]:
    """The registered class for `strategy_type` (not an instance — no params to validate)."""
    try:
        return _REGISTRY[strategy_type]
    except KeyError as exc:
        raise ConfigurationError(
            f"unknown strategy type {strategy_type!r}; available: {sorted(_REGISTRY)}"
        ) from exc


def catalog_entries() -> tuple[dict[str, Any], ...]:
    """Every registered strategy as a plain dict (`strategy_type`, `class_name`, `description`,
    `params_schema`) — the shared basis for the dashboard's and LLM assistant's independently
    owned strategy-catalog DTOs (each package builds its own frozen model from these fields;
    neither imports the other)."""
    entries = []
    for strategy_type in available_types():
        cls = strategy_class(strategy_type)
        entries.append(
            {
                "strategy_type": strategy_type,
                "class_name": cls.__name__,
                "description": (cls.__doc__ or "").strip(),
                "params_schema": cls.params_model.model_json_schema(),
            }
        )
    return tuple(entries)
