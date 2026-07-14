from alphaquant.domain import StrategyDefinition
from alphaquant.research.dataset import Dataset
from alphaquant.research.experiment_manager import ExperimentManager
from alphaquant.research.optimizer import Optimizer
from alphaquant.research.parameter_grid import ParameterGrid
from alphaquant.risk import RiskEngine


class TestGridSearch:
    def test_runs_all_combinations_and_picks_best(
        self,
        manager: ExperimentManager,
        definition: StrategyDefinition,
        dataset: Dataset,
        risk_engine: RiskEngine,
    ) -> None:
        optimizer = Optimizer(manager)
        grid = ParameterGrid(space={"lots": (1, 2, 3)})
        run = optimizer.grid_search(
            definition=definition,
            dataset=dataset,
            risk_engine=risk_engine,
            grid=grid,
            score_metric="total_return",
        )
        assert len(run.experiments) == 3
        assert run.best is not None
        best_return = max(e.metrics.total_return for e in run.experiments)
        assert run.best.metrics.total_return == best_return

    def test_best_property_resolves_experiment(
        self,
        manager: ExperimentManager,
        definition: StrategyDefinition,
        dataset: Dataset,
        risk_engine: RiskEngine,
    ) -> None:
        run = Optimizer(manager).grid_search(
            definition=definition,
            dataset=dataset,
            risk_engine=risk_engine,
            grid=ParameterGrid(space={"lots": (1, 2)}),
        )
        assert run.best is not None
        assert run.best.experiment_id == run.best_experiment_id


class TestRandomSearch:
    def test_runs_sampled_combinations(
        self,
        manager: ExperimentManager,
        definition: StrategyDefinition,
        dataset: Dataset,
        risk_engine: RiskEngine,
    ) -> None:
        run = Optimizer(manager).random_search(
            definition=definition,
            dataset=dataset,
            risk_engine=risk_engine,
            space={"lots": [1, 2, 3, 4]},
            n=2,
            seed=3,
            score_metric="total_return",
        )
        assert len(run.experiments) == 2
        assert run.best is not None


class TestSweep:
    def test_sweeps_single_parameter(
        self,
        manager: ExperimentManager,
        definition: StrategyDefinition,
        dataset: Dataset,
        risk_engine: RiskEngine,
    ) -> None:
        run = Optimizer(manager).sweep(
            definition=definition,
            dataset=dataset,
            risk_engine=risk_engine,
            parameter="lots",
            values=[1, 2, 3, 4],
            score_metric="total_return",
        )
        assert len(run.experiments) == 4


def test_empty_run_has_no_best() -> None:
    from alphaquant.research.optimizer import OptimizationRun

    empty = OptimizationRun(score_metric="sharpe")
    assert empty.best is None
