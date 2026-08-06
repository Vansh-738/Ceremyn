"""Detected market patterns -- additive, read-only market intelligence.

A `Pattern` is purely descriptive evidence about a market condition (e.g. a
candlestick formation). It carries no obligation to become a trading decision: it
is not a `Signal`, has no legs/quantities/side, and has no path to the OMS. Only a
`Signal`, produced by a versioned `Strategy`, may reach `OrderManagementEngine.
submit_signal` -- see ARCHITECTURE_DECISIONS.md / ROADMAP_V2.md §3.8 and §5.1.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ceremyn.domain.enums import PatternDirection
from ceremyn.domain.market_data import _require_aware


class Pattern(BaseModel):
    """One detected occurrence of a named pattern on one instrument, at one instant."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    tradingsymbol: str = Field(min_length=1)
    detected_at: datetime
    direction: PatternDirection
    # Which detector family found this (e.g. "candlestick") -- lets future detector
    # families (chart-shape patterns, etc.) coexist without changing this type.
    source: str = Field(min_length=1)

    _aware = field_validator("detected_at")(_require_aware)
