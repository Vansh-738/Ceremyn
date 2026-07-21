import json

from ceremyn.research.comparison import compare
from ceremyn.research.cross_validation import CrossValidationReport, FoldResult
from ceremyn.research.leaderboard import Leaderboard, RankMetric
from ceremyn.research.report import ResearchReporter
from ceremyn.research.walkforward import (
    WalkForwardReport,
    WalkForwardWindowReport,
)
from tests.unit.research.conftest import make_experiment

REPORTER = ResearchReporter()


class TestExperimentReport:
    def test_markdown_contains_all_metrics(self) -> None:
        exp = make_experiment(experiment_id="e1", sharpe=1.75, total_return=12.0)
        md = REPORTER.experiment_markdown(exp)
        assert "# Experiment e1" in md
        assert "Sharpe" in md and "1.7500" in md
        assert "Probability of Ruin" in md
        assert "Largest Drawdown" in md

    def test_markdown_includes_notes_when_present(self) -> None:
        exp = make_experiment(experiment_id="e1").model_copy(update={"notes": "hi there"})
        assert "hi there" in REPORTER.experiment_markdown(exp)

    def test_json_is_valid_and_roundtrips(self) -> None:
        exp = make_experiment(experiment_id="e1", sharpe=2.0)
        payload = json.loads(REPORTER.experiment_json(exp))
        assert payload["experiment_id"] == "e1"
        assert payload["metrics"]["sharpe"] == 2.0


class TestLeaderboardReport:
    def _rows(self) -> tuple:
        experiments = [
            make_experiment(experiment_id="a", sharpe=2.0, total_return=20.0),
            make_experiment(experiment_id="b", sharpe=1.0, total_return=10.0),
        ]
        return Leaderboard().rank(experiments, by=RankMetric.SHARPE)

    def test_markdown_table(self) -> None:
        md = REPORTER.leaderboard_markdown(self._rows(), title="Top Strategies")
        assert "# Top Strategies" in md
        assert "| Rank |" in md
        assert md.count("\n") > 3

    def test_json(self) -> None:
        payload = json.loads(REPORTER.leaderboard_json(self._rows()))
        assert payload[0]["rank"] == 1

    def test_html_embeds_table_and_chart(self) -> None:
        html = REPORTER.leaderboard_html(self._rows(), title="Top Strategies")
        assert "<!doctype html>" in html
        assert "<table>" in html
        assert "plotly" in html.lower()


class TestComparisonReport:
    def _result(self):
        a = make_experiment(experiment_id="a", sharpe=1.0)
        b = make_experiment(experiment_id="b", sharpe=2.0)
        return compare(a, b, label_a="A", label_b="B")

    def test_markdown(self) -> None:
        md = REPORTER.comparison_markdown(self._result())
        assert "Comparison: A vs B" in md
        assert "Delta (B-A)" in md
        assert "Overall winner" in md

    def test_json(self) -> None:
        payload = json.loads(REPORTER.comparison_json(self._result()))
        assert payload["label_a"] == "A"

    def test_html(self) -> None:
        html = REPORTER.comparison_html(self._result())
        assert "<table>" in html
        assert "plotly" in html.lower()


class TestWalkForwardReport:
    def _report(self) -> WalkForwardReport:
        window = WalkForwardWindowReport(
            window_index=0,
            selected_parameters={"lots": 2},
            train=make_experiment(experiment_id="t", sharpe=1.5),
            validation=make_experiment(experiment_id="v", sharpe=1.2),
            test=make_experiment(experiment_id="x", sharpe=0.9),
        )
        return WalkForwardReport(
            score_metric="sharpe",
            windows=(window,),
            mean_test_score=0.9,
            mean_validation_score=1.2,
        )

    def test_markdown(self) -> None:
        md = REPORTER.walkforward_markdown(self._report())
        assert "Walk-Forward Analysis" in md
        assert "Selected params" in md
        assert '"lots": 2' in md

    def test_json(self) -> None:
        payload = json.loads(REPORTER.walkforward_json(self._report()))
        assert payload["score_metric"] == "sharpe"
        assert len(payload["windows"]) == 1


class TestCrossValidationReport:
    def _report(self) -> CrossValidationReport:
        fold = FoldResult(
            fold_index=0,
            train_size=4,
            test_size=2,
            experiment=make_experiment(experiment_id="f", sharpe=1.1),
        )
        return CrossValidationReport(
            scheme="rolling", score_metric="sharpe", folds=(fold,), mean_score=1.1, std_score=0.0
        )

    def test_markdown(self) -> None:
        md = REPORTER.cross_validation_markdown(self._report())
        assert "Cross-Validation (rolling)" in md
        assert "Mean score" in md

    def test_json(self) -> None:
        payload = json.loads(REPORTER.cross_validation_json(self._report()))
        assert payload["scheme"] == "rolling"


class TestHtmlEscaping:
    def test_escapes_special_characters(self) -> None:
        exp = make_experiment(experiment_id="a", sharpe=2.0)
        rows = Leaderboard().rank(
            [exp.model_copy(update={"strategy_name": "A & <B>"})], by=RankMetric.SHARPE
        )
        html = REPORTER.leaderboard_html(rows, title="Risk & <Reward>")
        assert "&amp;" in html
        assert "&lt;" in html
        assert "<B>" not in html.replace("&lt;B&gt;", "")
