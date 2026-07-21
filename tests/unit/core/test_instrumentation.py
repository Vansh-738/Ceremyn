from datetime import UTC, datetime

from ceremyn.core.instrumentation import ObservableRiskEngine, ReadableHeartbeatMonitor
from ceremyn.oms.positions import OMSPortfolio
from tests.unit.oms.conftest import make_signal, permissive_settings


def test_readable_heartbeat_monitor_exposes_state() -> None:
    monitor = ReadableHeartbeatMonitor()
    assert monitor.state.is_healthy is True
    assert monitor.state.last_seen_at is None

    recorded = monitor.record(datetime(2026, 7, 15, 4, 20, tzinfo=UTC))
    assert monitor.state == recorded


def test_readable_heartbeat_monitor_reflects_check() -> None:
    monitor = ReadableHeartbeatMonitor(timeout_seconds=1.0)
    monitor.record(datetime(2026, 7, 15, 4, 20, 0, tzinfo=UTC))
    stale = monitor.check(datetime(2026, 7, 15, 4, 20, 10, tzinfo=UTC))
    assert monitor.state == stale
    assert monitor.state.is_healthy is False


def test_observable_risk_engine_starts_with_no_history() -> None:
    engine = ObservableRiskEngine(permissive_settings())
    assert engine.recent_decisions() == ()


def test_observable_risk_engine_records_evaluate_and_validate() -> None:
    engine = ObservableRiskEngine(permissive_settings())
    portfolio = OMSPortfolio().snapshot()
    signal = make_signal()

    decision = engine.evaluate(portfolio, signal)
    assert engine.recent_decisions() == (decision,)

    engine.validate(portfolio, signal)
    assert len(engine.recent_decisions()) == 2


def test_observable_risk_engine_history_is_bounded() -> None:
    engine = ObservableRiskEngine(permissive_settings(), history_size=2)
    portfolio = OMSPortfolio().snapshot()
    signal = make_signal()

    engine.evaluate(portfolio, signal)
    second = engine.evaluate(portfolio, signal)
    third = engine.evaluate(portfolio, signal)

    assert engine.recent_decisions() == (second, third)
