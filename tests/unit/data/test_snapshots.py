from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from alphaquant.core.timeutils import IST, now_ist
from alphaquant.data.services.chain_analytics import ChainAnalyticsService
from alphaquant.data.services.snapshots import ChainService, ChainSnapshotJob
from alphaquant.domain import OptionChainSnapshot, OptionContract, OptionType, Quote
from tests.unit.domain.conftest import make_contract

# ChainService stamps snapshots with the real clock, so enrichment only runs
# for expiries that are genuinely in the future — use a relative date.
EXPIRY = now_ist().date() + timedelta(days=15)


class FakeProvider:
    async def quotes(self, symbols: list[str]) -> dict[str, Quote]:
        return {
            symbol: Quote(
                tradingsymbol=symbol.split(":", 1)[1],
                timestamp=datetime(2025, 7, 14, 10, 0, tzinfo=IST),
                last_price=Decimal("150"),
                bid=Decimal("149.5"),
                ask=Decimal("150.5"),
                open_interest=1000,
            )
            for symbol in symbols
        }

    async def spot_price(self, underlying: str) -> Decimal:
        return Decimal("24010")


class FakeInstrumentRepo:
    def __init__(self, contracts: list[OptionContract]) -> None:
        self.contracts = contracts

    async def list_contracts(self, underlying: str, expiry: date) -> list[OptionContract]:
        return [c for c in self.contracts if c.underlying == underlying and c.expiry == expiry]

    async def expiries(self, underlying: str, on_or_after: date) -> list[date]:
        return sorted({c.expiry for c in self.contracts if c.underlying == underlying})


class FakeSnapshotRepo:
    def __init__(self) -> None:
        self.saved: list[OptionChainSnapshot] = []

    async def save(self, snapshot: OptionChainSnapshot) -> int:
        self.saved.append(snapshot)
        return len(snapshot.entries)


class FakeCalendar:
    def __init__(self, open_: bool) -> None:
        self.open_ = open_

    def is_market_open(self, at: datetime) -> bool:
        return self.open_


def contracts() -> list[OptionContract]:
    return [
        make_contract(strike=24000, option_type=OptionType.CALL, expiry=EXPIRY),
        make_contract(strike=24000, option_type=OptionType.PUT, expiry=EXPIRY),
    ]


def make_chain_service(repo: FakeInstrumentRepo | None = None) -> ChainService:
    return ChainService(
        FakeProvider(),  # type: ignore[arg-type]
        repo or FakeInstrumentRepo(contracts()),  # type: ignore[arg-type]
        ChainAnalyticsService(risk_free_rate=0.065),
    )


class TestChainService:
    async def test_build_assembles_and_enriches(self) -> None:
        snapshot = await make_chain_service().build("NIFTY", EXPIRY)
        assert snapshot.underlying == "NIFTY"
        assert snapshot.spot == Decimal("24010")
        assert len(snapshot.entries) == 2
        assert all(e.quote is not None for e in snapshot.entries)
        assert all(e.greeks is not None for e in snapshot.entries)  # enrichment ran

    async def test_build_without_contracts_raises(self) -> None:
        service = make_chain_service(FakeInstrumentRepo([]))
        with pytest.raises(ValueError, match="seed_instruments"):
            await service.build("NIFTY", EXPIRY)

    async def test_nearest_expiry(self) -> None:
        assert await make_chain_service().nearest_expiry("NIFTY") == EXPIRY


def make_job(open_: bool, repo: FakeSnapshotRepo) -> ChainSnapshotJob:
    return ChainSnapshotJob(
        make_chain_service(),
        repo,  # type: ignore[arg-type]
        FakeCalendar(open_),  # type: ignore[arg-type]
        ("NIFTY",),
    )


class TestSnapshotJob:
    async def test_skips_when_market_closed(self) -> None:
        repo = FakeSnapshotRepo()
        assert await make_job(open_=False, repo=repo).run_once() == 0
        assert repo.saved == []

    async def test_persists_when_market_open(self) -> None:
        repo = FakeSnapshotRepo()
        assert await make_job(open_=True, repo=repo).run_once() == 2
        assert len(repo.saved) == 1
        assert repo.saved[0].underlying == "NIFTY"
