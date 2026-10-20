"""Strategy engine.

Strategies observe enriched option chains and emit Signals — intents, never
orders. They have no broker handle and cannot import the execution layer.
Importing this package registers the built-in strategies.
"""

from ceremyn.strategies import (  # noqa: F401
    bear_call_spread,
    broken_wing_butterfly,
    bull_put_spread,
    calendar_spread,
    equity_pattern,
    expiry_day_theta,
    iron_condor,
    iron_fly,
    jade_lizard,
    long_contrarian,
    long_skew,
    long_strangle,
    max_pain_reversion,
    short_straddle,
    short_strangle,
    vertical_spread,
)
from ceremyn.strategies.base import Strategy, StrategyContext
from ceremyn.strategies.registry import (
    available_types,
    catalog_entries,
    create,
    strategy_class,
)

__all__ = [
    "Strategy",
    "StrategyContext",
    "available_types",
    "catalog_entries",
    "create",
    "strategy_class",
]
