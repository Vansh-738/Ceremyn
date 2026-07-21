from ceremyn.backtest.statistics import BacktestStatistics
from ceremyn.dashboard.health import build_health
from ceremyn.dashboard.metrics import build_metrics
from ceremyn.dashboard.models import DataFeedStatus
from ceremyn.live.heartbeat import HeartbeatState
from ceremyn.live.reconnect import ReconnectState
from tests.unit.dashboard.conftest import NOW, make_oms_metrics, make_portfolio_snapshot


class TestMetrics:
    def test_maps_from_snapshots(self) -> None:
        view = build_metrics(
            portfolio=make_portfolio_snapshot(),
            oms_metrics=make_oms_metrics().snapshot(NOW),
            open_orders=3,
            statistics=BacktestStatistics(sharpe=2.1),
            feature_cache_hit_rate=0.8,
            experiment_count=5,
        )
        assert view.pnl == 1250.0  # realized 1000 + unrealized 250
        assert view.drawdown == 300.0
        assert view.sharpe == 2.1
        assert view.greeks.delta == 0.5
        assert view.open_orders == 3
        assert view.filled_orders == 1
        assert view.experiment_count == 5

    def test_defaults_when_empty(self) -> None:
        view = build_metrics()
        assert view.pnl == 0.0
        assert view.sharpe == 0.0
        assert view.filled_orders == 0


class TestHealth:
    def test_healthy_when_all_present(self) -> None:
        view = build_health(
            heartbeat=HeartbeatState(is_healthy=True, last_seen_at=NOW, delay_seconds=0.5),
            reconnect=ReconnectState(attempts=0, is_reconnecting=False),
            oms_metrics=make_oms_metrics().snapshot(NOW),
            components_present={"live": True, "oms": True},
        )
        assert view.heartbeat_healthy is True
        assert view.healthy is True
        assert all(c.healthy for c in view.components)

    def test_unhealthy_component(self) -> None:
        view = build_health(components_present={"live": True, "oms": False})
        assert view.healthy is False
        oms = next(c for c in view.components if c.name == "oms")
        assert oms.healthy is False
        assert oms.detail

    def test_defaults(self) -> None:
        view = build_health()
        assert view.heartbeat_healthy is True
        assert view.broker_uptime_ratio == 1.0

    def test_failing_data_feed_makes_overall_unhealthy(self) -> None:
        # Regression: "Overall: HEALTHY" must not sit next to a critical
        # data-feed-failure alert derived from the exact same underlying state.
        view = build_health(
            components_present={"live": True, "oms": True},
            data_feed_status=DataFeedStatus(consecutive_failures=3, last_error="token expired"),
        )
        assert view.healthy is False
        feed = next(c for c in view.components if c.name == "data_feed")
        assert feed.healthy is False
        assert feed.detail == "token expired"

    def test_single_transient_data_feed_failure_stays_healthy(self) -> None:
        view = build_health(
            components_present={"live": True, "oms": True},
            data_feed_status=DataFeedStatus(consecutive_failures=1),
        )
        assert view.healthy is True
        feed = next(c for c in view.components if c.name == "data_feed")
        assert feed.healthy is True

    def test_no_data_feed_component_when_source_absent(self) -> None:
        view = build_health(components_present={"live": True})
        assert all(c.name != "data_feed" for c in view.components)
