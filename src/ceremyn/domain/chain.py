"""Option-chain snapshot: all quoted strikes of one underlying/expiry at an instant."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ceremyn.domain.enums import OptionType
from ceremyn.domain.greeks import Greeks
from ceremyn.domain.instruments import OptionContract
from ceremyn.domain.market_data import Quote, _require_aware


class ChainEntry(BaseModel):
    """One contract's row in a chain snapshot."""

    model_config = ConfigDict(frozen=True)

    contract: OptionContract
    quote: Quote | None = None
    greeks: Greeks | None = None

    @property
    def open_interest(self) -> int:
        return self.quote.open_interest if self.quote is not None else 0


class OptionChainSnapshot(BaseModel):
    """Point-in-time option chain for a single underlying and expiry."""

    model_config = ConfigDict(frozen=True)

    underlying: str = Field(min_length=1)
    expiry: date
    spot: Decimal = Field(gt=0)
    timestamp: datetime
    entries: tuple[ChainEntry, ...] = Field(min_length=1)

    _aware = field_validator("timestamp")(_require_aware)

    def get(self, strike: Decimal, option_type: OptionType) -> ChainEntry | None:
        for entry in self.entries:
            if entry.contract.strike == strike and entry.contract.option_type is option_type:
                return entry
        return None

    @property
    def strikes(self) -> tuple[Decimal, ...]:
        return tuple(sorted({entry.contract.strike for entry in self.entries}))

    @property
    def atm_strike(self) -> Decimal:
        return min(self.strikes, key=lambda strike: abs(strike - self.spot))

    @property
    def total_call_oi(self) -> int:
        return sum(e.open_interest for e in self.entries if e.contract.is_call)

    @property
    def total_put_oi(self) -> int:
        return sum(e.open_interest for e in self.entries if e.contract.is_put)

    @property
    def pcr(self) -> float | None:
        """Put-call ratio on open interest; None when call OI is zero."""
        call_oi = self.total_call_oi
        if call_oi == 0:
            return None
        return self.total_put_oi / call_oi
