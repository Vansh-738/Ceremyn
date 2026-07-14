from decimal import Decimal

from alphaquant.backtest.montecarlo import MonteCarloResult
from alphaquant.backtest.report import BacktestReport
from alphaquant.backtest.statistics import BacktestStatistics, ReturnBucket
from alphaquant.domain import PortfolioSnapshot
from alphaquant.research.statistics import (
    ExperimentMetrics,
    composite_score,
    metrics_from_report,
)
from tests.unit.backtest.helpers import make_strategy_definition


def make_report(**stat_overrides: object) -> BacktestReport:
    stats = BacktestStatistics(
        total_return=12.5,
        cagr=8.0,
        sharpe=1.5,
        sortino=2.0,
        calmar=1.1,
        profit_factor=1.8,
        expectancy=250.0,
        maximum_drawdown=1500.0,
        average_win=400.0,
        average_loss=-200.0,
        win_rate=60.0,
        monthly_returns=(ReturnBucket(period="2026-07", return_pct=3.2),),
        yearly_returns=(ReturnBucket(period="2026", return_pct=12.5),),
        **stat_overrides,  # type: ignore[arg-type]
    )
    return BacktestReport(
        strategy=make_strategy_definition(),
        statistics=stats,
        final_portfolio=PortfolioSnapshot(buying_power=Decimal("1000000")),
    )


class TestMetricsMapping:
    def test_maps_every_metric_from_statistics(self) -> None:
        metrics = metrics_from_report(make_report())
        assert metrics.total_return == 12.5
        assert metrics.cagr == 8.0
        assert metrics.sharpe == 1.5
        assert metrics.sortino == 2.0
        assert metrics.calmar == 1.1
        assert metrics.profit_factor == 1.8
        assert metrics.expectancy == 250.0
        assert metrics.average_win == 400.0
        assert metrics.average_loss == -200.0
        assert metrics.win_rate == 60.0
        assert len(metrics.monthly_returns) == 1
        assert len(metrics.yearly_returns) == 1

    def test_largest_drawdown_equals_max_drawdown(self) -> None:
        metrics = metrics_from_report(make_report())
        assert metrics.max_drawdown == 1500.0
        assert metrics.largest_drawdown == metrics.max_drawdown

    def test_probability_of_ruin_from_montecarlo(self) -> None:
        mc = MonteCarloResult(probability_of_ruin=0.125)
        metrics = metrics_from_report(make_report(), montecarlo=mc)
        assert metrics.probability_of_ruin == 0.125

    def test_probability_of_ruin_defaults_zero_without_montecarlo(self) -> None:
        assert metrics_from_report(make_report()).probability_of_ruin == 0.0

    def test_trade_count_from_ledger_length(self) -> None:
        assert metrics_from_report(make_report()).trade_count == 0


class TestCompositeScore:
    def test_weighted_blend(self) -> None:
        metrics = ExperimentMetrics(sharpe=2.0, sortino=1.0, profit_factor=1.0, cagr=1.0)
        # (0.35*2 + 0.25*1 + 0.20*1 + 0.20*1) / 1.0 = 1.35
        assert composite_score(metrics) == 1.35

    def test_custom_weights(self) -> None:
        metrics = ExperimentMetrics(sharpe=3.0, sortino=1.0)
        assert composite_score(metrics, weights={"sharpe": 1.0, "sortino": 1.0}) == 2.0

    def test_zero_weights_return_zero(self) -> None:
        assert composite_score(ExperimentMetrics(sharpe=5.0), weights={"sharpe": 0.0}) == 0.0
