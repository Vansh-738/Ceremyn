from alphaquant.domain import StrategyDefinition
from alphaquant.research.dataset import Dataset
from alphaquant.research.experiment_manager import ExperimentManager
from alphaquant.research.experiment_store import InMemoryExperimentStore
from alphaquant.risk import RiskEngine


class TestBuildSpec:
    def test_merges_parameter_overrides(
        self, manager: ExperimentManager, definition: StrategyDefinition, dataset: Dataset
    ) -> None:
        spec = manager.build_spec(definition=definition, dataset=dataset, parameters={"lots": 5})
        assert spec.parameters["lots"] == 5
        assert spec.strategy_type == definition.strategy_type
        assert spec.market_data_version == dataset.market_data_version

    def test_carries_notes(
        self, manager: ExperimentManager, definition: StrategyDefinition, dataset: Dataset
    ) -> None:
        spec = manager.build_spec(definition=definition, dataset=dataset, notes="hello")
        assert spec.notes == "hello"


class TestRun:
    def test_runs_and_persists(
        self,
        manager: ExperimentManager,
        store: InMemoryExperimentStore,
        definition: StrategyDefinition,
        dataset: Dataset,
        risk_engine: RiskEngine,
    ) -> None:
        spec = manager.build_spec(definition=definition, dataset=dataset, parameters={"lots": 2})
        exp = manager.run(spec, dataset, risk_engine)
        assert exp.metrics.trade_count > 0
        assert exp.execution_time_seconds >= 0.0
        assert store.get(exp.experiment_id) is not None
        assert exp.git_commit  # captured (sha or "unknown")

    def test_identical_spec_is_deduped(
        self,
        manager: ExperimentManager,
        store: InMemoryExperimentStore,
        definition: StrategyDefinition,
        dataset: Dataset,
        risk_engine: RiskEngine,
    ) -> None:
        spec = manager.build_spec(definition=definition, dataset=dataset, parameters={"lots": 1})
        first = manager.run(spec, dataset, risk_engine)
        second = manager.run(spec, dataset, risk_engine)
        assert first.experiment_id == second.experiment_id
        assert len(store.list_all()) == 1

    def test_force_reruns_even_if_present(
        self,
        manager: ExperimentManager,
        store: InMemoryExperimentStore,
        definition: StrategyDefinition,
        dataset: Dataset,
        risk_engine: RiskEngine,
    ) -> None:
        spec = manager.build_spec(definition=definition, dataset=dataset, parameters={"lots": 1})
        first = manager.run(spec, dataset, risk_engine)
        second = manager.run(spec, dataset, risk_engine, force=True)
        assert first.experiment_id != second.experiment_id
        assert len(store.list_all()) == 2

    def test_different_params_distinct_experiments(
        self,
        manager: ExperimentManager,
        definition: StrategyDefinition,
        dataset: Dataset,
        risk_engine: RiskEngine,
    ) -> None:
        a = manager.run(
            manager.build_spec(definition=definition, dataset=dataset, parameters={"lots": 1}),
            dataset,
            risk_engine,
        )
        b = manager.run(
            manager.build_spec(definition=definition, dataset=dataset, parameters={"lots": 3}),
            dataset,
            risk_engine,
        )
        assert a.experiment_id != b.experiment_id
        assert a.metrics.total_return != b.metrics.total_return

    def test_monte_carlo_can_be_disabled(
        self,
        manager: ExperimentManager,
        definition: StrategyDefinition,
        dataset: Dataset,
        risk_engine: RiskEngine,
    ) -> None:
        spec = manager.build_spec(definition=definition, dataset=dataset, parameters={"lots": 1})
        exp = manager.run(spec, dataset, risk_engine, run_monte_carlo=False)
        assert exp.metrics.probability_of_ruin == 0.0

    def test_monte_carlo_runs_when_enabled(
        self,
        definition: StrategyDefinition,
        dataset: Dataset,
        risk_engine: RiskEngine,
    ) -> None:
        # A separate manager with a real (tiny) Monte Carlo pass.
        manager = ExperimentManager(InMemoryExperimentStore(), monte_carlo_iterations=50)
        spec = manager.build_spec(definition=definition, dataset=dataset, parameters={"lots": 1})
        exp = manager.run(spec, dataset, risk_engine, run_monte_carlo=True)
        assert 0.0 <= exp.metrics.probability_of_ruin <= 1.0
