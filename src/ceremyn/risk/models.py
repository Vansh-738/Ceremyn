"""Risk-engine result models."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value


class RiskCategory(StrEnum):
    MARGIN = "margin"
    EXPOSURE = "exposure"
    LIQUIDITY = "liquidity"
    VOLATILITY = "volatility"
    PORTFOLIO_RISK = "portfolio_risk"
    CONCENTRATION = "concentration"
    TIME = "time"
    EVENT_RISK = "event_risk"


class RuleResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    category: RiskCategory
    passed: bool
    blocking: bool = True
    risk_level: float = Field(default=0.0, ge=0.0, le=1.0)
    message: str = ""
    violations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    required_actions: tuple[str, ...] = ()
    details: dict[str, Any] = Field(default_factory=dict)


class RiskDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    approved: bool
    risk_score: float = Field(ge=0.0, le=100.0)
    violations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    required_actions: tuple[str, ...] = ()
    rule_results: tuple[RuleResult, ...] = ()
    timestamp: datetime

    _aware = field_validator("timestamp")(_require_aware)
