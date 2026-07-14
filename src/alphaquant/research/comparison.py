"""Compare two experiments metric-by-metric with deltas and a winner per metric."""

from pydantic import BaseModel, ConfigDict

from alphaquant.research.experiment import Experiment

# Metric name -> whether a higher value is better (drives the per-metric winner).
_HIGHER_IS_BETTER: dict[str, bool] = {
    "total_return": True,
    "sharpe": True,
    "sortino": True,
    "calmar": True,
    "profit_factor": True,
    "expectancy": True,
    "cagr": True,
    "average_win": True,
    "win_rate": True,
    "max_drawdown": False,
    "largest_drawdown": False,
    "probability_of_ruin": False,
    "average_loss": True,  # less-negative is better
}


class MetricComparison(BaseModel):
    model_config = ConfigDict(frozen=True)

    metric: str
    value_a: float
    value_b: float
    delta: float  # b - a
    winner: str  # "A", "B", or "tie"


class ComparisonResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    experiment_a_id: str
    experiment_b_id: str
    label_a: str
    label_b: str
    metrics: tuple[MetricComparison, ...] = ()
    a_wins: int = 0
    b_wins: int = 0
    ties: int = 0

    @property
    def overall_winner(self) -> str:
        if self.a_wins > self.b_wins:
            return "A"
        if self.b_wins > self.a_wins:
            return "B"
        return "tie"


def compare(
    experiment_a: Experiment,
    experiment_b: Experiment,
    *,
    label_a: str = "A",
    label_b: str = "B",
) -> ComparisonResult:
    rows: list[MetricComparison] = []
    a_wins = b_wins = ties = 0
    for metric, higher_is_better in _HIGHER_IS_BETTER.items():
        value_a = float(getattr(experiment_a.metrics, metric))
        value_b = float(getattr(experiment_b.metrics, metric))
        if value_a == value_b:
            winner = "tie"
            ties += 1
        else:
            b_better = value_b > value_a if higher_is_better else value_b < value_a
            winner = "B" if b_better else "A"
            if b_better:
                b_wins += 1
            else:
                a_wins += 1
        rows.append(
            MetricComparison(
                metric=metric,
                value_a=round(value_a, 6),
                value_b=round(value_b, 6),
                delta=round(value_b - value_a, 6),
                winner=winner,
            )
        )
    return ComparisonResult(
        experiment_a_id=experiment_a.experiment_id,
        experiment_b_id=experiment_b.experiment_id,
        label_a=label_a,
        label_b=label_b,
        metrics=tuple(rows),
        a_wins=a_wins,
        b_wins=b_wins,
        ties=ties,
    )
