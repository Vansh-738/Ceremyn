from datetime import UTC, datetime
from decimal import Decimal

from ceremyn.backtest.statistics import EquityPoint
from ceremyn.dashboard import views
from ceremyn.dashboard.models import ReconciliationStatus
from ceremyn.oms.orders import OMSExecutionState
from tests.unit.dashboard.conftest import (
    make_feature_set,
    make_market_snapshot,
    make_oms_metrics,
    make_oms_order,
    make_portfolio_snapshot,
    make_position,
    make_risk_decision,
)


class TestPortfolio:
    def test_maps_snapshot(self) -> None:
        view = views.build_portfolio(make_portfolio_snapshot())
        assert view.realized_pnl == 1000.0
        assert view.unrealized_pnl == 250.0
        assert view.greeks.delta == 0.5
        assert view.exposure.gross_notional == 500000.0
        assert view.exposure.by_underlying == {"NIFTY": 100000.0}

    def test_none_returns_empty(self) -> None:
        assert views.build_portfolio(None).position_count == 0


class TestEquityHistory:
    def test_maps_real_curve_points(self) -> None:
        curve = (
            EquityPoint(
                timestamp=datetime(2026, 7, 16, 4, 0, tzinfo=UTC),
                cash=Decimal("99000"),
                equity=Decimal("99500"),
                drawdown=Decimal("500"),
            ),
            EquityPoint(
                timestamp=datetime(2026, 7, 16, 5, 0, tzinfo=UTC),
                cash=Decimal("99000"),
                equity=Decimal("100200"),
                drawdown=Decimal("0"),
            ),
        )
        view = views.build_equity_history(curve)
        assert len(view.points) == 2
        assert view.points[0].equity == 99500.0
        assert view.points[1].drawdown == 0.0

    def test_empty_curve_returns_no_points(self) -> None:
        assert views.build_equity_history(()).points == ()

    def test_caps_to_the_most_recent_points(self) -> None:
        curve = tuple(
            EquityPoint(
                timestamp=datetime(2026, 7, 16, 4, i % 60, tzinfo=UTC),
                cash=Decimal("100000"),
                equity=Decimal(str(100000 + i)),
                drawdown=Decimal("0"),
            )
            for i in range(600)
        )
        view = views.build_equity_history(curve)
        assert len(view.points) == 500
        assert view.points[-1].equity == 100599.0


class TestOrders:
    def test_counts_and_rows(self) -> None:
        orders = (
            make_oms_order(state=OMSExecutionState.PENDING),
            make_oms_order(state=OMSExecutionState.FILLED, filled=25),
            make_oms_order(state=OMSExecutionState.REJECTED),
        )
        view = views.build_orders(orders, page=1, page_size=50)
        assert view.total == 3
        assert view.open_count == 1
        assert view.filled_count == 1
        assert view.rejected_count == 1
        assert len(view.orders) == 3

    def test_pagination(self) -> None:
        orders = tuple(make_oms_order() for _ in range(5))
        view = views.build_orders(orders, page=2, page_size=2)
        assert view.page == 2
        assert len(view.orders) == 2
        assert view.total == 5


class TestPositions:
    def test_direction_counts(self) -> None:
        positions = (make_position(quantity=25), make_position(strike=23000, quantity=-25))
        view = views.build_positions(make_portfolio_snapshot(positions=positions))
        assert view.long_count == 1
        assert view.short_count == 1

    def test_none(self) -> None:
        assert views.build_positions(None).positions == ()

    def test_flat_positions_skipped(self) -> None:
        positions = (make_position(quantity=25), make_position(strike=23000, quantity=0))
        view = views.build_positions(make_portfolio_snapshot(positions=positions))
        assert len(view.positions) == 1  # the flat position is excluded


class TestLive:
    def test_maps_market_snapshot(self) -> None:
        view = views.build_live(None, (make_market_snapshot(),))
        assert view.underlyings[0].underlying == "NIFTY"
        assert view.underlyings[0].market_status == "open"
        assert view.underlyings[0].atm_strike is not None


class TestFeatures:
    def test_hit_rate_and_sample(self) -> None:
        view = views.build_features(make_feature_set(), hits=8, misses=2, size=10)
        assert view.cache_hit_rate == 0.8
        assert view.feature_count == 2
        assert "pcr" in view.sample

    def test_no_features(self) -> None:
        view = views.build_features(None, hits=0, misses=0, size=0)
        assert view.feature_set_version is None
        assert view.cache_hit_rate == 0.0


class TestRisk:
    def test_counts_violations(self) -> None:
        view = views.build_risk((make_risk_decision(approved=False),))
        assert view.violation_count == 1
        assert view.latest_score == 90.0
        assert view.decisions[0].approved is False

    def test_empty(self) -> None:
        assert views.build_risk(()).latest_score is None


class TestOMS:
    def test_maps_metrics_and_reconciliation(self) -> None:
        view = views.build_oms(
            make_oms_metrics().snapshot(make_risk_decision().timestamp),
            kill_switch_armed=True,
            kill_switch_reason="loss",
            reconciliation=ReconciliationStatus(reconciled=False, position_drift=2),
        )
        assert view.orders_submitted == 1
        assert view.kill_switch_armed is True
        assert view.reconciled is False
        assert view.reconciliation_drift == 2

    def test_no_metrics(self) -> None:
        view = views.build_oms(
            None, kill_switch_armed=False, kill_switch_reason="", reconciliation=None
        )
        assert view.orders_submitted == 0
        assert view.reconciled is True


class TestPaper:
    def test_without_monitor_uses_portfolio(self) -> None:
        view = views.build_paper(None, make_portfolio_snapshot())
        assert view.realized_pnl == 1000.0
        assert view.submitted == 0
