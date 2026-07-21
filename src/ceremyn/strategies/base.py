"""Strategy ABC and the context object strategies observe.

The same on_chain interface is driven by the backtester, the paper trader, and
(eventually) the live trader — a strategy cannot tell which mode it runs in.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from datetime import date, datetime, time
from typing import Any, ClassVar, Generic, TypeVar, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ceremyn.core.timeutils import to_ist
from ceremyn.domain import (
    OptionChainSnapshot,
    PortfolioSnapshot,
    Position,
    Signal,
    SignalLeg,
    StrategyDefinition,
)
from ceremyn.domain.enums import SignalAction

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
    # Other expiries of the same underlying known to the runner at this instant (e.g. for
    # calendar spreads). Empty by default — zero behavior change for single-expiry strategies.
    other_expiries: Mapping[date, OptionChainSnapshot] = Field(default_factory=dict)

    @field_validator("now")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        return value

    @model_validator(mode="before")
    @classmethod
    def _sync_positions(cls, data: Any) -> Any:
        """When `positions` is genuinely omitted (not just empty), default it to the
        whole portfolio's positions -- correct for any single-strategy caller (a
        backtest or a solo paper run), where "the whole portfolio" and "this
        strategy's own positions" are the same thing by construction.

        Must run on the raw input (`mode="before"`), not the validated model: a
        multi-strategy runner sharing one account (e.g. `RestPricePoller`) computes
        each strategy's own positions and passes them explicitly, including an
        explicitly empty tuple for a strategy that's genuinely flat. An `after`
        validator can't tell "explicitly empty" from "not provided" once both have
        collapsed to `()` -- it would silently overwrite a deliberately-flat strategy
        with every other strategy's positions too, which is exactly the bug this
        validator used to reintroduce.
        """
        if isinstance(data, dict) and "positions" not in data and data.get("portfolio") is not None:
            data["positions"] = data["portfolio"].positions
        return data

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
