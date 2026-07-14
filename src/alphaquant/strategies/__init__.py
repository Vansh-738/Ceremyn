"""Strategy engine.

Strategies observe enriched option chains and emit Signals — intents, never
orders. They have no broker handle and cannot import the execution layer.
Importing this package registers the built-in strategies.
"""

from alphaquant.strategies import expiry_day_theta, iron_condor, short_strangle  # noqa: F401
from alphaquant.strategies.base import Strategy, StrategyContext
from alphaquant.strategies.registry import available_types, create

__all__ = ["Strategy", "StrategyContext", "available_types", "create"]
