"""FeatureContext: the immutable, hashable input every feature reads.

The context bundles everything a feature may need — the current option chain, the
previous chain (for change features), an ATM-IV history, the underlying candle
history, and the risk-free rate — plus an ``as_of`` instant. Its ``fingerprint`` is a
deterministic content hash used as the cache identity, so identical inputs always
resolve to the same cached feature values.
"""

import hashlib
from datetime import datetime
from functools import cached_property

from pydantic import BaseModel, ConfigDict, Field, field_validator

from alphaquant.domain import Candle, OptionChainSnapshot
from alphaquant.domain.market_data import _require_aware


class FeatureContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    as_of: datetime
    underlying: str = Field(min_length=1)
    chain: OptionChainSnapshot | None = None
    previous_chain: OptionChainSnapshot | None = None
    # ATM-IV observations up to and including now (oldest -> newest), for IV rank/percentile.
    iv_history: tuple[float, ...] = ()
    # Underlying OHLCV history, ascending by time.
    candles: tuple[Candle, ...] = ()
    risk_free_rate: float = 0.065

    _aware = field_validator("as_of")(_require_aware)

    @cached_property
    def fingerprint(self) -> str:
        """Deterministic sha256 over a canonical digest of every input."""
        hasher = hashlib.sha256()
        hasher.update(self.as_of.isoformat().encode())
        hasher.update(self.underlying.encode())
        hasher.update(f"{self.risk_free_rate:.10f}".encode())
        hasher.update(repr(self.iv_history).encode())
        for label, chain in (("chain", self.chain), ("prev", self.previous_chain)):
            hasher.update(label.encode())
            hasher.update(b"none" if chain is None else chain.model_dump_json().encode())
        for candle in self.candles:
            hasher.update(candle.model_dump_json().encode())
        return hasher.hexdigest()

    # -- convenience views for features -----------------------------------

    @property
    def closes(self) -> list[float]:
        return [float(candle.close) for candle in self.candles]

    @property
    def highs(self) -> list[float]:
        return [float(candle.high) for candle in self.candles]

    @property
    def lows(self) -> list[float]:
        return [float(candle.low) for candle in self.candles]

    @property
    def volumes(self) -> list[float]:
        return [float(candle.volume) for candle in self.candles]

    @property
    def candle_count(self) -> int:
        return len(self.candles)
