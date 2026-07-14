import pytest

from alphaquant.domain import StrategyDefinition
from alphaquant.research.cross_validation import CrossValidator
from alphaquant.research.dataset import Dataset
from alphaquant.research.experiment_manager import ExperimentManager
from alphaquant.risk import RiskEngine


class TestRolling:
    def test_produces_folds(
        self,
        manager: ExperimentManager,
        definition: StrategyDefinition,
        dataset: Dataset,
        risk_engine: RiskEngine,
    ) -> None:
        report = CrossValidator(manager).rolling(
            definition=definition,
            dataset=dataset,
            risk_engine=risk_engine,
            train_size=2,
            test_size=2,
            score_metric="total_return",
        )
        assert report.scheme == "rolling"
        assert report.fold_count == 3  # 8 events, train2+test2, step=2
        assert all(f.test_size == 2 for f in report.folds)
        assert isinstance(report.mean_score, float)
        assert isinstance(report.std_score, float)

    def test_fold_indices_sequential(
        self,
        manager: ExperimentManager,
        definition: StrategyDefinition,
        dataset: Dataset,
        risk_engine: RiskEngine,
    ) -> None:
        report = CrossValidator(manager).rolling(
            definition=definition,
            dataset=dataset,
            risk_engine=risk_engine,
            train_size=2,
            test_size=2,
        )
        assert [f.fold_index for f in report.folds] == list(range(report.fold_count))


class TestExpanding:
    def test_train_window_grows(
        self,
        manager: ExperimentManager,
        definition: StrategyDefinition,
        dataset: Dataset,
        risk_engine: RiskEngine,
    ) -> None:
        report = CrossValidator(manager).expanding(
            definition=definition,
            dataset=dataset,
            risk_engine=risk_engine,
            train_size=2,
            test_size=2,
            score_metric="total_return",
        )
        assert report.scheme == "expanding"
        assert report.fold_count == 3
        # Expanding: each fold's train window starts at 0 and grows.
        sizes = [f.train_size for f in report.folds]
        assert sizes == sorted(sizes)
        assert sizes[0] < sizes[-1]


class TestValidation:
    def test_rejects_non_positive_sizes(
        self,
        manager: ExperimentManager,
        definition: StrategyDefinition,
        dataset: Dataset,
        risk_engine: RiskEngine,
    ) -> None:
        with pytest.raises(ValueError, match=">= 1"):
            CrossValidator(manager).rolling(
                definition=definition,
                dataset=dataset,
                risk_engine=risk_engine,
                train_size=0,
                test_size=2,
            )

    def test_std_zero_for_single_fold(
        self,
        manager: ExperimentManager,
        definition: StrategyDefinition,
        dataset: Dataset,
        risk_engine: RiskEngine,
    ) -> None:
        # train6 + test2 = 8 -> exactly one fold.
        report = CrossValidator(manager).rolling(
            definition=definition,
            dataset=dataset,
            risk_engine=risk_engine,
            train_size=6,
            test_size=2,
        )
        assert report.fold_count == 1
        assert report.std_score == 0.0
