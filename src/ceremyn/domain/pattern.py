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


class PatternTrackRecord(BaseModel):
    """One (pattern, direction) pair's full historical track record for a single
    symbol -- every pattern ever detected across its history, not just ones that
    fired on the latest bar (that narrower, cross-market view is `Opportunity`).
    Used for a deliberate, one-symbol "tell me everything you know" lookup."""

    model_config = ConfigDict(frozen=True)

    pattern_name: str = Field(min_length=1)
    direction: PatternDirection
    source: str = Field(min_length=1)
    # Whether this pattern fired on the symbol's own latest bar -- actionable
    # right now, as opposed to a historical occurrence with no current signal.
    active_now: bool
    occurrences: int = Field(ge=0)
    hit_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    average_forward_return_pct: float | None = None
    forward_days: int = Field(gt=0)
    # Whether this specific track record would clear find_opportunities' own
    # quality bar (min_occurrences/min_hit_rate/min_avg_forward_return_pct) --
    # lets a one-symbol lookup show its weaker patterns too, honestly labelled,
    # rather than silently hiding everything that isn't scan-grade.
    is_opportunity_grade: bool
