from alphaquant.config import Settings
from alphaquant.core.calendar import MarketCalendar
from alphaquant.core.container import Container
from alphaquant.core.events import EventBus
from alphaquant.core.instrumentation import ObservableRiskEngine, ReadableHeartbeatMonitor
from alphaquant.features.engine import FeatureEngine
from alphaquant.live.engine import LiveMarketDataEngine
from alphaquant.live.reconnect import ReconnectManager
from alphaquant.oms.engine import OrderManagementEngine
from alphaquant.paper.engine import PaperTradingEngine
from alphaquant.research.experiment_manager import ExperimentManager


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
    "oms_engine",
    "paper_engine",
    "live_engine",
    "experiment_store",
    "experiment_manager",
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
    assert isinstance(container.oms_engine, OrderManagementEngine)
    assert isinstance(container.paper_engine, PaperTradingEngine)
    assert isinstance(container.live_engine, LiveMarketDataEngine)
    assert isinstance(container.experiment_manager, ExperimentManager)


def test_runtime_engines_share_one_risk_engine() -> None:
    container = make_container()
    assert container.oms_engine.risk_engine is container.risk_engine
    assert container.paper_engine.risk_engine is container.risk_engine


def test_oms_engine_reconciles_clean_with_no_broker() -> None:
    container = make_container()
    report = container.oms_engine.reconcile()
    assert report.reconciled is True
    assert report.missing_orders == ()


def test_runtime_engines_never_touch_the_database() -> None:
    container = make_container()
    for attr in RUNTIME_ENGINE_ATTRS:
        getattr(container, attr)
    # `_db` is the cached_property backing `.engine`/`.session_factory`; it must stay
    # unresolved since nothing in the runtime-engine wiring needs Postgres.
    assert "_db" not in container.__dict__
