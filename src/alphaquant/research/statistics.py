"""Experiment metrics: a flat, storable view mapped from the backtest engine.

This module does NOT reimplement any metric. Every value is mapped from
``BacktestStatistics`` (backtest/statistics.py) or ``MonteCarloResult``
(backtest/montecarlo.py). ``composite_score`` is the only derived quantity and is a
simple weighted blend used for leaderboard ranking.
"""

from pydantic import BaseModel, ConfigDict

from alphaquant.backtest.montecarlo import MonteCarloResult
from alphaquant.backtest.report import BacktestReport
from alphaquant.backtest.statistics import ReturnBucket


class ExperimentMetrics(BaseModel):
    """The full M6 metric set, flattened for storage and ranking."""

    model_config = ConfigDict(frozen=True)

    total_return: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    calmar: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    max_drawdown: float = 0.0
    largest_drawdown: float = 0.0  # == max_drawdown; named per the M6 spec
    cagr: float = 0.0
    average_win: float = 0.0
    average_loss: float = 0.0
    win_rate: float = 0.0
    probability_of_ruin: float = 0.0
    trade_count: int = 0
    monthly_returns: tuple[ReturnBucket, ...] = ()
    yearly_returns: tuple[ReturnBucket, ...] = ()


# Higher-is-better metrics use the raw value; drawdown-style metrics are negated so
# that "bigger composite is better" holds uniformly.
_DEFAULT_COMPOSITE_WEIGHTS: dict[str, float] = {
    "sharpe": 0.35,
    "sortino": 0.25,
    "profit_factor": 0.20,
    "cagr": 0.20,
}


def metrics_from_report(
    report: BacktestReport,
    *,
    montecarlo: MonteCarloResult | None = None,
) -> ExperimentMetrics:
    """Map a BacktestReport (and optional Monte Carlo result) to ExperimentMetrics."""
    stats = report.statistics
    return ExperimentMetrics(
        total_return=stats.total_return,
        sharpe=stats.sharpe,
        sortino=stats.sortino,
        calmar=stats.calmar,
        profit_factor=stats.profit_factor,
        expectancy=stats.expectancy,
        max_drawdown=stats.maximum_drawdown,
        largest_drawdown=stats.maximum_drawdown,
        cagr=stats.cagr,
        average_win=stats.average_win,
        average_loss=stats.average_loss,
        win_rate=stats.win_rate,
        probability_of_ruin=(montecarlo.probability_of_ruin if montecarlo else 0.0),
        trade_count=len(report.trade_ledger),
        monthly_returns=stats.monthly_returns,
        yearly_returns=stats.yearly_returns,
    )


def composite_score(
    metrics: ExperimentMetrics,
    *,
    weights: dict[str, float] | None = None,
) -> float:
    """Weighted blend of performance metrics for ranking (higher is better)."""
    active = weights or _DEFAULT_COMPOSITE_WEIGHTS
    total_weight = sum(active.values())
    if total_weight <= 0:
        return 0.0
    score = sum(float(getattr(metrics, name)) * weight for name, weight in active.items())
    return round(score / total_weight, 6)
