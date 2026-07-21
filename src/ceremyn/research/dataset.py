"""Datasets: a versioned, content-hashed event stream for reproducible experiments.

A Dataset wraps a pre-built sequence of BacktestEvents (from repositories, ingestion,
or fixtures) together with the metadata an experiment needs to be reproducible:

- ``market_data_version`` — a deterministic sha256 over a canonical digest of the
  events, so identical market data yields an identical version string.
- ``feature_version`` — a caller-supplied tag describing the feature/analytics
  pipeline that produced the chains (e.g. greeks/IV config), advanced when that changes.
"""

import hashlib
from collections.abc import Iterable
from functools import cached_property

from pydantic import BaseModel, ConfigDict, Field

from ceremyn.backtest.events import BacktestEvent


class Dataset(BaseModel):
    """An immutable, versioned event stream fed to the backtest engine."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    events: tuple[BacktestEvent, ...] = Field(min_length=1)
    feature_version: str = "v1"

    @cached_property
    def market_data_version(self) -> str:
        """sha256 of a canonical digest of the events (order-independent of memory ids)."""
        hasher = hashlib.sha256()
        for event in sorted(self.events, key=lambda item: item.timestamp):
            # model_dump_json is stable for frozen pydantic models with sorted keys.
            hasher.update(type(event).__name__.encode())
            hasher.update(event.model_dump_json().encode())
        return hasher.hexdigest()

    @property
    def size(self) -> int:
        return len(self.events)

    def ordered_events(self) -> tuple[BacktestEvent, ...]:
        return tuple(sorted(self.events, key=lambda item: item.timestamp))


def dataset_from_events(
    name: str,
    events: Iterable[BacktestEvent],
    *,
    feature_version: str = "v1",
) -> Dataset:
    return Dataset(name=name, events=tuple(events), feature_version=feature_version)
