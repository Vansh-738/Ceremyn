"""Composition root.

The Container is the single place where the object graph is assembled. Modules
never instantiate each other's collaborators; they receive them from here
(directly, or via FastAPI dependencies that delegate to the container).
"""

from datetime import timedelta
from functools import cached_property
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from ceremyn.config import Settings
from ceremyn.core.calendar import MarketCalendar
from ceremyn.core.events import EventBus
from ceremyn.domain import StrategyDefinition

# Type-checking-only imports: runtime imports inside the properties stay lazy
# so that importing the container never drags in heavy infra modules.
if TYPE_CHECKING:
    from ceremyn.backtest.portfolio import PortfolioConfig
    from ceremyn.broker.simulated import SimulatedBroker
    from ceremyn.core.instrumentation import ObservableRiskEngine, ReadableHeartbeatMonitor
    from ceremyn.data.providers.kite import KiteProvider
    from ceremyn.data.records import EodFutureRecord, EodOptionRecord
    from ceremyn.data.repositories.candles import CandleRepository
    from ceremyn.data.repositories.chains import (
        ChainSnapshotRepository,
        OptionChainEodRepository,
    )
    from ceremyn.data.repositories.corporate_actions import CorporateActionRepository
    from ceremyn.data.repositories.futures import FutureChainEodRepository
    from ceremyn.data.repositories.instruments import InstrumentRepository
    from ceremyn.data.services.candle_ingest import CandleIngestService
    from ceremyn.data.services.chain_analytics import ChainAnalyticsService
    from ceremyn.data.services.equity_quotes import EquityQuoteJob
    from ceremyn.data.services.ingest import BhavcopyIngestService
    from ceremyn.data.services.snapshots import ChainService, ChainSnapshotJob
    from ceremyn.execution.gate import LiveTradingGate
    from ceremyn.execution.gated_broker import GatedBrokerAdapter
    from ceremyn.execution.kite_broker import KiteBroker
    from ceremyn.features.cache import InMemoryFeatureCache
    from ceremyn.features.engine import FeatureEngine
    from ceremyn.live.engine import LiveMarketDataEngine
    from ceremyn.live.reconnect import ReconnectManager
    from ceremyn.llm.client import ClaudeClient
    from ceremyn.llm.conversation import InMemoryConversationStore
    from ceremyn.llm.watchlist import InMemoryWatchlistStore
    from ceremyn.oms.engine import OrderManagementEngine
    from ceremyn.paper.engine import PaperTradingEngine
    from ceremyn.research.experiment_manager import ExperimentManager
    from ceremyn.research.experiment_store import JSONExperimentStore
    from ceremyn.runtime.orchestrator import RuntimeOrchestrator
    from ceremyn.runtime.rest_poller import RestPricePoller
    from ceremyn.strategies.base import Strategy


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
        from ceremyn.data.repositories.db import create_engine_and_sessionmaker

        return create_engine_and_sessionmaker(self.settings.db.url)

    @property
    def engine(self) -> AsyncEngine:
        return self._db[0]

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._db[1]

    @cached_property
    def instrument_repository(self) -> "InstrumentRepository":
        from ceremyn.data.repositories.instruments import InstrumentRepository

        return InstrumentRepository(self.session_factory)

    @cached_property
    def candle_repository(self) -> "CandleRepository":
        from ceremyn.data.repositories.candles import CandleRepository

        return CandleRepository(self.session_factory)

    @cached_property
    def chain_eod_repository(self) -> "OptionChainEodRepository":
        from ceremyn.data.repositories.chains import OptionChainEodRepository

        return OptionChainEodRepository(self.session_factory)

    @cached_property
    def chain_snapshot_repository(self) -> "ChainSnapshotRepository":
        from ceremyn.data.repositories.chains import ChainSnapshotRepository

        return ChainSnapshotRepository(self.session_factory)

    @cached_property
    def future_chain_eod_repository(self) -> "FutureChainEodRepository":
        from ceremyn.data.repositories.futures import FutureChainEodRepository

        return FutureChainEodRepository(self.session_factory)

    @cached_property
    def corporate_action_repository(self) -> "CorporateActionRepository":
        from ceremyn.data.repositories.corporate_actions import CorporateActionRepository

        return CorporateActionRepository(self.session_factory)

    # -- providers & services -----------------------------------------------

    @cached_property
    def kite_provider(self) -> "KiteProvider":
        from ceremyn.data.providers.kite import KiteProvider

        return KiteProvider.from_settings(self.settings)

    @cached_property
    def chain_analytics(self) -> "ChainAnalyticsService":
        from ceremyn.data.services.chain_analytics import ChainAnalyticsService

        return ChainAnalyticsService(risk_free_rate=self.settings.data.risk_free_rate)

    @cached_property
    def chain_service(self) -> "ChainService":
        from ceremyn.data.services.snapshots import ChainService

        return ChainService(self.kite_provider, self.instrument_repository, self.chain_analytics)

    @cached_property
    def chain_snapshot_job(self) -> "ChainSnapshotJob":
        from ceremyn.data.services.snapshots import ChainSnapshotJob

        return ChainSnapshotJob(
            self.chain_service,
            self.chain_snapshot_repository,
            self.calendar,
            self.settings.data.underlyings,
        )

    @cached_property
    def bhavcopy_ingest(self) -> "BhavcopyIngestService[EodOptionRecord]":
        from ceremyn.data.providers.bhavcopy import BhavcopyClient
        from ceremyn.data.services.ingest import BhavcopyIngestService

        return BhavcopyIngestService(
            BhavcopyClient(),
            self.chain_eod_repository,
            self.calendar,
            self.settings.data.underlyings,
        )

    @cached_property
    def future_bhavcopy_ingest(self) -> "BhavcopyIngestService[EodFutureRecord]":
        from ceremyn.data.providers.bhavcopy import BhavcopyClient, parse_bhavcopy_futures
        from ceremyn.data.services.ingest import BhavcopyIngestService

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
        from ceremyn.data.services.candle_ingest import CandleIngestService

        return CandleIngestService(self.kite_provider, self.candle_repository)

    # -- runtime engines (live, OMS, paper, risk, features, research) -------
    #
    # None of these touch Postgres/Redis/Kite: the dev environment has no DB and no
    # broker credentials, so the runtime must construct and start cleanly without them.
    # Each engine is a `cached_property` singleton, resolved lazily on first use.

    @cached_property
    def heartbeat_monitor(self) -> "ReadableHeartbeatMonitor":
        from ceremyn.core.instrumentation import ReadableHeartbeatMonitor

        return ReadableHeartbeatMonitor()

    @cached_property
    def reconnect_manager(self) -> "ReconnectManager":
        from ceremyn.live.reconnect import ReconnectManager

        return ReconnectManager()

    @cached_property
    def risk_engine(self) -> "ObservableRiskEngine":
        from ceremyn.core.instrumentation import ObservableRiskEngine

        return ObservableRiskEngine(self.settings)

    @cached_property
    def feature_cache(self) -> "InMemoryFeatureCache":
        from ceremyn.features.cache import InMemoryFeatureCache

        return InMemoryFeatureCache()

    @cached_property
    def feature_engine(self) -> "FeatureEngine":
        from ceremyn.features.engine import FeatureEngine

        return FeatureEngine(cache=self.feature_cache)

    def _portfolio_config(self) -> "PortfolioConfig":
        from ceremyn.backtest.portfolio import PortfolioConfig

        # One source of truth for cash + margin-ratio assumptions, shared by the real
        # OMS portfolio, the `SimulatedBroker`'s shadow ledger, and
        # `RiskContext.projected_margin_used` (`risk/context.py`) -- all three must
        # agree, or margin/cash reconciliation and pre-trade risk checks silently
        # diverge from what actually gets booked on a fill.
        return PortfolioConfig(
            initial_cash=self.settings.portfolio.initial_cash,
            short_option_margin_ratio=self.settings.risk.margin.short_option_margin_ratio,
            long_option_margin_ratio=self.settings.risk.margin.long_option_margin_ratio,
        )

    @cached_property
    def simulated_broker(self) -> "SimulatedBroker":
        from ceremyn.broker.simulated import SimulatedBroker

        # Real market data when it's available (via the live engine's cache), honest
        # unfilled orders when it isn't — never fabricated fills. `portfolio_config`
        # must mirror `oms_engine`'s own initial cash: this shadow ledger stands in
        # for what a real broker's `fetch_cash()` would report, and `reconcile()`
        # compares it against `oms_engine.portfolio.cash` — a mismatched starting
        # balance would make `cash_drift` permanently non-zero.
        return SimulatedBroker(
            market_data=self.live_engine.cache,
            portfolio_config=self._portfolio_config(),
            max_quote_age=timedelta(seconds=self.settings.execution.max_paper_quote_age_seconds),
        )

    @cached_property
    def kite_broker(self) -> "KiteBroker":
        from ceremyn.execution.kite_broker import KiteBroker

        # Raises BrokerError without CEREMYN_KITE__API_KEY, exactly like
        # `kite_provider`. Never touched unless `live_trading_gate` actually permits
        # live routing (see `gated_broker`'s lazy factory), so a missing key never
        # breaks OMS construction outside live mode.
        return KiteBroker.from_settings(self.settings)

    @cached_property
    def live_trading_gate(self) -> "LiveTradingGate":
        from ceremyn.execution.gate import LiveTradingGate

        return LiveTradingGate()

    @cached_property
    def gated_broker(self) -> "GatedBrokerAdapter":
        from ceremyn.execution.gated_broker import GatedBrokerAdapter

        return GatedBrokerAdapter(
            live_factory=lambda: self.kite_broker,
            fallback=self.simulated_broker,
            gate=self.live_trading_gate,
            settings=self.settings,
        )

    @cached_property
    def oms_engine(self) -> "OrderManagementEngine":
        from ceremyn.oms.engine import OrderManagementEngine
        from ceremyn.oms.journal import JSONJournalStore, OMSJournal
        from ceremyn.oms.positions import OMSPortfolio

        # A stable session id (not a random uuid4) so a restart re-opens the *same*
        # journal file rather than starting a fresh, empty one — the whole point of
        # persisting it. `restore_from_journal()` rebuilds `orders`/`external_index`/
        # `_children`/idempotency purely from local disk; it never touches a broker
        # (the broker round-trip reconciliation happens once in
        # `RuntimeOrchestrator.start()`, which is the component whose job is actually
        # reaching out to the world on startup).
        session_id = f"oms-{self.settings.environment}"
        journal = OMSJournal(session_id, store=JSONJournalStore(session_id))
        portfolio = OMSPortfolio(self._portfolio_config())
        engine = OrderManagementEngine(
            risk_engine=self.risk_engine,
            brokers={"execution": self.gated_broker},
            default_broker="execution",
            journal=journal,
            portfolio=portfolio,
        )
        engine.restore_from_journal()
        return engine

    @cached_property
    def paper_engine(self) -> "PaperTradingEngine":
        from ceremyn.paper.engine import PaperTradingEngine

        # No strategies configured by default: which strategies to run in paper
        # mode is a product decision, not part of runtime wiring.
        return PaperTradingEngine(
            strategies=[],
            risk_engine=self.risk_engine,
            feature_engine=self.feature_engine,
        )

    @cached_property
    def live_engine(self) -> "LiveMarketDataEngine":
        from ceremyn.live.engine import LiveMarketDataEngine
        from ceremyn.live.feed import UnderlyingDefinition

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

    def _runtime_strategy_definitions(self, *, suffix: str) -> tuple[StrategyDefinition, ...]:
        underlying = self.settings.data.underlyings[0]
        seen: set[str] = set()
        definitions: list[StrategyDefinition] = []
        for strategy_type in self.settings.runtime.active_strategy_types:
            if strategy_type in seen:
                continue
            seen.add(strategy_type)
            definitions.append(
                StrategyDefinition(
                    id=f"{strategy_type}_{suffix}",
                    strategy_type=strategy_type,
                    name=f"{strategy_type.replace('_', ' ').title()} ({suffix})",
                    underlyings=(underlying,),
                    params={},
                )
            )
        return tuple(definitions)

    @cached_property
    def active_runtime_strategies(self) -> tuple["Strategy[Any]", ...]:
        from ceremyn.strategies import create

        return tuple(
            create(definition)
            for definition in self._runtime_strategy_definitions(suffix="runtime")
        )

    @cached_property
    def orchestrator(self) -> "RuntimeOrchestrator":
        from ceremyn.runtime.orchestrator import RuntimeOrchestrator

        # No streaming client yet (no Kite session-auth flow exists here), but the
        # orchestrator now uses the same explicit active-strategy roster the REST
        # poller uses, so the runtime's intended trading posture is visible and
        # consistent across both entry paths.
        return RuntimeOrchestrator(
            live_engine=self.live_engine,
            oms_engine=self.oms_engine,
            strategies=self.active_runtime_strategies,
            poll_interval_seconds=self.settings.runtime.poll_interval_seconds,
        )

    @cached_property
    def equity_quote_job(self) -> "EquityQuoteJob":
        from ceremyn.data.services.equity_history import fetch_all_equity_candles
        from ceremyn.data.services.equity_quotes import EquityQuoteJob

        return EquityQuoteJob(
            provider=self.kite_provider,
            cache=self.live_engine.cache,
            history_loader=fetch_all_equity_candles,
            settings=self.settings.equity_quotes,
            calendar=self.calendar,
        )

    @cached_property
    def rest_poller(self) -> "RestPricePoller":
        from ceremyn.runtime.rest_poller import RestPricePoller

        underlying = self.settings.data.underlyings[0]
        strategies = self.active_runtime_strategies
        return RestPricePoller(
            kite_provider=self.kite_provider,
            oms_engine=self.oms_engine,
            analytics=self.chain_analytics,
            cache=self.live_engine.cache,
            strategies=strategies,
            underlying=underlying,
            calendar=self.calendar,
            feature_engine=self.feature_engine,
        )

    @cached_property
    def experiment_store(self) -> "JSONExperimentStore":
        from ceremyn.research.experiment_store import JSONExperimentStore

        return JSONExperimentStore()

    @cached_property
    def experiment_manager(self) -> "ExperimentManager":
        from ceremyn.research.experiment_manager import ExperimentManager

        return ExperimentManager(self.experiment_store)

    # -- LLM assistant (M12) -------------------------------------------------
    #
    # `llm_client` is the only one of these that touches the network — and only when
    # actually called; construction just needs CEREMYN_ANTHROPIC__API_KEY, exactly like
    # `kite_broker` needs CEREMYN_KITE__API_KEY. `conversation_store`/`watchlist_store`
    # are session-scoped and in-memory only, by design (never persisted, never lives in
    # configuration).

    @cached_property
    def llm_client(self) -> "ClaudeClient":
        from ceremyn.llm.client import ClaudeClient

        return ClaudeClient.from_settings(self.settings)

    @cached_property
    def conversation_store(self) -> "InMemoryConversationStore":
        from ceremyn.llm.conversation import InMemoryConversationStore

        return InMemoryConversationStore()

    @cached_property
    def watchlist_store(self) -> "InMemoryWatchlistStore":
        from ceremyn.llm.watchlist import InMemoryWatchlistStore

        return InMemoryWatchlistStore()
