"""Immutable live-market tick and snapshot models."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ceremyn.domain import OptionChainSnapshot
from ceremyn.domain.market_data import _require_aware
from ceremyn.features.context import FeatureContext
from ceremyn.features.models import FeatureSet
from ceremyn.live.market_hours import MarketStatus


class InstrumentKind(StrEnum):
    INDEX = "index"
    OPTION = "option"
    SPOT = "spot"


class LiveTick(BaseModel):
    """A normalized tick emitted by the live feed."""

    model_config = ConfigDict(frozen=True)

    instrument_token: int = Field(ge=1)
    tradingsymbol: str = Field(min_length=1)
    underlying: str = Field(min_length=1)
    instrument_kind: InstrumentKind
    timestamp: datetime
    last_price: Decimal = Field(ge=0)
    bid: Decimal | None = Field(default=None, ge=0)
    ask: Decimal | None = Field(default=None, ge=0)
    volume: int = Field(default=0, ge=0)
    open_interest: int = Field(default=0, ge=0)
    exchange_timestamp: datetime | None = None
    received_at: datetime
    sequence_id: str = Field(min_length=1)

    _aware_timestamp = field_validator("timestamp")(_require_aware)
    _aware_received = field_validator("received_at")(_require_aware)

    @field_validator("exchange_timestamp")
    @classmethod
    def _validate_exchange_timestamp(cls, value: datetime | None) -> datetime | None:
        return _require_aware(value) if value is not None else None

    @property
    def event_timestamp(self) -> datetime:
        return self.exchange_timestamp or self.timestamp

    @property
    def latency_ms(self) -> float:
        return max(0.0, (self.received_at - self.event_timestamp).total_seconds() * 1000)


class MarketSnapshot(BaseModel):
    """The latest immutable market view for one underlying."""

    model_config = ConfigDict(frozen=True)

    underlying: str = Field(min_length=1)
    timestamp: datetime
    market_status: MarketStatus
    spot: Decimal = Field(gt=0)
    option_chain: OptionChainSnapshot
    feature_context: FeatureContext
    features: FeatureSet | None = None
    source_tick_count: int = Field(default=0, ge=0)
    latency_ms: float = Field(default=0.0, ge=0)

    _aware = field_validator("timestamp")(_require_aware)
