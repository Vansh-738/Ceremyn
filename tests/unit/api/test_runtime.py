from datetime import timedelta

from ceremyn.api.runtime import build_dashboard_sources
from ceremyn.config import Settings, TradingMode
from ceremyn.core.container import Container
from ceremyn.core.timeutils import now_utc
from tests.unit.backtest.helpers import make_chain

_PORT_METHODS = {
    "live": ("live_metrics", "market_snapshots", "heartbeat", "reconnect"),
    "oms": (
        "orders",
        "oms_metrics",
        "kill_switch",
        "portfolio_snapshot",
        "equity_curve",
        "reconciliation",
    ),
    "portfolio": ("portfolio_snapshot", "session_statistics"),
    "risk": ("recent_decisions",),
    "features": ("latest_features", "cache_hits", "cache_misses", "cache_size"),
    "paper": ("monitor", "portfolio_snapshot"),
    "research": ("experiments",),
    "execution": ("is_armed", "live_trading_permitted", "active_broker_name"),
    "strategies": ("catalog",),
    "logs": ("recent_logs",),
    "data_feed": ("status",),
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


def test_live_source_falls_back_to_rest_poller_cache() -> None:
    """`RestPricePoller` (the actually-running data path when no Kite streaming
    client is configured) writes chains into `live_engine.cache`, not into
    `LiveMarketDataEngine`'s own tick-driven snapshot store -- without this
    fallback, the dashboard's "Live Market" page shows "no feed" forever even
    while the poller is ticking real spot/PCR/ATM data every cycle."""
    container = make_container()
    sources = build_dashboard_sources(container)
    now = now_utc()
    chain = make_chain(timestamp=now, last_price="100", bid="99", ask="101")
    container.live_engine.cache.set_chain(chain)

    (snapshot,) = sources.live.market_snapshots()

    assert snapshot.underlying == "NIFTY"
    assert snapshot.spot == chain.spot
    assert snapshot.option_chain.atm_strike == chain.atm_strike
    assert snapshot.timestamp == now


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


def test_data_feed_source_returns_none_without_kite_credentials() -> None:
    # Regression: building the real poller needs `container.kite_provider`, which
    # raises BrokerError without CEREMYN_KITE__API_KEY configured -- that's a
    # completely normal state (e.g. research-mode-only setups), and must return
    # None rather than propagate and break every other dashboard channel.
    from ceremyn.api.runtime import _DataFeedSourceAdapter

    sources = build_dashboard_sources(make_container())
    assert sources.data_feed is not None
    assert sources.data_feed.status() is None

    adapter = _DataFeedSourceAdapter(make_container())
    assert adapter.status() is None


def test_data_feed_source_reflects_the_poller_state() -> None:
    # Deliberately bypasses the real Container/kite_provider (needs real Kite
    # credentials to construct) -- mirrors the same caution
    # test_execution_source_never_touches_kite_credentials takes elsewhere.
    from ceremyn.api.runtime import _DataFeedSourceAdapter

    class FakePoller:
        consecutive_failures = 4
        last_error = "Kite LTP fetch failed: Incorrect `api_key` or `access_token`."
        orphaned_symbols: tuple[str, ...] = ()

    class FakeContainer:
        rest_poller = FakePoller()

    adapter = _DataFeedSourceAdapter(FakeContainer())  # type: ignore[arg-type]
    status = adapter.status()
    assert status is not None
    assert status.consecutive_failures == 4
    assert "access_token" in status.last_error


def test_portfolio_source_zero_state() -> None:
    sources = build_dashboard_sources(make_container())
    assert sources.portfolio is not None
    assert sources.portfolio.portfolio_snapshot() is not None
    stats = sources.portfolio.session_statistics()
    assert stats is not None
    assert stats.sharpe == 0.0


def test_log_source_reflects_the_ring_buffer() -> None:
    from ceremyn.core import logging as logging_module
    from ceremyn.core.logging import _capture_to_ring_buffer

    logging_module._RING_BUFFER.clear()
    try:
        entry = {
            "event": "signal_submitted",
            "level": "info",
            "timestamp": "2026-07-16T00:00:00Z",
        }
        _capture_to_ring_buffer(None, "info", entry)
        sources = build_dashboard_sources(make_container())
        assert sources.logs is not None
        rows = sources.logs.recent_logs(10)
        assert len(rows) == 1
        assert rows[0].event == "signal_submitted"
        assert rows[0].level == "info"
    finally:
        logging_module._RING_BUFFER.clear()


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


def test_execution_source_zero_state() -> None:
    sources = build_dashboard_sources(make_container())
    assert sources.execution is not None
    assert sources.execution.is_armed() is False
    assert sources.execution.live_trading_permitted() is False
    assert sources.execution.active_broker_name() == "simulated"


def test_execution_source_reflects_armed_state() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, trading_mode=TradingMode.LIVE, live_trading_enabled=True
    )
    container = Container(settings)
    container.live_trading_gate.arm(settings=settings, reason="ops approved")
    sources = build_dashboard_sources(container)
    assert sources.execution is not None
    assert sources.execution.is_armed() is True
    assert sources.execution.live_trading_permitted() is True
    assert sources.execution.active_broker_name() == "kite"


def test_execution_source_never_touches_kite_credentials() -> None:
    container = make_container()
    sources = build_dashboard_sources(container)
    assert sources.execution is not None
    sources.execution.is_armed()
    sources.execution.live_trading_permitted()
    sources.execution.active_broker_name()
    assert "kite_broker" not in container.__dict__


def test_strategy_source_catalog() -> None:
    sources = build_dashboard_sources(make_container())
    assert sources.strategies is not None
    entries = sources.strategies.catalog()
    assert len(entries) >= 9  # 3 from M3 + 6 from M14
    by_type = {entry.strategy_type: entry for entry in entries}
    assert "calendar_spread" in by_type
    assert by_type["calendar_spread"].class_name == "CalendarSpread"
    assert "properties" in by_type["calendar_spread"].params_schema


def test_strategy_source_needs_no_container_engine() -> None:
    container = make_container()
    sources = build_dashboard_sources(container)
    assert sources.strategies is not None
    sources.strategies.catalog()
    for attr in ("oms_engine", "paper_engine", "live_engine", "risk_engine"):
        assert attr not in container.__dict__, attr


def test_sources_do_not_build_engines_eagerly() -> None:
    container = make_container()
    build_dashboard_sources(container)
    for attr in (
        "oms_engine",
        "paper_engine",
        "live_engine",
        "risk_engine",
        "kite_broker",
        "rest_poller",
    ):
        assert attr not in container.__dict__, attr
