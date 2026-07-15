from datetime import timedelta

from alphaquant.api.runtime import build_dashboard_sources
from alphaquant.config import Settings
from alphaquant.core.container import Container
from alphaquant.core.timeutils import now_utc

_PORT_METHODS = {
    "live": ("live_metrics", "market_snapshots", "heartbeat", "reconnect"),
    "oms": ("orders", "oms_metrics", "kill_switch", "portfolio_snapshot", "reconciliation"),
    "risk": ("recent_decisions",),
    "features": ("latest_features", "cache_hits", "cache_misses", "cache_size"),
    "paper": ("monitor", "portfolio_snapshot"),
    "research": ("experiments",),
}


def make_container() -> Container:
    return Container(Settings(_env_file=None))  # type: ignore[call-arg]


def test_sources_satisfy_the_read_port_protocols() -> None:
    # The Protocols in `dashboard.backend` aren't `@runtime_checkable`, so this checks
    # structurally: every port method the dashboard calls must exist and be callable.
    sources = build_dashboard_sources(make_container())
    for field, methods in _PORT_METHODS.items():
        source = getattr(sources, field)
        assert source is not None, field
        for method in methods:
            assert callable(getattr(source, method)), f"{field}.{method}"


def test_live_source_zero_state() -> None:
    sources = build_dashboard_sources(make_container())
    assert sources.live is not None
    assert sources.live.live_metrics() is not None
    assert sources.live.market_snapshots() == ()
    assert sources.live.heartbeat().is_healthy is True
    assert sources.live.reconnect().attempts == 0


def test_oms_source_zero_state() -> None:
    sources = build_dashboard_sources(make_container())
    assert sources.oms is not None
    assert sources.oms.orders() == ()
    assert sources.oms.kill_switch().armed is False
    assert sources.oms.portfolio_snapshot() is not None
    reconciliation = sources.oms.reconciliation()
    assert reconciliation is not None
    assert reconciliation.reconciled is True
    assert reconciliation.missing_orders == 0


def test_oms_reconciliation_is_rate_limited() -> None:
    container = make_container()
    sources = build_dashboard_sources(container)
    assert sources.oms is not None

    calls = 0
    original_reconcile = container.oms_engine.reconcile

    def counting_reconcile(*, now: object = None) -> object:
        nonlocal calls
        calls += 1
        return original_reconcile(now=now)  # type: ignore[arg-type]

    container.oms_engine.reconcile = counting_reconcile  # type: ignore[method-assign]

    first = sources.oms.reconciliation()
    second = sources.oms.reconciliation()
    assert first is second
    assert calls == 1

    # Simulate the throttle window elapsing: the next read recomputes.
    sources.oms._last_reconciled_at = now_utc() - timedelta(minutes=5)  # type: ignore[attr-defined]
    sources.oms.reconciliation()
    assert calls == 2


def test_risk_source_starts_empty() -> None:
    sources = build_dashboard_sources(make_container())
    assert sources.risk is not None
    assert sources.risk.recent_decisions() == ()


def test_feature_source_zero_state() -> None:
    sources = build_dashboard_sources(make_container())
    assert sources.features is not None
    assert sources.features.latest_features() is None
    assert sources.features.cache_hits() == 0
    assert sources.features.cache_misses() == 0
    assert sources.features.cache_size() == 0


def test_paper_source_zero_state() -> None:
    sources = build_dashboard_sources(make_container())
    assert sources.paper is not None
    monitor = sources.paper.monitor()
    assert monitor is not None
    assert monitor.submitted == 0
    portfolio = sources.paper.portfolio_snapshot()
    assert portfolio is not None
    assert portfolio.positions == ()


def test_research_source_starts_empty() -> None:
    sources = build_dashboard_sources(make_container())
    assert sources.research is not None
    assert sources.research.experiments() == ()


def test_sources_do_not_build_engines_eagerly() -> None:
    container = make_container()
    build_dashboard_sources(container)
    for attr in ("oms_engine", "paper_engine", "live_engine", "risk_engine"):
        assert attr not in container.__dict__, attr
