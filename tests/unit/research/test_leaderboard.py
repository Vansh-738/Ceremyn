from alphaquant.research.leaderboard import Leaderboard, RankMetric
from tests.unit.research.conftest import make_experiment


def experiments() -> list:
    return [
        make_experiment(
            experiment_id="low",
            sharpe=0.5,
            sortino=0.4,
            profit_factor=1.0,
            cagr=2.0,
            max_drawdown=500.0,
            total_return=5.0,
        ),
        make_experiment(
            experiment_id="high",
            sharpe=2.5,
            sortino=3.0,
            profit_factor=2.2,
            cagr=15.0,
            max_drawdown=1200.0,
            total_return=25.0,
        ),
        make_experiment(
            experiment_id="mid",
            sharpe=1.5,
            sortino=1.2,
            profit_factor=1.6,
            cagr=9.0,
            max_drawdown=200.0,
            total_return=12.0,
        ),
    ]


class TestRanking:
    def test_rank_by_sharpe_descending(self) -> None:
        rows = Leaderboard().rank(experiments(), by=RankMetric.SHARPE)
        assert [r.experiment_id for r in rows] == ["high", "mid", "low"]
        assert rows[0].rank == 1 and rows[-1].rank == 3

    def test_rank_by_drawdown_ascending(self) -> None:
        # Lower drawdown is better -> "mid" (200) ranks first.
        rows = Leaderboard().rank(experiments(), by=RankMetric.DRAWDOWN)
        assert [r.experiment_id for r in rows] == ["mid", "low", "high"]

    def test_rank_by_profit_factor(self) -> None:
        rows = Leaderboard().rank(experiments(), by=RankMetric.PROFIT_FACTOR)
        assert rows[0].experiment_id == "high"

    def test_rank_by_cagr(self) -> None:
        rows = Leaderboard().rank(experiments(), by=RankMetric.CAGR)
        assert rows[0].experiment_id == "high"

    def test_rank_by_sortino(self) -> None:
        rows = Leaderboard().rank(experiments(), by=RankMetric.SORTINO)
        assert rows[0].experiment_id == "high"

    def test_rank_by_composite(self) -> None:
        rows = Leaderboard().rank(experiments(), by=RankMetric.COMPOSITE)
        assert rows[0].experiment_id == "high"
        # Score should be populated and monotonically non-increasing.
        scores = [r.score for r in rows]
        assert scores == sorted(scores, reverse=True)

    def test_top_limits_results(self) -> None:
        rows = Leaderboard().top(experiments(), by=RankMetric.SHARPE, limit=2)
        assert len(rows) == 2
        assert [r.experiment_id for r in rows] == ["high", "mid"]

    def test_row_carries_metric_snapshot(self) -> None:
        row = Leaderboard().rank(experiments(), by=RankMetric.SHARPE)[0]
        assert row.strategy_name == "Strategy"
        assert row.sharpe == 2.5
        assert row.total_return == 25.0

    def test_empty_input(self) -> None:
        assert Leaderboard().rank([]) == ()
