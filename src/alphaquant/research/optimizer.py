"""Parameter optimization: grid search, random search, and parameter sweep.

Each candidate parameter combination becomes one persisted experiment via the
``ExperimentManager`` (which drives the existing backtest engine). The optimizer only
expands the search space and ranks the results — it reruns no backtest logic itself.
"""

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict

from alphaquant.domain import StrategyDefinition
from alphaquant.research.dataset import Dataset
from alphaquant.research.experiment import Experiment
from alphaquant.research.experiment_manager import ExperimentManager
from alphaquant.research.parameter_grid import (
    ParameterGrid,
    random_search_samples,
    sweep,
)
from alphaquant.risk import RiskEngine


class OptimizationRun(BaseModel):
    """The full set of experiments from one optimization, plus the best."""

    model_config = ConfigDict(frozen=True)

    score_metric: str
    experiments: tuple[Experiment, ...] = ()
    best_experiment_id: str | None = None

    @property
    def best(self) -> Experiment | None:
        if self.best_experiment_id is None:
            return None
        return next(
            (exp for exp in self.experiments if exp.experiment_id == self.best_experiment_id),
            None,
        )


class Optimizer:
    def __init__(self, manager: ExperimentManager) -> None:
        self.manager = manager

    def grid_search(
        self,
        *,
        definition: StrategyDefinition,
        dataset: Dataset,
        risk_engine: RiskEngine,
        grid: ParameterGrid,
        score_metric: str = "sharpe",
        run_monte_carlo: bool = False,
    ) -> OptimizationRun:
        return self._run_combinations(
            definition=definition,
            dataset=dataset,
            risk_engine=risk_engine,
            combinations=list(grid.combinations()),
            score_metric=score_metric,
            run_monte_carlo=run_monte_carlo,
        )

    def random_search(
        self,
        *,
        definition: StrategyDefinition,
        dataset: Dataset,
        risk_engine: RiskEngine,
        space: dict[str, Sequence[Any]],
        n: int,
        seed: int = 7,
        score_metric: str = "sharpe",
        run_monte_carlo: bool = False,
    ) -> OptimizationRun:
        return self._run_combinations(
            definition=definition,
            dataset=dataset,
            risk_engine=risk_engine,
            combinations=random_search_samples(space, n=n, seed=seed),
            score_metric=score_metric,
            run_monte_carlo=run_monte_carlo,
        )

    def sweep(
        self,
        *,
        definition: StrategyDefinition,
        dataset: Dataset,
        risk_engine: RiskEngine,
        parameter: str,
        values: Sequence[Any],
        score_metric: str = "sharpe",
        run_monte_carlo: bool = False,
    ) -> OptimizationRun:
        return self._run_combinations(
            definition=definition,
            dataset=dataset,
            risk_engine=risk_engine,
            combinations=sweep(parameter, values),
            score_metric=score_metric,
            run_monte_carlo=run_monte_carlo,
        )

    def _run_combinations(
        self,
        *,
        definition: StrategyDefinition,
        dataset: Dataset,
        risk_engine: RiskEngine,
        combinations: list[dict[str, Any]],
        score_metric: str,
        run_monte_carlo: bool,
    ) -> OptimizationRun:
        experiments: list[Experiment] = []
        for parameters in combinations:
            spec = self.manager.build_spec(
                definition=definition,
                dataset=dataset,
                parameters=parameters,
            )
            experiments.append(
                self.manager.run(
                    spec,
                    dataset,
                    risk_engine,
                    run_monte_carlo=run_monte_carlo,
                )
            )
        best = _best_by_metric(experiments, score_metric)
        return OptimizationRun(
            score_metric=score_metric,
            experiments=tuple(experiments),
            best_experiment_id=best.experiment_id if best else None,
        )


def _best_by_metric(experiments: Sequence[Experiment], metric: str) -> Experiment | None:
    if not experiments:
        return None
    return max(experiments, key=lambda exp: float(getattr(exp.metrics, metric)))
