"""Strategy definition metadata.

The executable Strategy ABC lives in the strategies package (M3); the domain
only knows the descriptive record that identifies a strategy configuration —
enough for orders, journal entries, and backtest results to reference it.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrategyDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, pattern=r"^[a-z0-9_\-]+$")  # e.g. "short_strangle_v1"
    name: str = Field(min_length=1)
    version: str = "1"
    description: str = ""
    underlyings: tuple[str, ...] = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
