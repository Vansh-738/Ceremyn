"""Leaderboard: rank experiments by a chosen metric or a composite score."""

from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from ceremyn.research.experiment import Experiment
from ceremyn.research.statistics import composite_score


class RankMetric(StrEnum):
    SHARPE = "sharpe"
    PROFIT_FACTOR = "profit_factor"
    SORTINO = "sortino"
    CAGR = "cagr"
    DRAWDOWN = "drawdown"  # lower is better -> ascending
    COMPOSITE = "composite"


# Drawdown ranks ascending (smaller is better); everything else descending.
_ASCENDING = {RankMetric.DRAWDOWN}


class LeaderboardRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    rank: int
    experiment_id: str
    strategy_name: str
    score: float
    sharpe: float
    sortino: float
    profit_factor: float
    cagr: float
    max_drawdown: float
    total_return: float
    trade_count: int


class Leaderboard:
    def rank(
        self,
        experiments: Sequence[Experiment],
        *,
        by: RankMetric = RankMetric.SHARPE,
        composite_weights: dict[str, float] | None = None,
    ) -> tuple[LeaderboardRow, ...]:
        scored = [(self._score(exp, by, composite_weights), exp) for exp in experiments]
        scored.sort(key=lambda pair: pair[0], reverse=by not in _ASCENDING)
        return tuple(
            LeaderboardRow(
                rank=position,
                experiment_id=exp.experiment_id,
                strategy_name=exp.strategy_name,
                score=round(score, 6),
                sharpe=exp.metrics.sharpe,
                sortino=exp.metrics.sortino,
                profit_factor=exp.metrics.profit_factor,
                cagr=exp.metrics.cagr,
                max_drawdown=exp.metrics.max_drawdown,
                total_return=exp.metrics.total_return,
                trade_count=exp.metrics.trade_count,
            )
            for position, (score, exp) in enumerate(scored, start=1)
        )

    def top(
        self,
        experiments: Sequence[Experiment],
        *,
        by: RankMetric = RankMetric.SHARPE,
        limit: int = 10,
        composite_weights: dict[str, float] | None = None,
    ) -> tuple[LeaderboardRow, ...]:
        return self.rank(experiments, by=by, composite_weights=composite_weights)[:limit]

    @staticmethod
    def _score(
        experiment: Experiment,
        by: RankMetric,
        composite_weights: dict[str, float] | None,
    ) -> float:
        if by is RankMetric.COMPOSITE:
            return composite_score(experiment.metrics, weights=composite_weights)
        if by is RankMetric.DRAWDOWN:
            return experiment.metrics.max_drawdown
        return float(getattr(experiment.metrics, by.value))
