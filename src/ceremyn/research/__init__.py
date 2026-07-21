"""Ceremyn Research Lab.

A platform for discovering profitable strategies by running, persisting, ranking,
and comparing many backtests. It orchestrates the existing backtesting engine — it
does not reimplement strategy, risk, portfolio, or metric logic.

Everything ultimately runs through ``ceremyn.backtest.BacktestRunner``; the Lab
adds experiment identity, reproducibility, persistence, optimization, walk-forward /
cross-validation orchestration, leaderboards, comparison, and multi-experiment reports.
"""

from ceremyn.research.comparison import ComparisonResult, MetricComparison, compare
from ceremyn.research.cross_validation import (
    CrossValidationReport,
    CrossValidator,
    FoldResult,
)
from ceremyn.research.dataset import Dataset, dataset_from_events
from ceremyn.research.experiment import (
    Experiment,
    ExperimentSpec,
    git_commit,
)
from ceremyn.research.experiment_manager import ExperimentManager
from ceremyn.research.experiment_store import ExperimentStore, JSONExperimentStore
from ceremyn.research.leaderboard import Leaderboard, LeaderboardRow, RankMetric
from ceremyn.research.optimizer import OptimizationRun, Optimizer
from ceremyn.research.parameter_grid import ParameterGrid, random_search_samples, sweep
from ceremyn.research.report import ResearchReporter
from ceremyn.research.statistics import (
    ExperimentMetrics,
    composite_score,
    metrics_from_report,
)
from ceremyn.research.walkforward import (
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
