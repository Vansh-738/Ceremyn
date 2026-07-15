from alphaquant.broker.simulated import SimulatedBroker
from alphaquant.config import Settings
from alphaquant.core.calendar import MarketCalendar
from alphaquant.core.container import Container
from alphaquant.core.events import EventBus
from alphaquant.core.instrumentation import ObservableRiskEngine, ReadableHeartbeatMonitor
from alphaquant.execution import GatedBrokerAdapter, KiteBroker, LiveTradingGate
from alphaquant.features.engine import FeatureEngine
from alphaquant.live.engine import LiveMarketDataEngine
from alphaquant.live.reconnect import ReconnectManager
from alphaquant.llm.client import ClaudeClient
from alphaquant.llm.conversation import InMemoryConversationStore
from alphaquant.llm.watchlist import InMemoryWatchlistStore
from alphaquant.oms.engine import OrderManagementEngine
from alphaquant.paper.engine import PaperTradingEngine
from alphaquant.research.experiment_manager import ExperimentManager
from alphaquant.runtime.orchestrator import RuntimeOrchestrator


def make_container() -> Container:
    return Container(Settings(_env_file=None))  # type: ignore[call-arg]


def test_container_provides_singletons() -> None:
    container = make_container()
    assert container.event_bus is container.event_bus
    assert container.calendar is container.calendar


def test_container_wiring_types() -> None:
    container = make_container()
    assert isinstance(container.event_bus, EventBus)
    assert isinstance(container.calendar, MarketCalendar)


def test_containers_are_isolated() -> None:
    assert make_container().event_bus is not make_container().event_bus


RUNTIME_ENGINE_ATTRS = (
    "heartbeat_monitor",
    "reconnect_manager",
    "risk_engine",
    "feature_cache",
    "feature_engine",
    "null_broker",
    "simulated_broker",
    "live_trading_gate",
    "gated_broker",
    "oms_engine",
    "paper_engine",
    "live_engine",
    "experiment_store",
    "experiment_manager",
    "conversation_store",
    "watchlist_store",
    "orchestrator",
)


def test_runtime_engines_are_singletons() -> None:
    container = make_container()
    for attr in RUNTIME_ENGINE_ATTRS:
        assert getattr(container, attr) is getattr(container, attr), attr


def test_runtime_engine_types() -> None:
    container = make_container()
    assert isinstance(container.heartbeat_monitor, ReadableHeartbeatMonitor)
    assert isinstance(container.reconnect_manager, ReconnectManager)
    assert isinstance(container.risk_engine, ObservableRiskEngine)
    assert isinstance(container.feature_engine, FeatureEngine)
    assert isinstance(container.simulated_broker, SimulatedBroker)
    assert isinstance(container.live_trading_gate, LiveTradingGate)
    assert isinstance(container.gated_broker, GatedBrokerAdapter)
    assert isinstance(container.oms_engine, OrderManagementEngine)
    assert isinstance(container.paper_engine, PaperTradingEngine)
    assert isinstance(container.live_engine, LiveMarketDataEngine)
    assert isinstance(container.experiment_manager, ExperimentManager)
    assert isinstance(container.conversation_store, InMemoryConversationStore)
    assert isinstance(container.watchlist_store, InMemoryWatchlistStore)
    assert isinstance(container.orchestrator, RuntimeOrchestrator)


def test_runtime_engines_share_one_risk_engine() -> None:
    container = make_container()
    assert container.oms_engine.risk_engine is container.risk_engine
    assert container.paper_engine.risk_engine is container.risk_engine


def test_oms_engine_reconciles_clean_with_gated_fallback_broker() -> None:
    container = make_container()
    report = container.oms_engine.reconcile()
    assert report.reconciled is True
    assert report.missing_orders == ()


def test_oms_engine_is_wired_with_the_gated_broker_only() -> None:
    container = make_container()
    assert container.oms_engine.router.brokers == (container.gated_broker,)


def test_gated_broker_uses_the_shared_simulated_fallback() -> None:
    container = make_container()
    # No gates open by default: OMS's own broker calls resolve to the same
    # SimulatedBroker singleton the container wires everywhere else.
    assert container.gated_broker.fetch_cash() == container.simulated_broker.fetch_cash()


def test_runtime_engines_never_touch_the_database() -> None:
    container = make_container()
    for attr in RUNTIME_ENGINE_ATTRS:
        getattr(container, attr)
    # `_db` is the cached_property backing `.engine`/`.session_factory`; it must stay
    # unresolved since nothing in the runtime-engine wiring needs Postgres.
    assert "_db" not in container.__dict__


def test_kite_broker_is_never_touched_without_credentials() -> None:
    container = make_container()
    for attr in RUNTIME_ENGINE_ATTRS:
        getattr(container, attr)
    # No ALPHAQUANT_KITE__API_KEY in this dev environment: `kite_broker` would raise
    # BrokerError if constructed, so it must stay untouched until live routing is
    # actually permitted (see `execution.gated_broker.GatedBrokerAdapter`).
    assert "kite_broker" not in container.__dict__


def test_kite_broker_constructs_when_credentials_are_present() -> None:
    settings = Settings(_env_file=None, kite={"api_key": "test-key"})  # type: ignore[call-arg]
    container = Container(settings)
    assert isinstance(container.kite_broker, KiteBroker)
    assert container.kite_broker is container.kite_broker


def test_llm_client_is_never_touched_without_credentials() -> None:
    container = make_container()
    for attr in RUNTIME_ENGINE_ATTRS:
        getattr(container, attr)
    # No ALPHAQUANT_ANTHROPIC__API_KEY in this dev environment: `llm_client` would raise
    # LLMProviderError if constructed, so nothing in ordinary runtime wiring may touch it.
    assert "llm_client" not in container.__dict__


def test_llm_client_constructs_when_credentials_are_present() -> None:
    settings = Settings(_env_file=None, anthropic={"api_key": "demo-key"})  # type: ignore[call-arg]
    container = Container(settings)
    assert isinstance(container.llm_client, ClaudeClient)
    assert container.llm_client is container.llm_client


def test_oms_engine_journal_is_persisted_and_stable_across_containers(
    tmp_path, monkeypatch
) -> None:
    """`oms_engine` must use a durable, stably-named journal (not the default
    in-memory one, not a random-uuid session id) so a restart re-opens the *same*
    file rather than starting fresh empty every time."""
    from alphaquant.oms.journal import JSONJournalStore

    monkeypatch.chdir(tmp_path)  # `JSONJournalStore`'s default root is a relative path

    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    first = Container(settings).oms_engine
    second = Container(settings).oms_engine  # a fresh process/container, same settings

    assert isinstance(first.journal.store, JSONJournalStore)
    assert first.journal.session_id == second.journal.session_id == f"oms-{settings.environment}"
    assert first.journal.store.path == second.journal.store.path
