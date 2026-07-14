"""Multi-experiment reporting: Markdown, JSON, and HTML (with Plotly charts).

Renders the Research Lab's aggregate artifacts — single experiments, leaderboards,
comparisons, walk-forward, and cross-validation — without touching the per-run
``backtest.BacktestReport`` (which this layer consumes upstream, not here).
"""

import json
from typing import Any

import plotly.graph_objects as go

from alphaquant.research.comparison import ComparisonResult
from alphaquant.research.cross_validation import CrossValidationReport
from alphaquant.research.experiment import Experiment
from alphaquant.research.leaderboard import LeaderboardRow
from alphaquant.research.walkforward import WalkForwardReport

_METRIC_ROWS: tuple[tuple[str, str], ...] = (
    ("Total Return %", "total_return"),
    ("CAGR %", "cagr"),
    ("Sharpe", "sharpe"),
    ("Sortino", "sortino"),
    ("Calmar", "calmar"),
    ("Profit Factor", "profit_factor"),
    ("Expectancy", "expectancy"),
    ("Max Drawdown", "max_drawdown"),
    ("Largest Drawdown", "largest_drawdown"),
    ("Average Win", "average_win"),
    ("Average Loss", "average_loss"),
    ("Win Rate %", "win_rate"),
    ("Probability of Ruin", "probability_of_ruin"),
    ("Trade Count", "trade_count"),
)


class ResearchReporter:
    """Render research artifacts to markdown / json / html strings."""

    # -- single experiment ------------------------------------------------

    def experiment_markdown(self, experiment: Experiment) -> str:
        lines = [
            f"# Experiment {experiment.experiment_id}",
            "",
            f"- **Strategy:** {experiment.strategy_name} (v{experiment.strategy_version})",
            f"- **Git commit:** `{experiment.git_commit}`",
            f"- **Timestamp:** {experiment.timestamp.isoformat()}",
            f"- **Market data version:** `{experiment.market_data_version[:16]}…`",
            f"- **Feature version:** {experiment.feature_version}",
            f"- **Execution time:** {experiment.execution_time_seconds:.4f}s",
            f"- **Parameters:** `{json.dumps(experiment.parameters, sort_keys=True, default=str)}`",
        ]
        if experiment.notes:
            lines.append(f"- **Notes:** {experiment.notes}")
        lines += ["", "## Metrics", "", "| Metric | Value |", "| --- | ---: |"]
        for label, attr in _METRIC_ROWS:
            lines.append(f"| {label} | {_fmt(getattr(experiment.metrics, attr))} |")
        return "\n".join(lines) + "\n"

    def experiment_json(self, experiment: Experiment) -> str:
        return json.dumps(experiment.model_dump(mode="json"), indent=2, default=str)

    # -- leaderboard ------------------------------------------------------

    def leaderboard_markdown(self, rows: tuple[LeaderboardRow, ...], *, title: str) -> str:
        lines = [
            f"# {title}",
            "",
            "| Rank | Strategy | Score | Sharpe | Sortino | Profit Factor | CAGR % | "
            "Max DD | Return % | Trades |",
            "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for row in rows:
            lines.append(
                f"| {row.rank} | {row.strategy_name} | {_fmt(row.score)} | "
                f"{_fmt(row.sharpe)} | {_fmt(row.sortino)} | {_fmt(row.profit_factor)} | "
                f"{_fmt(row.cagr)} | {_fmt(row.max_drawdown)} | {_fmt(row.total_return)} | "
                f"{row.trade_count} |"
            )
        return "\n".join(lines) + "\n"

    def leaderboard_json(self, rows: tuple[LeaderboardRow, ...]) -> str:
        return json.dumps([row.model_dump(mode="json") for row in rows], indent=2, default=str)

    def leaderboard_html(self, rows: tuple[LeaderboardRow, ...], *, title: str) -> str:
        chart = go.Figure(
            data=[
                go.Bar(
                    x=[f"#{row.rank} {row.strategy_name}" for row in rows],
                    y=[row.score for row in rows],
                    marker_color="#2b6cb0",
                )
            ],
            layout=go.Layout(
                title=title,
                xaxis_title="Experiment",
                yaxis_title="Score",
                template="plotly_white",
            ),
        )
        table = self._markdown_table_to_html(self.leaderboard_markdown(rows, title=title))
        return _html_document(title, [table, _figure_div(chart)])

    # -- comparison -------------------------------------------------------

    def comparison_markdown(self, result: ComparisonResult) -> str:
        lines = [
            f"# Comparison: {result.label_a} vs {result.label_b}",
            "",
            f"- **{result.label_a}** id: `{result.experiment_a_id}`",
            f"- **{result.label_b}** id: `{result.experiment_b_id}`",
            f"- **Wins:** {result.label_a} {result.a_wins} / {result.label_b} {result.b_wins} "
            f"/ ties {result.ties}",
            f"- **Overall winner:** {result.overall_winner}",
            "",
            f"| Metric | {result.label_a} | {result.label_b} | Delta (B-A) | Winner |",
            "| --- | ---: | ---: | ---: | :---: |",
        ]
        for row in result.metrics:
            lines.append(
                f"| {row.metric} | {_fmt(row.value_a)} | {_fmt(row.value_b)} | "
                f"{_fmt(row.delta)} | {row.winner} |"
            )
        return "\n".join(lines) + "\n"

    def comparison_json(self, result: ComparisonResult) -> str:
        return json.dumps(result.model_dump(mode="json"), indent=2, default=str)

    def comparison_html(self, result: ComparisonResult) -> str:
        metrics = [row.metric for row in result.metrics]
        chart = go.Figure(
            data=[
                go.Bar(name=result.label_a, x=metrics, y=[r.value_a for r in result.metrics]),
                go.Bar(name=result.label_b, x=metrics, y=[r.value_b for r in result.metrics]),
            ],
            layout=go.Layout(
                title=f"{result.label_a} vs {result.label_b}",
                barmode="group",
                template="plotly_white",
            ),
        )
        table = self._markdown_table_to_html(self.comparison_markdown(result))
        return _html_document(f"{result.label_a} vs {result.label_b}", [table, _figure_div(chart)])

    # -- walk-forward / cross-validation ----------------------------------

    def walkforward_markdown(self, report: WalkForwardReport) -> str:
        lines = [
            "# Walk-Forward Analysis",
            "",
            f"- **Score metric:** {report.score_metric}",
            f"- **Windows:** {len(report.windows)}",
            f"- **Mean validation score:** {_fmt(report.mean_validation_score)}",
            f"- **Mean test (out-of-sample) score:** {_fmt(report.mean_test_score)}",
            f"- **Robust:** {'yes' if report.is_robust else 'no'}",
            "",
            "| Window | Selected params | Train | Validation | Test |",
            "| ---: | --- | ---: | ---: | ---: |",
        ]
        metric = report.score_metric
        for window in report.windows:
            lines.append(
                f"| {window.window_index} | "
                f"`{json.dumps(window.selected_parameters, sort_keys=True, default=str)}` | "
                f"{_fmt(getattr(window.train.metrics, metric))} | "
                f"{_fmt(getattr(window.validation.metrics, metric))} | "
                f"{_fmt(getattr(window.test.metrics, metric))} |"
            )
        return "\n".join(lines) + "\n"

    def walkforward_json(self, report: WalkForwardReport) -> str:
        return json.dumps(report.model_dump(mode="json"), indent=2, default=str)

    def cross_validation_markdown(self, report: CrossValidationReport) -> str:
        lines = [
            f"# Cross-Validation ({report.scheme})",
            "",
            f"- **Score metric:** {report.score_metric}",
            f"- **Folds:** {report.fold_count}",
            f"- **Mean score:** {_fmt(report.mean_score)}",
            f"- **Std score:** {_fmt(report.std_score)}",
            "",
            "| Fold | Train size | Test size | Score |",
            "| ---: | ---: | ---: | ---: |",
        ]
        for fold in report.folds:
            lines.append(
                f"| {fold.fold_index} | {fold.train_size} | {fold.test_size} | "
                f"{_fmt(getattr(fold.experiment.metrics, report.score_metric))} |"
            )
        return "\n".join(lines) + "\n"

    def cross_validation_json(self, report: CrossValidationReport) -> str:
        return json.dumps(report.model_dump(mode="json"), indent=2, default=str)

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _markdown_table_to_html(markdown: str) -> str:
        """Minimal, dependency-free markdown-table -> HTML (headings + pipe tables)."""
        html_parts: list[str] = []
        in_table = False
        for line in markdown.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                html_parts.append(f"<h1>{_escape(stripped[2:])}</h1>")
            elif set(stripped) <= {"|", "-", " ", ":"} and "|" in stripped:
                continue  # table separator row
            elif stripped.startswith("|"):
                cells = [cell.strip() for cell in stripped.strip("|").split("|")]
                if not in_table:
                    html_parts.append("<table>")
                    in_table = True
                    tag = "th"
                else:
                    tag = "td"
                cells_html = "".join(f"<{tag}>{_escape(cell)}</{tag}>" for cell in cells)
                html_parts.append(f"<tr>{cells_html}</tr>")
            else:
                if in_table:
                    html_parts.append("</table>")
                    in_table = False
                if stripped:
                    html_parts.append(f"<p>{_escape(stripped)}</p>")
        if in_table:
            html_parts.append("</table>")
        return "\n".join(html_parts)


def _figure_div(figure: go.Figure) -> str:
    return str(figure.to_html(full_html=False, include_plotlyjs="cdn"))


def _html_document(title: str, bodies: list[str]) -> str:
    body = "\n".join(bodies)
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{_escape(title)}</title>"
        "<style>body{font-family:system-ui,sans-serif;margin:2rem;}"
        "table{border-collapse:collapse;margin:1rem 0;}"
        "th,td{border:1px solid #ccc;padding:4px 10px;text-align:right;}"
        "th{background:#f5f7fa;}</style></head><body>"
        f"{body}</body></html>"
    )


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )
