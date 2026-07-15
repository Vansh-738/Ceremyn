"""New read-only DTOs for the few things no existing view already covers: a single
experiment's full statistics, time-windowed recaps, and the strategy catalog. Everything
here is a frozen, primitive-only pydantic model — no imports beyond `domain`/pydantic/stdlib,
so nothing here can ever create a transitive path to `risk` or `execution`.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from alphaquant.domain.market_data import _require_aware


class ExperimentDetailBrief(BaseModel):
    """Full statistics for one experiment — beyond `ResearchView`'s leaderboard columns."""

    model_config = ConfigDict(frozen=True)

    experiment_id: str = Field(min_length=1)
    strategy_name: str = Field(min_length=1)
    strategy_version: str = "1"
    parameters: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime
    total_return: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    calmar: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    cagr: float = 0.0
    win_rate: float = 0.0
    trade_count: int = 0
    notes: str = ""

    _aware = field_validator("timestamp")(_require_aware)


class RecapBrief(BaseModel):
    """A time-windowed summary of trading activity (today, or the current session)."""

    model_config = ConfigDict(frozen=True)

    window_label: str = Field(min_length=1)  # "today" | "this session"
    window_start: datetime
    window_end: datetime
    orders_submitted: int = 0
    orders_filled: int = 0
    orders_rejected: int = 0
    net_pnl: float = 0.0
    risk_violations: int = 0
    notable_events: tuple[str, ...] = ()

    _aware_start = field_validator("window_start")(_require_aware)
    _aware_end = field_validator("window_end")(_require_aware)


class StrategyCatalogEntry(BaseModel):
    """One registered strategy type, for strategy-explanation questions."""

    model_config = ConfigDict(frozen=True)

    strategy_type: str = Field(min_length=1)
    class_name: str = Field(min_length=1)
    description: str = ""
    params_schema: dict[str, Any] = Field(default_factory=dict)
