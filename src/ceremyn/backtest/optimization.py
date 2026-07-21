"""Parameter optimization helpers."""

from collections.abc import Iterable
from itertools import product
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ceremyn.backtest.engine import BacktestConfig
from ceremyn.backtest.events import BacktestEvent
from ceremyn.backtest.report import BacktestReport
from ceremyn.backtest.runner import BacktestRunner
from ceremyn.domain import StrategyDefinition
from ceremyn.risk import RiskEngine
from ceremyn.strategies import create


class OptimizationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    best_params: dict[str, Any] = Field(default_factory=dict)
    best_score: float = 0.0
    reports: tuple[BacktestReport, ...] = ()


class GridSearchOptimizer:
    def run(
        self,
        *,
        definition: StrategyDefinition,
        parameter_grid: dict[str, tuple[Any, ...]],
        events: Iterable[BacktestEvent],
        risk_engine: RiskEngine,
        config: BacktestConfig | None = None,
        score_key: str = "total_return",
    ) -> OptimizationResult:
        keys = tuple(parameter_grid)
        reports: list[BacktestReport] = []
        best_params: dict[str, Any] = {}
        best_score = float("-inf")
        event_list = tuple(events)

        for values in product(*(parameter_grid[key] for key in keys)):
            params = dict(zip(keys, values, strict=True))
            candidate = definition.model_copy(update={"params": {**definition.params, **params}})
            report = BacktestRunner(
                strategy=create(candidate),
                definition=candidate,
                risk_engine=risk_engine,
                config=config,
            ).run(event_list)
            reports.append(report)
            score = float(getattr(report.statistics, score_key))
            if score > best_score:
                best_score = score
                best_params = params

        return OptimizationResult(
            best_params=best_params,
            best_score=best_score if best_score != float("-inf") else 0.0,
            reports=tuple(reports),
        )
