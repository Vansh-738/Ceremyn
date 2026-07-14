"""Composition root.

The Container is the single place where the object graph is assembled. Modules
never instantiate each other's collaborators; they receive them from here
(directly, or via FastAPI dependencies that delegate to the container).
"""

from functools import cached_property
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from alphaquant.config import Settings
from alphaquant.core.calendar import MarketCalendar
from alphaquant.core.events import EventBus

# Type-checking-only imports: runtime imports inside the properties stay lazy
# so that importing the container never drags in heavy infra modules.
if TYPE_CHECKING:
    from alphaquant.data.providers.kite import KiteProvider
    from alphaquant.data.repositories.candles import CandleRepository
    from alphaquant.data.repositories.chains import (
        ChainSnapshotRepository,
        OptionChainEodRepository,
    )
    from alphaquant.data.repositories.instruments import InstrumentRepository
    from alphaquant.data.services.chain_analytics import ChainAnalyticsService
    from alphaquant.data.services.ingest import BhavcopyIngestService
    from alphaquant.data.services.snapshots import ChainService, ChainSnapshotJob


class Container:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @cached_property
    def event_bus(self) -> EventBus:
        return EventBus()

    @cached_property
    def calendar(self) -> MarketCalendar:
        return MarketCalendar()

    # -- persistence -----------------------------------------------------

    @cached_property
    def _db(self) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
        from alphaquant.data.repositories.db import create_engine_and_sessionmaker

        return create_engine_and_sessionmaker(self.settings.db.url)

    @property
    def engine(self) -> AsyncEngine:
        return self._db[0]

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._db[1]

    @cached_property
    def instrument_repository(self) -> "InstrumentRepository":
        from alphaquant.data.repositories.instruments import InstrumentRepository

        return InstrumentRepository(self.session_factory)

    @cached_property
    def candle_repository(self) -> "CandleRepository":
        from alphaquant.data.repositories.candles import CandleRepository

        return CandleRepository(self.session_factory)

    @cached_property
    def chain_eod_repository(self) -> "OptionChainEodRepository":
        from alphaquant.data.repositories.chains import OptionChainEodRepository

        return OptionChainEodRepository(self.session_factory)

    @cached_property
    def chain_snapshot_repository(self) -> "ChainSnapshotRepository":
        from alphaquant.data.repositories.chains import ChainSnapshotRepository

        return ChainSnapshotRepository(self.session_factory)

    # -- providers & services -----------------------------------------------

    @cached_property
    def kite_provider(self) -> "KiteProvider":
        from alphaquant.data.providers.kite import KiteProvider

        return KiteProvider.from_settings(self.settings)

    @cached_property
    def chain_analytics(self) -> "ChainAnalyticsService":
        from alphaquant.data.services.chain_analytics import ChainAnalyticsService

        return ChainAnalyticsService(risk_free_rate=self.settings.data.risk_free_rate)

    @cached_property
    def chain_service(self) -> "ChainService":
        from alphaquant.data.services.snapshots import ChainService

        return ChainService(self.kite_provider, self.instrument_repository, self.chain_analytics)

    @cached_property
    def chain_snapshot_job(self) -> "ChainSnapshotJob":
        from alphaquant.data.services.snapshots import ChainSnapshotJob

        return ChainSnapshotJob(
            self.chain_service,
            self.chain_snapshot_repository,
            self.calendar,
            self.settings.data.underlyings,
        )

    @cached_property
    def bhavcopy_ingest(self) -> "BhavcopyIngestService":
        from alphaquant.data.providers.bhavcopy import BhavcopyClient
        from alphaquant.data.services.ingest import BhavcopyIngestService

        return BhavcopyIngestService(
            BhavcopyClient(),
            self.chain_eod_repository,
            self.calendar,
            self.settings.data.underlyings,
        )
