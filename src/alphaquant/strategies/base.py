"""Strategy ABC and the context object strategies observe.

The same on_chain interface is driven by the backtester, the paper trader, and
(eventually) the live trader — a strategy cannot tell which mode it runs in.
"""

from abc import ABC, abstractmethod
from datetime import datetime, time
from typing import Any, ClassVar, Generic, TypeVar, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from alphaquant.core.timeutils import to_ist
from alphaquant.domain import (
    OptionChainSnapshot,
    PortfolioSnapshot,
    Position,
    Signal,
    SignalLeg,
    StrategyDefinition,
)
from alphaquant.domain.enums import SignalAction

P = TypeVar("P", bound=BaseModel)


class StrategyContext(BaseModel):
    """Everything a strategy may look at when deciding.

    `positions` are the strategy's own open positions (in the observed chain's
    underlying), maintained by whichever runner drives the strategy.
    """

    model_config = ConfigDict(frozen=True)

    chain: OptionChainSnapshot  # enriched: entries carry greeks where priceable
    positions: tuple[Position, ...] = ()
    portfolio: PortfolioSnapshot | None = None
    iv_rank: float | None = None  # vs this underlying's IV history, 0..100
    now: datetime

    @field_validator("now")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _sync_positions(self) -> "StrategyContext":
        if self.portfolio is not None and not self.positions:
            object.__setattr__(self, "positions", self.portfolio.positions)
        return self

    @property
    def days_to_expiry(self) -> int:
        return (self.chain.expiry - to_ist(self.now).date()).days

    @property
    def time_ist(self) -> time:
        return to_ist(self.now).time()

    @property
    def has_open_position(self) -> bool:
        return any(not p.is_flat for p in self.positions)


class Strategy(ABC, Generic[P]):
    """Base class. Subclasses declare `params_model` and implement `on_chain`.

    Strategies must be deterministic pure functions of the context: no I/O, no
    clocks, no randomness — that is what makes backtests reproducible and the
    backtest/paper/live behavior identical.
    """

    strategy_type: ClassVar[str]
    params_model: ClassVar[type[BaseModel]]

    def __init__(self, definition: StrategyDefinition) -> None:
        self.definition = definition
        self.params = cast(P, self.params_model.model_validate(definition.params))

    def emit(
        self,
        ctx: StrategyContext,
        *,
        signal_type: SignalAction,
        legs: tuple[SignalLeg, ...],
        reason: str,
        confidence: float | None = None,
        priority: int = 50,
        metadata: dict[str, Any] | None = None,
        correlation_id: UUID | None = None,
        replay_id: str | None = None,
    ) -> Signal:
        return Signal(
            strategy_id=self.definition.id,
            strategy_version=self.definition.version,
            signal_type=signal_type,
            created_at=ctx.now,
            market_timestamp=ctx.chain.timestamp,
            underlying=ctx.chain.underlying,
            expiry=ctx.chain.expiry,
            confidence=confidence,
            priority=priority,
            reason=reason,
            metadata=metadata or {},
            correlation_id=correlation_id,
            replay_id=replay_id,
            legs=legs,
        )

    @abstractmethod
    def on_chain(self, ctx: StrategyContext) -> list[Signal]:
        """Return zero or more signals for the observed chain."""
