"""ExperimentManager: run a spec through the backtest engine, then persist it.

This is the central integration point. It builds a StrategyDefinition from the spec,
runs the existing ``BacktestRunner`` over the dataset's events, maps the resulting
``BacktestReport`` to ``ExperimentMetrics`` (optionally running Monte Carlo for
probability-of-ruin), and stores an immutable ``Experiment``.

Identical specs (same ``spec_hash``) are deduplicated: rerunning returns the stored
experiment unless ``force=True``.
"""

import time

import structlog

from alphaquant.backtest.engine import BacktestConfig
from alphaquant.backtest.montecarlo import MonteCarloSimulator
from alphaquant.backtest.report import BacktestReport
from alphaquant.backtest.runner import BacktestRunner
from alphaquant.domain import StrategyDefinition
from alphaquant.research.dataset import Dataset
from alphaquant.research.experiment import Experiment, ExperimentSpec, git_commit
from alphaquant.research.experiment_store import ExperimentStore
from alphaquant.research.statistics import ExperimentMetrics, metrics_from_report
from alphaquant.risk import RiskEngine
from alphaquant.strategies import create

logger = structlog.get_logger(__name__)


class ExperimentManager:
    def __init__(
        self,
        store: ExperimentStore,
        *,
        monte_carlo_iterations: int = 500,
        monte_carlo_seed: int = 7,
    ) -> None:
        self.store = store
        self._mc_iterations = monte_carlo_iterations
        self._mc_seed = monte_carlo_seed

    def build_spec(
        self,
        *,
        definition: StrategyDefinition,
        dataset: Dataset,
        parameters: dict[str, object] | None = None,
        notes: str = "",
    ) -> ExperimentSpec:
        """Compose a spec from a base definition + parameter overrides + dataset."""
        merged = {**definition.params, **(parameters or {})}
        return ExperimentSpec(
            strategy_type=definition.strategy_type,
            strategy_name=definition.name,
            strategy_version=definition.version,
            underlyings=definition.underlyings,
            parameters=merged,
            dataset_name=dataset.name,
            market_data_version=dataset.market_data_version,
            feature_version=dataset.feature_version,
            backtest_config=BacktestConfig(),
            notes=notes,
        )

    def run(
        self,
        spec: ExperimentSpec,
        dataset: Dataset,
        risk_engine: RiskEngine,
        *,
        force: bool = False,
        run_monte_carlo: bool = True,
    ) -> Experiment:
        """Run (or return the deduped result of) an experiment and persist it."""
        if not force:
            existing = self.store.find_by_spec_hash(spec.spec_hash)
            if existing is not None:
                logger.info(
                    "experiment_dedup_hit",
                    spec_hash=spec.spec_hash,
                    experiment_id=existing.experiment_id,
                )
                return existing

        definition = StrategyDefinition(
            id=_definition_id(spec),
            strategy_type=spec.strategy_type,
            name=spec.strategy_name,
            version=spec.strategy_version,
            underlyings=spec.underlyings,
            params=spec.parameters,
        )

        started = time.perf_counter()
        report = BacktestRunner(
            strategy=create(definition),
            definition=definition,
            risk_engine=risk_engine,
            config=spec.backtest_config,
        ).run(dataset.ordered_events())
        elapsed = time.perf_counter() - started

        metrics = self._metrics(report, run_monte_carlo=run_monte_carlo)
        experiment = Experiment.from_spec(
            spec,
            metrics=metrics,
            execution_time_seconds=round(elapsed, 6),
            commit=git_commit(),
        )
        self.store.save(experiment)
        logger.info(
            "experiment_completed",
            experiment_id=experiment.experiment_id,
            strategy=spec.strategy_name,
            sharpe=metrics.sharpe,
            total_return=metrics.total_return,
        )
        return experiment

    def _metrics(self, report: BacktestReport, *, run_monte_carlo: bool) -> ExperimentMetrics:
        montecarlo = None
        if run_monte_carlo and len(report.equity_curve) >= 2:
            montecarlo = MonteCarloSimulator().run(
                equity_curve=report.equity_curve,
                iterations=self._mc_iterations,
                seed=self._mc_seed,
            )
        return metrics_from_report(report, montecarlo=montecarlo)


def _definition_id(spec: ExperimentSpec) -> str:
    """A registry-safe definition id (lowercase, ``[a-z0-9_-]``) from the spec hash."""
    return f"{spec.strategy_type}-{spec.spec_hash[:12]}"
