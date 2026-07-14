"""Cross-validation over the event stream: rolling and expanding windows.

Evaluates a *fixed* strategy configuration across time folds to gauge robustness
(as opposed to the optimizer/walk-forward, which search parameters). Each fold runs
through the existing backtest engine via the ExperimentManager.

- rolling  — fixed-size train window slides forward; test on the following block.
- expanding — train window grows from the start; test on the following block.

The train slice provides preceding market context; the reported metrics are always the
out-of-sample test-block metrics.
"""

from statistics import fmean, pstdev

from pydantic import BaseModel, ConfigDict

from alphaquant.backtest.events import BacktestEvent
from alphaquant.domain import StrategyDefinition
from alphaquant.research.dataset import Dataset, dataset_from_events
from alphaquant.research.experiment import Experiment
from alphaquant.research.experiment_manager import ExperimentManager
from alphaquant.risk import RiskEngine


class FoldResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    fold_index: int
    train_size: int
    test_size: int
    experiment: Experiment


class CrossValidationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    scheme: str  # "rolling" | "expanding"
    score_metric: str
    folds: tuple[FoldResult, ...] = ()
    mean_score: float = 0.0
    std_score: float = 0.0

    @property
    def fold_count(self) -> int:
        return len(self.folds)


class CrossValidator:
    def __init__(self, manager: ExperimentManager) -> None:
        self.manager = manager

    def rolling(
        self,
        *,
        definition: StrategyDefinition,
        dataset: Dataset,
        risk_engine: RiskEngine,
        train_size: int,
        test_size: int,
        score_metric: str = "sharpe",
    ) -> CrossValidationReport:
        return self._run(
            scheme="rolling",
            definition=definition,
            dataset=dataset,
            risk_engine=risk_engine,
            train_size=train_size,
            test_size=test_size,
            score_metric=score_metric,
            expanding=False,
        )

    def expanding(
        self,
        *,
        definition: StrategyDefinition,
        dataset: Dataset,
        risk_engine: RiskEngine,
        train_size: int,
        test_size: int,
        score_metric: str = "sharpe",
    ) -> CrossValidationReport:
        return self._run(
            scheme="expanding",
            definition=definition,
            dataset=dataset,
            risk_engine=risk_engine,
            train_size=train_size,
            test_size=test_size,
            score_metric=score_metric,
            expanding=True,
        )

    def _run(
        self,
        *,
        scheme: str,
        definition: StrategyDefinition,
        dataset: Dataset,
        risk_engine: RiskEngine,
        train_size: int,
        test_size: int,
        score_metric: str,
        expanding: bool,
    ) -> CrossValidationReport:
        if train_size < 1 or test_size < 1:
            raise ValueError("train_size and test_size must both be >= 1")
        events = dataset.ordered_events()
        folds: list[FoldResult] = []
        index = 0
        start = 0
        while start + train_size + test_size <= len(events):
            train_start = 0 if expanding else start
            train_events = events[train_start : start + train_size]
            test_events = events[start + train_size : start + train_size + test_size]
            experiment = self._evaluate_fold(
                definition=definition,
                dataset=dataset,
                train_events=train_events,
                test_events=test_events,
                risk_engine=risk_engine,
                scheme=scheme,
                fold_index=index,
            )
            folds.append(
                FoldResult(
                    fold_index=index,
                    train_size=len(train_events),
                    test_size=len(test_events),
                    experiment=experiment,
                )
            )
            index += 1
            start += test_size

        scores = [float(getattr(fold.experiment.metrics, score_metric)) for fold in folds]
        return CrossValidationReport(
            scheme=scheme,
            score_metric=score_metric,
            folds=tuple(folds),
            mean_score=round(fmean(scores), 6) if scores else 0.0,
            std_score=round(pstdev(scores), 6) if len(scores) > 1 else 0.0,
        )

    def _evaluate_fold(
        self,
        *,
        definition: StrategyDefinition,
        dataset: Dataset,
        train_events: tuple[BacktestEvent, ...],
        test_events: tuple[BacktestEvent, ...],
        risk_engine: RiskEngine,
        scheme: str,
        fold_index: int,
    ) -> Experiment:
        # The test block is what we score; train events precede it as market context.
        fold_events = train_events + test_events if scheme == "expanding" else test_events
        fold_ds = dataset_from_events(
            f"{dataset.name}#cv-{scheme}-{fold_index}",
            fold_events,
            feature_version=dataset.feature_version,
        )
        spec = self.manager.build_spec(definition=definition, dataset=fold_ds)
        return self.manager.run(spec, fold_ds, risk_engine, run_monte_carlo=False)
