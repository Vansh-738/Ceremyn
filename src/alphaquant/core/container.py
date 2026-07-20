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
    from alphaquant.broker.adapter import NullBrokerAdapter
    from alphaquant.broker.simulated import SimulatedBroker
    from alphaquant.core.instrumentation import ObservableRiskEngine, ReadableHeartbeatMonitor
    from alphaquant.data.providers.kite import KiteProvider
    from alphaquant.data.records import EodFutureRecord, EodOptionRecord
    from alphaquant.data.repositories.candles import CandleRepository
    from alphaquant.data.repositories.chains import (
        ChainSnapshotRepository,
        OptionChainEodRepository,
    )
    from alphaquant.data.repositories.corporate_actions import CorporateActionRepository
    from alphaquant.data.repositories.futures import FutureChainEodRepository
    from alphaquant.data.repositories.instruments import InstrumentRepository
    from alphaquant.data.services.candle_ingest import CandleIngestService
    from alphaquant.data.services.chain_analytics import ChainAnalyticsService
    from alphaquant.data.services.ingest import BhavcopyIngestService
    from alphaquant.data.services.snapshots import ChainService, ChainSnapshotJob
    from alphaquant.execution.gate import LiveTradingGate
    from alphaquant.execution.gated_broker import GatedBrokerAdapter
    from alphaquant.execution.kite_broker import KiteBroker
    from alphaquant.features.cache import InMemoryFeatureCache
    from alphaquant.features.engine import FeatureEngine
    from alphaquant.live.engine import LiveMarketDataEngine
    from alphaquant.live.reconnect import ReconnectManager
    from alphaquant.llm.client import ClaudeClient
    from alphaquant.llm.conversation import InMemoryConversationStore
    from alphaquant.llm.watchlist import InMemoryWatchlistStore
    from alphaquant.oms.engine import OrderManagementEngine
    from alphaquant.paper.engine import PaperTradingEngine
    from alphaquant.research.experiment_manager import ExperimentManager
    from alphaquant.research.experiment_store import JSONExperimentStore
    from alphaquant.runtime.orchestrator import RuntimeOrchestrator


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

    @cached_property
    def future_chain_eod_repository(self) -> "FutureChainEodRepository":
        from alphaquant.data.repositories.futures import FutureChainEodRepository

        return FutureChainEodRepository(self.session_factory)

    @cached_property
    def corporate_action_repository(self) -> "CorporateActionRepository":
        from alphaquant.data.repositories.corporate_actions import CorporateActionRepository

        return CorporateActionRepository(self.session_factory)

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
    def bhavcopy_ingest(self) -> "BhavcopyIngestService[EodOptionRecord]":
        from alphaquant.data.providers.bhavcopy import BhavcopyClient
        from alphaquant.data.services.ingest import BhavcopyIngestService

        return BhavcopyIngestService(
            BhavcopyClient(),
            self.chain_eod_repository,
            self.calendar,
            self.settings.data.underlyings,
        )

    @cached_property
    def future_bhavcopy_ingest(self) -> "BhavcopyIngestService[EodFutureRecord]":
        from alphaquant.data.providers.bhavcopy import BhavcopyClient, parse_bhavcopy_futures
        from alphaquant.data.services.ingest import BhavcopyIngestService

        # Same underlyings as options: NIFTY/BANKNIFTY futures trade against the
        # same index names, and both segments live in the same bhavcopy file.
        return BhavcopyIngestService(
            BhavcopyClient(),
            self.future_chain_eod_repository,
            self.calendar,
            self.settings.data.underlyings,
            parse=parse_bhavcopy_futures,
        )

    @cached_property
    def candle_ingest(self) -> "CandleIngestService":
        from alphaquant.data.services.candle_ingest import CandleIngestService

        return CandleIngestService(self.kite_provider, self.candle_repository)

    # -- runtime engines (live, OMS, paper, risk, features, research) -------
    #
    # None of these touch Postgres/Redis/Kite: the dev environment has no DB and no
    # broker credentials, so the runtime must construct and start cleanly without them.
    # Each engine is a `cached_property` singleton, resolved lazily on first use.

    @cached_property
    def heartbeat_monitor(self) -> "ReadableHeartbeatMonitor":
        from alphaquant.core.instrumentation import ReadableHeartbeatMonitor

        return ReadableHeartbeatMonitor()

    @cached_property
    def reconnect_manager(self) -> "ReconnectManager":
        from alphaquant.live.reconnect import ReconnectManager

        return ReconnectManager()

    @cached_property
    def risk_engine(self) -> "ObservableRiskEngine":
        from alphaquant.core.instrumentation import ObservableRiskEngine

        return ObservableRiskEngine(self.settings)

    @cached_property
    def feature_cache(self) -> "InMemoryFeatureCache":
        from alphaquant.features.cache import InMemoryFeatureCache

        return InMemoryFeatureCache()

    @cached_property
    def feature_engine(self) -> "FeatureEngine":
        from alphaquant.features.engine import FeatureEngine

        return FeatureEngine(cache=self.feature_cache)

    @cached_property
    def null_broker(self) -> "NullBrokerAdapter":
        from alphaquant.broker.adapter import NullBrokerAdapter

        return NullBrokerAdapter()

    @cached_property
    def simulated_broker(self) -> "SimulatedBroker":
        from alphaquant.broker.simulated import SimulatedBroker

        # Real market data when it's available (via the live engine's cache), honest
        # unfilled orders when it isn't — never fabricated fills.
        return SimulatedBroker(market_data=self.live_engine.cache)

    @cached_property
    def kite_broker(self) -> "KiteBroker":
        from alphaquant.execution.kite_broker import KiteBroker

        # Raises BrokerError without ALPHAQUANT_KITE__API_KEY, exactly like
        # `kite_provider`. Never touched unless `live_trading_gate` actually permits
        # live routing (see `gated_broker`'s lazy factory), so a missing key never
        # breaks OMS construction outside live mode.
        return KiteBroker.from_settings(self.settings)

    @cached_property
    def live_trading_gate(self) -> "LiveTradingGate":
        from alphaquant.execution.gate import LiveTradingGate

        return LiveTradingGate()

    @cached_property
    def gated_broker(self) -> "GatedBrokerAdapter":
        from alphaquant.execution.gated_broker import GatedBrokerAdapter

        return GatedBrokerAdapter(
            live_factory=lambda: self.kite_broker,
            fallback=self.simulated_broker,
            gate=self.live_trading_gate,
            settings=self.settings,
        )

    @cached_property
    def oms_engine(self) -> "OrderManagementEngine":
        from alphaquant.oms.engine import OrderManagementEngine
        from alphaquant.oms.journal import JSONJournalStore, OMSJournal

        # A stable session id (not a random uuid4) so a restart re-opens the *same*
        # journal file rather than starting a fresh, empty one — the whole point of
        # persisting it. `restore_from_journal()` rebuilds `orders`/`external_index`/
        # `_children`/idempotency purely from local disk; it never touches a broker
        # (the broker round-trip reconciliation happens once in
        # `RuntimeOrchestrator.start()`, which is the component whose job is actually
        # reaching out to the world on startup).
        session_id = f"oms-{self.settings.environment}"
        journal = OMSJournal(session_id, store=JSONJournalStore(session_id))
        engine = OrderManagementEngine(
            risk_engine=self.risk_engine,
            brokers={"execution": self.gated_broker},
            default_broker="execution",
            journal=journal,
        )
        engine.restore_from_journal()
        return engine

    @cached_property
    def paper_engine(self) -> "PaperTradingEngine":
        from alphaquant.paper.engine import PaperTradingEngine

        # No strategies configured by default: which strategies to run in paper
        # mode is a product decision, not part of runtime wiring.
        return PaperTradingEngine(
            strategies=[],
            risk_engine=self.risk_engine,
            feature_engine=self.feature_engine,
        )

    @cached_property
    def live_engine(self) -> "LiveMarketDataEngine":
        from alphaquant.live.engine import LiveMarketDataEngine
        from alphaquant.live.feed import UnderlyingDefinition

        # No Kite credentials/instrument master in this environment, so there are no
        # real index tokens. Negative sentinel tokens keep the subscription plan
        # non-empty (required) without fabricating market data; no `client` is passed,
        # so `.start()` stays a no-op and nothing produces fake ticks.
        underlyings = tuple(
            UnderlyingDefinition(name=name, index_symbol=name, index_token=-(position + 1))
            for position, name in enumerate(self.settings.data.underlyings)
        )
        return LiveMarketDataEngine(
            underlyings=underlyings,
            contracts=(),
            analytics=self.chain_analytics,
            event_bus=self.event_bus,
            feature_engine=self.feature_engine,
            heartbeat=self.heartbeat_monitor,
            reconnect=self.reconnect_manager,
        )

    @cached_property
    def orchestrator(self) -> "RuntimeOrchestrator":
        from alphaquant.runtime.orchestrator import RuntimeOrchestrator

        # Empty strategies by default — same safe posture as `paper_engine`: which
        # strategies actually trade is a product decision, not part of runtime wiring.
        # No streaming client either (no Kite session-auth flow exists yet, see
        # PROJECT_CONTEXT.md), so the tick consumer stays correctly wired but inert
        # until both are configured.
        return RuntimeOrchestrator(
            live_engine=self.live_engine,
            oms_engine=self.oms_engine,
            strategies=(),
            poll_interval_seconds=self.settings.runtime.poll_interval_seconds,
        )

    @cached_property
    def experiment_store(self) -> "JSONExperimentStore":
        from alphaquant.research.experiment_store import JSONExperimentStore

        return JSONExperimentStore()

    @cached_property
    def experiment_manager(self) -> "ExperimentManager":
        from alphaquant.research.experiment_manager import ExperimentManager

        return ExperimentManager(self.experiment_store)

    # -- LLM assistant (M12) -------------------------------------------------
    #
    # `llm_client` is the only one of these that touches the network — and only when
    # actually called; construction just needs ALPHAQUANT_ANTHROPIC__API_KEY, exactly like
    # `kite_broker` needs ALPHAQUANT_KITE__API_KEY. `conversation_store`/`watchlist_store`
    # are session-scoped and in-memory only, by design (never persisted, never lives in
    # configuration).

    @cached_property
    def llm_client(self) -> "ClaudeClient":
        from alphaquant.llm.client import ClaudeClient

        return ClaudeClient.from_settings(self.settings)

    @cached_property
    def conversation_store(self) -> "InMemoryConversationStore":
        from alphaquant.llm.conversation import InMemoryConversationStore

        return InMemoryConversationStore()

    @cached_property
    def watchlist_store(self) -> "InMemoryWatchlistStore":
        from alphaquant.llm.watchlist import InMemoryWatchlistStore

        return InMemoryWatchlistStore()
