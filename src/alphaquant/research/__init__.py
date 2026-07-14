"""AlphaQuant Research Lab.

A platform for discovering profitable strategies by running, persisting, ranking,
and comparing many backtests. It orchestrates the existing backtesting engine — it
does not reimplement strategy, risk, portfolio, or metric logic.

Everything ultimately runs through ``alphaquant.backtest.BacktestRunner``; the Lab
adds experiment identity, reproducibility, persistence, optimization, walk-forward /
cross-validation orchestration, leaderboards, comparison, and multi-experiment reports.
"""

from alphaquant.research.comparison import ComparisonResult, MetricComparison, compare
from alphaquant.research.cross_validation import (
    CrossValidationReport,
    CrossValidator,
    FoldResult,
)
from alphaquant.research.dataset import Dataset, dataset_from_events
from alphaquant.research.experiment import (
    Experiment,
    ExperimentSpec,
    git_commit,
)
from alphaquant.research.experiment_manager import ExperimentManager
from alphaquant.research.experiment_store import ExperimentStore, JSONExperimentStore
from alphaquant.research.leaderboard import Leaderboard, LeaderboardRow, RankMetric
from alphaquant.research.optimizer import OptimizationRun, Optimizer
from alphaquant.research.parameter_grid import ParameterGrid, random_search_samples, sweep
from alphaquant.research.report import ResearchReporter
from alphaquant.research.statistics import (
    ExperimentMetrics,
    composite_score,
    metrics_from_report,
)
from alphaquant.research.walkforward import (
    WalkForwardLab,
    WalkForwardReport,
    WalkForwardWindowReport,
)

__all__ = [
    "ComparisonResult",
    "CrossValidationReport",
    "CrossValidator",
    "Dataset",
    "Experiment",
    "ExperimentManager",
    "ExperimentMetrics",
    "ExperimentSpec",
    "ExperimentStore",
    "FoldResult",
    "JSONExperimentStore",
    "Leaderboard",
    "LeaderboardRow",
    "MetricComparison",
    "OptimizationRun",
    "Optimizer",
    "ParameterGrid",
    "RankMetric",
    "ResearchReporter",
    "WalkForwardLab",
    "WalkForwardReport",
    "WalkForwardWindowReport",
    "compare",
    "composite_score",
    "dataset_from_events",
    "git_commit",
    "metrics_from_report",
    "random_search_samples",
    "sweep",
]
