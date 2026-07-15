from datetime import UTC, datetime

import pytest

from alphaquant.dashboard.backend import DashboardService, DashboardSources
from alphaquant.llm.exceptions import LLMToolError
from alphaquant.llm.snapshots import ExperimentDetailBrief, RecapBrief
from alphaquant.llm.tools import TOOL_DEFINITIONS, TOOL_DISPATCH, ToolContext, run_tool
from alphaquant.llm.watchlist import InMemoryWatchlistStore

NOW = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)


class FakeExperiments:
    def detail(self, experiment_id: str) -> ExperimentDetailBrief | None:
        if experiment_id == "e1":
            return ExperimentDetailBrief(
                experiment_id="e1", strategy_name="Short Strangle", timestamp=NOW, sharpe=1.5
            )
        return None


class FakeRecap:
    def daily(self) -> RecapBrief:
        return RecapBrief(window_label="today", window_start=NOW, window_end=NOW)

    def session(self) -> RecapBrief:
        return RecapBrief(window_label="this session", window_start=NOW, window_end=NOW)


def make_context(session_id: str = "s1") -> ToolContext:
    return ToolContext(
        dashboard=DashboardService(DashboardSources()),
        experiments=FakeExperiments(),
        recap=FakeRecap(),
        watchlist=InMemoryWatchlistStore(),
        session_id=session_id,
    )


def test_every_tool_definition_has_a_dispatch_entry() -> None:
    defined = {tool["name"] for tool in TOOL_DEFINITIONS}
    assert defined == set(TOOL_DISPATCH)


def test_every_tool_definition_has_name_description_and_schema() -> None:
    for tool in TOOL_DEFINITIONS:
        assert tool["name"]
        assert tool["description"]
        assert tool["input_schema"]["type"] == "object"


@pytest.mark.parametrize(
    "name",
    [
        "get_portfolio_overview",
        "get_portfolio_detail",
        "get_positions",
        "get_market_snapshot",
        "get_feature_snapshot",
        "get_risk_decisions",
        "get_oms_status",
        "get_research_leaderboard",
        "get_paper_trading_status",
        "get_alerts",
        "get_strategy_catalog",
        "get_daily_recap",
        "get_session_recap",
    ],
)
def test_zero_argument_tools_run_and_carry_a_source(name: str) -> None:
    result = run_tool(name, {}, make_context())
    assert isinstance(result.data, dict)
    assert result.source


def test_get_orders_forwards_page() -> None:
    result = run_tool("get_orders", {"page": 2}, make_context())
    assert result.data["page"] == 2


def test_get_orders_defaults_to_page_one() -> None:
    result = run_tool("get_orders", {}, make_context())
    assert result.data["page"] == 1


def test_get_experiment_detail_found() -> None:
    result = run_tool("get_experiment_detail", {"experiment_id": "e1"}, make_context())
    assert result.data["sharpe"] == 1.5
    assert "e1" in result.source


def test_get_experiment_detail_not_found_returns_empty_data() -> None:
    result = run_tool("get_experiment_detail", {"experiment_id": "missing"}, make_context())
    assert result.data == {}


def test_manage_watchlist_add_then_list() -> None:
    ctx = make_context()
    added = run_tool("manage_watchlist", {"action": "add", "symbol": "nifty"}, ctx)
    assert added.data["symbols"] == ["NIFTY"]

    listed = run_tool("manage_watchlist", {"action": "list"}, ctx)
    assert listed.data["symbols"] == ["NIFTY"]


def test_manage_watchlist_remove() -> None:
    ctx = make_context()
    run_tool("manage_watchlist", {"action": "add", "symbol": "NIFTY"}, ctx)
    removed = run_tool("manage_watchlist", {"action": "remove", "symbol": "nifty"}, ctx)
    assert removed.data["symbols"] == []


def test_manage_watchlist_defaults_to_list() -> None:
    result = run_tool("manage_watchlist", {}, make_context())
    assert result.data["symbols"] == []


def test_manage_watchlist_is_session_scoped() -> None:
    ctx1 = make_context("s1")
    ctx2 = make_context("s2")
    run_tool("manage_watchlist", {"action": "add", "symbol": "NIFTY"}, ctx1)
    listed = run_tool("manage_watchlist", {"action": "list"}, ctx2)
    assert listed.data["symbols"] == []


def test_unknown_tool_raises() -> None:
    with pytest.raises(LLMToolError):
        run_tool("delete_everything", {}, make_context())
