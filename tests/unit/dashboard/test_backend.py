from datetime import UTC, datetime
from decimal import Decimal

from ceremyn.backtest.statistics import EquityPoint
from ceremyn.dashboard.backend import DashboardService, DashboardSources
from ceremyn.dashboard.models import Channel, StrategyEntry
from tests.unit.dashboard.conftest import (
    FakeExecution,
    FakeOMS,
    FakePaper,
    FakePortfolio,
    make_portfolio_snapshot,
)


class FakeStrategies:
    def catalog(self) -> tuple[StrategyEntry, ...]:
        return (StrategyEntry(strategy_type="iron_fly", class_name="IronFly"),)


class TestFullService:
    def test_all_channels_produce_dicts(self, service: DashboardService) -> None:
        for channel in Channel:
            assert isinstance(service.channel_payload(channel), dict)

    def test_overview_aggregates(self, service: DashboardService) -> None:
        overview = service.overview()
        assert overview.open_orders == 1  # one PENDING order in the fixture
        assert overview.experiment_count == 0
        assert overview.alert_count >= 0

    def test_metrics_uses_session_stats(self, service: DashboardService) -> None:
        assert service.metrics().sharpe == 1.85

    def test_logs_view(self, service: DashboardService) -> None:
        assert len(service.logs().logs) == 1

    def test_execution_view_reflects_the_source(self, service: DashboardService) -> None:
        assert service.execution().armed is False
        assert service.execution().active_broker == "simulated"


class TestExecutionView:
    def test_reflects_armed_and_permitted_source(self) -> None:
        service = DashboardService(
            DashboardSources(execution=FakeExecution(armed=True, permitted=True))
        )
        view = service.execution()
        assert view.armed is True
        assert view.live_trading_permitted is True
        assert view.active_broker == "kite"


class TestStrategiesView:
    def test_reflects_the_source(self) -> None:
        service = DashboardService(DashboardSources(strategies=FakeStrategies()))
        view = service.strategies()
        assert len(view.strategies) == 1
        assert view.strategies[0].strategy_type == "iron_fly"

    def test_empty_without_a_source(self) -> None:
        service = DashboardService(DashboardSources())
        assert service.strategies().strategies == ()


class TestEmptyService:
    def test_all_views_default_without_sources(self) -> None:
        service = DashboardService(DashboardSources())
        assert service.overview().open_orders == 0
        assert service.portfolio().position_count == 0
        assert service.orders().total == 0
        assert service.live().underlyings == ()
        assert service.features().feature_count == 0
        assert service.risk().decisions == ()
        assert service.oms().orders_submitted == 0
        assert service.research().experiment_count == 0
        assert service.paper().submitted == 0
        # No sources connected -> components report unhealthy, but the heartbeat default holds.
        assert service.health().heartbeat_healthy is True
        assert service.health().healthy is False
        assert service.logs().logs == ()
        assert service.metrics().pnl == 0.0
        assert service.execution().armed is False
        assert service.execution().active_broker == "simulated"
        assert service.alerts().count == 0
        assert service.equity_history().points == ()


class TestEquityHistoryView:
    def test_reflects_the_oms_sources_real_curve(self) -> None:
        point = EquityPoint(
            timestamp=datetime(2026, 7, 16, 4, 0, tzinfo=UTC),
            cash=Decimal("99000"),
            equity=Decimal("99500"),
            drawdown=Decimal("500"),
        )
        service = DashboardService(DashboardSources(oms=FakeOMS(equity_curve=(point,))))
        view = service.equity_history()
        assert len(view.points) == 1
        assert view.points[0].equity == 99500.0

    def test_empty_without_an_oms_source(self) -> None:
        service = DashboardService(DashboardSources())
        assert service.equity_history().points == ()


class TestPortfolioResolution:
    def test_prefers_oms_then_portfolio_then_paper(self) -> None:
        # Only paper has a snapshot -> it is used.
        service = DashboardService(DashboardSources(paper=FakePaper()))
        assert service.portfolio().realized_pnl == 1000.0

    def test_portfolio_source_used_when_oms_absent(self) -> None:
        service = DashboardService(
            DashboardSources(portfolio=FakePortfolio(make_portfolio_snapshot()))
        )
        assert service.positions() is not None
        assert service.portfolio().realized_pnl == 1000.0
