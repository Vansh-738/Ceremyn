"""ORM models (infrastructure only — never leak these upward; map to domain types).

Numeric columns use Decimal-compatible NUMERIC; volumes/OI are BIGINT.
All timestamps are TIMESTAMPTZ (stored UTC).
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, Index, Numeric, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from alphaquant.data.repositories.db import Base

PRICE = Numeric(14, 4)


class InstrumentRow(Base):
    __tablename__ = "instruments"
    __table_args__ = (Index("ix_instruments_underlying_expiry", "underlying", "expiry"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tradingsymbol: Mapped[str] = mapped_column(Text, unique=True)
    exchange: Mapped[str] = mapped_column(Text)
    underlying: Mapped[str | None] = mapped_column(Text)
    expiry: Mapped[date | None] = mapped_column(Date)
    strike: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    option_type: Mapped[str | None] = mapped_column(Text)  # CE / PE
    lot_size: Mapped[int | None] = mapped_column(BigInteger)
    tick_size: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=Decimal("0.05"))
    broker_token: Mapped[int | None] = mapped_column(BigInteger)


class CandleRow(Base):
    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint("tradingsymbol", "timeframe", "ts", name="uq_candles_symbol_tf_ts"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tradingsymbol: Mapped[str] = mapped_column(Text)
    timeframe: Mapped[str] = mapped_column(Text)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    open: Mapped[Decimal] = mapped_column(PRICE)
    high: Mapped[Decimal] = mapped_column(PRICE)
    low: Mapped[Decimal] = mapped_column(PRICE)
    close: Mapped[Decimal] = mapped_column(PRICE)
    volume: Mapped[int] = mapped_column(BigInteger, default=0)
    open_interest: Mapped[int] = mapped_column(BigInteger, default=0)


class OptionChainEodRow(Base):
    """One option contract's end-of-day record (from the NSE F&O bhavcopy)."""

    __tablename__ = "option_chain_eod"
    __table_args__ = (Index("ix_chain_eod_underlying_date", "underlying", "trade_date"),)

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    underlying: Mapped[str] = mapped_column(Text, primary_key=True)
    expiry: Mapped[date] = mapped_column(Date, primary_key=True)
    strike: Mapped[Decimal] = mapped_column(Numeric(12, 2), primary_key=True)
    option_type: Mapped[str] = mapped_column(Text, primary_key=True)  # CE / PE
    open: Mapped[Decimal | None] = mapped_column(PRICE)
    high: Mapped[Decimal | None] = mapped_column(PRICE)
    low: Mapped[Decimal | None] = mapped_column(PRICE)
    close: Mapped[Decimal | None] = mapped_column(PRICE)
    settle: Mapped[Decimal | None] = mapped_column(PRICE)
    volume: Mapped[int] = mapped_column(BigInteger, default=0)
    open_interest: Mapped[int] = mapped_column(BigInteger, default=0)
    oi_change: Mapped[int] = mapped_column(BigInteger, default=0)
    underlying_close: Mapped[Decimal | None] = mapped_column(PRICE)


class ChainSnapshotEntryRow(Base):
    """One contract within an intraday chain snapshot (built from live quotes)."""

    __tablename__ = "chain_snapshot_entries"

    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    underlying: Mapped[str] = mapped_column(Text, primary_key=True)
    expiry: Mapped[date] = mapped_column(Date, primary_key=True)
    strike: Mapped[Decimal] = mapped_column(Numeric(12, 2), primary_key=True)
    option_type: Mapped[str] = mapped_column(Text, primary_key=True)
    spot: Mapped[Decimal] = mapped_column(PRICE)
    last_price: Mapped[Decimal | None] = mapped_column(PRICE)
    bid: Mapped[Decimal | None] = mapped_column(PRICE)
    ask: Mapped[Decimal | None] = mapped_column(PRICE)
    volume: Mapped[int] = mapped_column(BigInteger, default=0)
    open_interest: Mapped[int] = mapped_column(BigInteger, default=0)
    iv: Mapped[float | None] = mapped_column()
