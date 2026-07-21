import pytest

from ceremyn.domain import StrategyDefinition
from ceremyn.research.dataset import Dataset
from ceremyn.research.experiment_manager import ExperimentManager
from ceremyn.research.parameter_grid import ParameterGrid
from ceremyn.research.walkforward import WalkForwardLab, WalkForwardReport
from ceremyn.risk import RiskEngine


def run_wf(
    manager: ExperimentManager,
    definition: StrategyDefinition,
    dataset: Dataset,
    risk_engine: RiskEngine,
    **kwargs: object,
) -> WalkForwardReport:
    defaults: dict[str, object] = {
        "train_size": 3,
        "validate_size": 2,
        "test_size": 2,
        "score_metric": "total_return",
    }
    defaults.update(kwargs)
    return WalkForwardLab(manager).run(
        definition=definition,
        dataset=dataset,
        risk_engine=risk_engine,
        grid=ParameterGrid(space={"lots": (1, 2)}),
        **defaults,  # type: ignore[arg-type]
    )


class TestWalkForward:
    def test_produces_windows_with_all_phases(
        self,
        manager: ExperimentManager,
        definition: StrategyDefinition,
        dataset: Dataset,
        risk_engine: RiskEngine,
    ) -> None:
        report = run_wf(manager, definition, dataset, risk_engine)
        assert len(report.windows) >= 1
        for window in report.windows:
            assert window.train is not None
            assert window.validation is not None
            assert window.test is not None
            assert "lots" in window.selected_parameters

    def test_aggregate_scores_present(
        self,
        manager: ExperimentManager,
        definition: StrategyDefinition,
        dataset: Dataset,
        risk_engine: RiskEngine,
    ) -> None:
        report = run_wf(manager, definition, dataset, risk_engine)
        assert isinstance(report.mean_test_score, float)
        assert isinstance(report.mean_validation_score, float)
        assert isinstance(report.is_robust, bool)

    def test_selected_params_come_from_grid(
        self,
        manager: ExperimentManager,
        definition: StrategyDefinition,
        dataset: Dataset,
        risk_engine: RiskEngine,
    ) -> None:
        report = run_wf(manager, definition, dataset, risk_engine)
        for window in report.windows:
            assert window.selected_parameters["lots"] in (1, 2)

    def test_rejects_non_positive_sizes(
        self,
        manager: ExperimentManager,
        definition: StrategyDefinition,
        dataset: Dataset,
        risk_engine: RiskEngine,
    ) -> None:
        with pytest.raises(ValueError, match=">= 1"):
            run_wf(manager, definition, dataset, risk_engine, validate_size=0)

    def test_rejects_empty_grid(
        self,
        manager: ExperimentManager,
        definition: StrategyDefinition,
        dataset: Dataset,
        risk_engine: RiskEngine,
    ) -> None:
        with pytest.raises(ValueError, match="empty"):
            WalkForwardLab(manager).run(
                definition=definition,
                dataset=dataset,
                risk_engine=risk_engine,
                grid=ParameterGrid(space={}),
                train_size=3,
                validate_size=2,
                test_size=2,
            )


class TestRobustness:
    def test_is_robust_flag_logic(self) -> None:
        robust = WalkForwardReport(
            score_metric="sharpe", mean_validation_score=2.0, mean_test_score=1.5
        )
        assert robust.is_robust is True
        fragile = WalkForwardReport(
            score_metric="sharpe", mean_validation_score=2.0, mean_test_score=0.5
        )
        assert fragile.is_robust is False
        no_val_positive = WalkForwardReport(
            score_metric="sharpe", mean_validation_score=0.0, mean_test_score=0.1
        )
        assert no_val_positive.is_robust is True
