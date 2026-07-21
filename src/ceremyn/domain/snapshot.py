"""Asset-class-neutral point-in-time market observation.

`MarketSnapshot` is additive: nothing in strategies/risk/OMS/broker consumes it yet
(see `ARCHITECTURE_DECISIONS.md` / `ROADMAP_V2.md`). It composes -- never replaces --
the existing, options-specific `OptionChainSnapshot`, and can equally represent an
underlying that has no option chain at all (an equity, a future, an ETF, or any future
asset class), which `OptionChainSnapshot` cannot: its `expiry` field is required and its
`entries` field requires at least one contract.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ceremyn.domain.chain import OptionChainSnapshot
from ceremyn.domain.market_data import Candle, Quote, _require_aware


class MarketSnapshot(BaseModel):
    """A point-in-time observation of one underlying, independent of asset class.

    At least one of `quote`, `candle`, or `option_chain` must be present -- an
    observation carrying none of them holds no market data at all. When `option_chain`
    is present, its own `underlying` must match this snapshot's `underlying`.
    """

    model_config = ConfigDict(frozen=True)

    underlying: str = Field(min_length=1)
    timestamp: datetime
    quote: Quote | None = None
    candle: Candle | None = None
    option_chain: OptionChainSnapshot | None = None

    _aware = field_validator("timestamp")(_require_aware)

    @model_validator(mode="after")
    def _check_consistency(self) -> "MarketSnapshot":
        if self.quote is None and self.candle is None and self.option_chain is None:
            raise ValueError(
                "MarketSnapshot requires at least one of quote, candle, or option_chain"
            )
        if self.option_chain is not None and self.option_chain.underlying != self.underlying:
            raise ValueError("option_chain.underlying must match the snapshot's underlying")
        return self
