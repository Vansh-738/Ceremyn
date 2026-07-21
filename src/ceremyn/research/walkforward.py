"""Walk-forward analysis: optimize in-sample, select on validation, test out-of-sample.

Reuses the backtest engine's window splitter (``WalkForwardAnalyzer.split``) for the
train/validate/test partitioning, then adds the research-grade selection loop the
backtest layer intentionally leaves out: for each window it optimizes parameters on the
train slice, picks the combination that scores best on validation, and evaluates that
single combination out-of-sample on test.
"""

from statistics import fmean

from pydantic import BaseModel, ConfigDict, Field

from ceremyn.backtest.walkforward import WalkForwardAnalyzer
from ceremyn.domain import StrategyDefinition
from ceremyn.research.dataset import Dataset, dataset_from_events
from ceremyn.research.experiment import Experiment
from ceremyn.research.experiment_manager import ExperimentManager
from ceremyn.research.parameter_grid import ParameterGrid
from ceremyn.risk import RiskEngine


class WalkForwardWindowReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    window_index: int
    selected_parameters: dict[str, object] = Field(default_factory=dict)
    train: Experiment
    validation: Experiment
    test: Experiment


class WalkForwardReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    score_metric: str
    windows: tuple[WalkForwardWindowReport, ...] = ()
    mean_test_score: float = 0.0
    mean_validation_score: float = 0.0

    @property
    def is_robust(self) -> bool:
        """A crude robustness flag: out-of-sample score kept at least half of validation."""
        if self.mean_validation_score <= 0:
            return self.mean_test_score > 0
        return self.mean_test_score >= 0.5 * self.mean_validation_score


class WalkForwardLab:
    def __init__(self, manager: ExperimentManager) -> None:
        self.manager = manager
        self._splitter = WalkForwardAnalyzer()

    def run(
        self,
        *,
        definition: StrategyDefinition,
        dataset: Dataset,
        risk_engine: RiskEngine,
        grid: ParameterGrid,
        train_size: int,
        validate_size: int,
        test_size: int,
        score_metric: str = "sharpe",
    ) -> WalkForwardReport:
        if min(train_size, validate_size, test_size) < 1:
            raise ValueError("train_size, validate_size and test_size must all be >= 1")

        windows = self._splitter.split(
            dataset.ordered_events(),
            train_size=train_size,
            validate_size=validate_size,
            test_size=test_size,
        )
        combinations = list(grid.combinations())
        if not combinations:
            raise ValueError("parameter grid is empty")

        window_reports: list[WalkForwardWindowReport] = []
        for index, window in enumerate(windows):
            train_ds = dataset_from_events(
                f"{dataset.name}#wf{index}-train",
                window.train,
                feature_version=dataset.feature_version,
            )
            validation_ds = dataset_from_events(
                f"{dataset.name}#wf{index}-val",
                window.validation,
                feature_version=dataset.feature_version,
            )
            test_ds = dataset_from_events(
                f"{dataset.name}#wf{index}-test",
                window.test,
                feature_version=dataset.feature_version,
            )

            best_params, train_exp, validation_exp = self._select_on_validation(
                definition=definition,
                train_ds=train_ds,
                validation_ds=validation_ds,
                risk_engine=risk_engine,
                combinations=combinations,
                score_metric=score_metric,
            )
            test_exp = self.manager.run(
                self.manager.build_spec(
                    definition=definition, dataset=test_ds, parameters=best_params
                ),
                test_ds,
                risk_engine,
                run_monte_carlo=False,
            )
            window_reports.append(
                WalkForwardWindowReport(
                    window_index=index,
                    selected_parameters=best_params,
                    train=train_exp,
                    validation=validation_exp,
                    test=test_exp,
                )
            )

        return WalkForwardReport(
            score_metric=score_metric,
            windows=tuple(window_reports),
            mean_test_score=_mean_score(window_reports, "test", score_metric),
            mean_validation_score=_mean_score(window_reports, "validation", score_metric),
        )

    def _select_on_validation(
        self,
        *,
        definition: StrategyDefinition,
        train_ds: Dataset,
        validation_ds: Dataset,
        risk_engine: RiskEngine,
        combinations: list[dict[str, object]],
        score_metric: str,
    ) -> tuple[dict[str, object], Experiment, Experiment]:
        best: tuple[float, dict[str, object], Experiment, Experiment] | None = None
        for parameters in combinations:
            train_exp = self.manager.run(
                self.manager.build_spec(
                    definition=definition, dataset=train_ds, parameters=parameters
                ),
                train_ds,
                risk_engine,
                run_monte_carlo=False,
            )
            validation_exp = self.manager.run(
                self.manager.build_spec(
                    definition=definition, dataset=validation_ds, parameters=parameters
                ),
                validation_ds,
                risk_engine,
                run_monte_carlo=False,
            )
            score = float(getattr(validation_exp.metrics, score_metric))
            if best is None or score > best[0]:
                best = (score, parameters, train_exp, validation_exp)
        assert best is not None  # combinations is non-empty (checked by caller)
        return best[1], best[2], best[3]


def _mean_score(
    windows: list[WalkForwardWindowReport],
    phase: str,
    metric: str,
) -> float:
    if not windows:
        return 0.0
    scores = [float(getattr(getattr(window, phase).metrics, metric)) for window in windows]
    return round(fmean(scores), 6)
