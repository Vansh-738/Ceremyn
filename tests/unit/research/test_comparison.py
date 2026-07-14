from alphaquant.research.comparison import compare
from tests.unit.research.conftest import make_experiment


class TestCompare:
    def test_deltas_and_per_metric_winner(self) -> None:
        a = make_experiment(experiment_id="a", sharpe=1.0, max_drawdown=1000.0)
        b = make_experiment(experiment_id="b", sharpe=2.0, max_drawdown=500.0)
        result = compare(a, b, label_a="A", label_b="B")

        sharpe = next(m for m in result.metrics if m.metric == "sharpe")
        assert sharpe.value_a == 1.0
        assert sharpe.value_b == 2.0
        assert sharpe.delta == 1.0
        assert sharpe.winner == "B"  # higher sharpe wins

        # Lower drawdown is better, so B (500) wins on max_drawdown.
        drawdown = next(m for m in result.metrics if m.metric == "max_drawdown")
        assert drawdown.winner == "B"

    def test_overall_winner_counts_metric_wins(self) -> None:
        a = make_experiment(experiment_id="a", sharpe=0.1, sortino=0.1, cagr=0.1)
        b = make_experiment(experiment_id="b", sharpe=5.0, sortino=5.0, cagr=5.0)
        result = compare(a, b)
        assert result.b_wins > result.a_wins
        assert result.overall_winner == "B"

    def test_identical_experiments_all_ties(self) -> None:
        a = make_experiment(experiment_id="a", sharpe=1.0)
        b = make_experiment(experiment_id="b", sharpe=1.0)
        result = compare(a, b)
        assert result.a_wins == 0
        assert result.b_wins == 0
        assert result.ties == len(result.metrics)
        assert result.overall_winner == "tie"

    def test_lower_probability_of_ruin_wins(self) -> None:
        a = make_experiment(experiment_id="a", probability_of_ruin=0.4)
        b = make_experiment(experiment_id="b", probability_of_ruin=0.1)
        result = compare(a, b)
        por = next(m for m in result.metrics if m.metric == "probability_of_ruin")
        assert por.winner == "B"

    def test_a_can_win_metrics(self) -> None:
        a = make_experiment(experiment_id="a", sharpe=3.0, max_drawdown=100.0)
        b = make_experiment(experiment_id="b", sharpe=1.0, max_drawdown=900.0)
        result = compare(a, b)
        assert result.a_wins >= 2  # a wins both sharpe and (lower) drawdown
        assert result.overall_winner == "A"
        sharpe = next(m for m in result.metrics if m.metric == "sharpe")
        assert sharpe.winner == "A"

    def test_labels_and_ids_preserved(self) -> None:
        a = make_experiment(experiment_id="exp-a")
        b = make_experiment(experiment_id="exp-b")
        result = compare(a, b, label_a="Champion", label_b="Challenger")
        assert result.label_a == "Champion"
        assert result.experiment_a_id == "exp-a"
        assert result.experiment_b_id == "exp-b"
