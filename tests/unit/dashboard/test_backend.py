from alphaquant.dashboard.backend import DashboardService, DashboardSources
from alphaquant.dashboard.models import Channel
from tests.unit.dashboard.conftest import FakePaper, FakePortfolio, make_portfolio_snapshot


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
        assert service.alerts().count == 0


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
