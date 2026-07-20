"""Trade ledger and closed-trade records."""

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from alphaquant.domain import Instrument
from alphaquant.domain.enums import Side
from alphaquant.domain.market_data import _require_aware


class CashLedgerEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    amount: Decimal
    description: str = Field(min_length=1)

    _aware = field_validator("timestamp")(_require_aware)


class ClosedTrade(BaseModel):
    model_config = ConfigDict(frozen=True)

    contract: Instrument
    strategy_id: str = Field(min_length=1)
    signal_id: UUID | None = None
    quantity: int = Field(gt=0)
    direction: Side
    entry_price: Decimal = Field(gt=0)
    exit_price: Decimal = Field(gt=0)
    entry_at: datetime
    exit_at: datetime
    gross_pnl: Decimal
    costs: Decimal = Field(default=Decimal("0"), ge=0)

    _aware_entry = field_validator("entry_at")(_require_aware)
    _aware_exit = field_validator("exit_at")(_require_aware)

    @property
    def net_pnl(self) -> Decimal:
        return self.gross_pnl - self.costs

    @property
    def holding_time(self) -> timedelta:
        return self.exit_at - self.entry_at


class TradeLedger(BaseModel):
    model_config = ConfigDict(frozen=True)

    cash_entries: tuple[CashLedgerEntry, ...] = ()
    closed_trades: tuple[ClosedTrade, ...] = ()

    def add_cash_entry(self, entry: CashLedgerEntry) -> "TradeLedger":
        return self.model_copy(update={"cash_entries": (*self.cash_entries, entry)})

    def add_closed_trade(self, trade: ClosedTrade) -> "TradeLedger":
        return self.model_copy(update={"closed_trades": (*self.closed_trades, trade)})
