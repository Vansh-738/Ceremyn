"""Repository round-trips against a real Postgres (see conftest for setup)."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alphaquant.data.records import EodFutureRecord, EodOptionRecord
from alphaquant.data.repositories.candles import CandleRepository
from alphaquant.data.repositories.chains import ChainSnapshotRepository, OptionChainEodRepository
from alphaquant.data.repositories.corporate_actions import CorporateActionRepository
from alphaquant.data.repositories.futures import FutureChainEodRepository
from alphaquant.data.repositories.instruments import InstrumentRepository
from alphaquant.domain import (
    Candle,
    ChainEntry,
    CorporateAction,
    CorporateActionType,
    EquityInstrument,
    ETFInstrument,
    Exchange,
    FutureContract,
    OptionChainSnapshot,
    TimeFrame,
)
from tests.unit.domain.conftest import make_contract, make_quote

pytestmark = pytest.mark.integration

EXPIRY = date(2025, 7, 29)


class TestInstrumentRepository:
    async def test_upsert_and_fetch(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = InstrumentRepository(session_factory)
        contracts = [
            make_contract(strike=24000).model_copy(update={"broker_token": 1}),
            make_contract(strike=24100).model_copy(update={"broker_token": 2}),
        ]
        assert await repo.upsert_contracts(contracts) == 2
        # Idempotent upsert: same symbols update in place.
        assert await repo.upsert_contracts(contracts) == 2

        stored = await repo.list_contracts("NIFTY", EXPIRY)
        assert [c.strike for c in stored] == [Decimal(24000), Decimal(24100)]
        assert await repo.get(contracts[0].tradingsymbol) == contracts[0]
        assert await repo.expiries("NIFTY", date(2025, 7, 1)) == [EXPIRY]

    async def test_round_trips_every_asset_class(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = InstrumentRepository(session_factory)
        future = FutureContract(
            tradingsymbol="NIFTY25JULFUT",
            exchange=Exchange.NFO,
            underlying="NIFTY",
            expiry=EXPIRY,
            lot_size=75,
            broker_token=201,
        )
        equity = EquityInstrument(
            tradingsymbol="RELIANCE",
            exchange=Exchange.NSE,
            underlying="RELIANCE",
            isin="INE002A01018",
            broker_token=202,
        )
        etf = ETFInstrument(
            tradingsymbol="NIFTYBEES",
            exchange=Exchange.NSE,
            underlying="NIFTYBEES",
            isin="INF204KB17I5",
            broker_token=203,
        )

        assert await repo.upsert_contracts([future, equity, etf]) == 3

        assert await repo.get("NIFTY25JULFUT") == future
        assert await repo.get("RELIANCE") == equity
        assert await repo.get("NIFTYBEES") == etf


class TestFutureChainEodRepository:
    async def test_upsert_and_queries(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = FutureChainEodRepository(session_factory)
        trade_date = date(2025, 7, 11)
        record = EodFutureRecord(
            trade_date=trade_date,
            underlying="NIFTY",
            expiry=date(2025, 7, 31),
            close=Decimal("24580.25"),
            settle=Decimal("24580.25"),
            volume=15_478_236,
            open_interest=12_456_300,
            oi_change=235_600,
            underlying_close=Decimal("24502.15"),
        )

        assert await repo.upsert_many([record]) == 1
        assert await repo.upsert_many([record]) == 1  # idempotent

        chain = await repo.fetch_chain("NIFTY", trade_date)
        assert len(chain) == 1
        assert chain[0].close == Decimal("24580.25")
        assert await repo.trade_dates("NIFTY") == [trade_date]


class TestCorporateActionRepository:
    async def test_upsert_and_queries(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = CorporateActionRepository(session_factory)
        split = CorporateAction(
            tradingsymbol="RELIANCE",
            action_type=CorporateActionType.SPLIT,
            ex_date=date(2025, 8, 1),
            ratio=Decimal("2"),
        )
        dividend = CorporateAction(
            tradingsymbol="RELIANCE",
            action_type=CorporateActionType.DIVIDEND,
            ex_date=date(2025, 9, 1),
            dividend_amount=Decimal("8.5"),
        )

        assert await repo.upsert_many([split, dividend]) == 2
        assert await repo.upsert_many([split, dividend]) == 2  # idempotent

        actions = await repo.for_tradingsymbol("RELIANCE")
        assert actions == [split, dividend]
        assert await repo.since("RELIANCE", date(2025, 8, 15)) == [dividend]


class TestCandleRepository:
    async def test_upsert_overwrites_and_fetch_orders(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = CandleRepository(session_factory)
        ts = datetime(2025, 7, 11, 9, 15, tzinfo=UTC)

        def candle(close: str) -> Candle:
            return Candle(
                tradingsymbol="NIFTY 50",
                timeframe=TimeFrame.DAY,
                timestamp=ts,
                open=Decimal(24500),
                high=Decimal(24700),
                low=Decimal(24400),
                close=Decimal(close),
            )

        await repo.upsert_many([candle("24580")])
        await repo.upsert_many([candle("24600")])  # same key -> overwrite
        rows = await repo.fetch("NIFTY 50", TimeFrame.DAY, ts, ts)
        assert len(rows) == 1
        assert rows[0].close == Decimal(24600)


class TestChainRepositories:
    async def test_eod_upsert_and_queries(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        repo = OptionChainEodRepository(session_factory)
        trade_date = date(2025, 7, 11)

        def record(strike: int, option_type: str) -> EodOptionRecord:
            return EodOptionRecord(
                trade_date=trade_date,
                underlying="NIFTY",
                expiry=EXPIRY,
                strike=Decimal(strike),
                option_type=option_type,
                close=Decimal("100.5"),
                settle=Decimal("100.5"),
                volume=1000,
                open_interest=50_000,
                oi_change=-1200,
                underlying_close=Decimal("24502.15"),
                lot_size=75,
            )

        rows = [record(24000, "CE"), record(24000, "PE"), record(24100, "CE")]
        assert await repo.upsert_many(rows) == 3
        assert await repo.upsert_many(rows) == 3  # idempotent

        chain = await repo.fetch_chain("NIFTY", trade_date, EXPIRY)
        assert len(chain) == 3
        assert chain[0].oi_change == -1200
        assert await repo.trade_dates("NIFTY") == [trade_date]
        assert await repo.expiries_on("NIFTY", trade_date) == [EXPIRY]

    async def test_snapshot_save(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        repo = ChainSnapshotRepository(session_factory)
        contract = make_contract(strike=24000, expiry=EXPIRY)
        snapshot = OptionChainSnapshot(
            underlying="NIFTY",
            expiry=EXPIRY,
            spot=Decimal(24010),
            timestamp=datetime(2025, 7, 14, 10, 0, tzinfo=UTC),
            entries=(
                ChainEntry(
                    contract=contract,
                    quote=make_quote(tradingsymbol=contract.tradingsymbol, open_interest=999),
                ),
            ),
        )
        assert await repo.save(snapshot) == 1
        assert await repo.save(snapshot) == 1  # duplicate capture: conflict ignored
