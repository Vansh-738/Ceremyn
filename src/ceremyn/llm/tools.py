"""Tool definitions + dispatch — the only way the model can read Ceremyn data.

Every tool is read-only, hand-written, and fixed: there is no "run arbitrary code" tool, so
the model can never do anything this file doesn't explicitly wire up. Every tool returns a
`ToolResult` carrying a `source` string, which `llm/assistant.py` collects into a guaranteed
citation list regardless of whether the model mentions it in prose.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ceremyn.llm.exceptions import LLMToolError
from ceremyn.llm.providers import DashboardReader, ExperimentDetailReader, RecapReader
from ceremyn.llm.snapshots import StrategyCatalogEntry
from ceremyn.llm.watchlist import WatchlistStore
from ceremyn.strategies import catalog_entries


@dataclass(frozen=True)
class ToolResult:
    data: dict[str, Any]
    source: str


@dataclass(frozen=True)
class ToolContext:
    """Everything a tool function might read from, bundled per-call so every tool function
    has the same signature regardless of which provider it uses."""

    dashboard: DashboardReader
    experiments: ExperimentDetailReader
    recap: RecapReader
    watchlist: WatchlistStore
    session_id: str
    opportunities: Callable[[], dict[str, Any]] | None = None
    fundamentals: Callable[[str], dict[str, Any]] | None = None


ToolFunction = Callable[[ToolContext, dict[str, Any]], ToolResult]


def _get_portfolio_overview(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    view = ctx.dashboard.overview()
    return ToolResult(data=view.model_dump(mode="json"), source="DashboardService.overview()")


def _get_portfolio_detail(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    view = ctx.dashboard.portfolio()
    return ToolResult(data=view.model_dump(mode="json"), source="DashboardService.portfolio()")


def _get_positions(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    view = ctx.dashboard.positions()
    return ToolResult(data=view.model_dump(mode="json"), source="DashboardService.positions()")


def _get_orders(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    page = int(args.get("page", 1))
    view = ctx.dashboard.orders(page=page)
    return ToolResult(data=view.model_dump(mode="json"), source="DashboardService.orders()")


def _get_market_snapshot(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    view = ctx.dashboard.live()
    return ToolResult(data=view.model_dump(mode="json"), source="DashboardService.live()")


def _get_feature_snapshot(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    view = ctx.dashboard.features()
    return ToolResult(data=view.model_dump(mode="json"), source="DashboardService.features()")


def _get_risk_decisions(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    view = ctx.dashboard.risk()
    return ToolResult(
        data=view.model_dump(mode="json"),
        source="RiskEngine (via DashboardService.risk())",
    )


def _get_oms_status(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    view = ctx.dashboard.oms()
    return ToolResult(data=view.model_dump(mode="json"), source="DashboardService.oms()")


def _get_research_leaderboard(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    view = ctx.dashboard.research()
    return ToolResult(data=view.model_dump(mode="json"), source="DashboardService.research()")


def _get_experiment_detail(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    experiment_id = str(args.get("experiment_id", ""))
    detail = ctx.experiments.detail(experiment_id)
    data = detail.model_dump(mode="json") if detail is not None else {}
    return ToolResult(data=data, source=f"Research Lab experiment {experiment_id or '?'}")


def _get_paper_trading_status(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    view = ctx.dashboard.paper()
    return ToolResult(data=view.model_dump(mode="json"), source="DashboardService.paper()")


def _get_alerts(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    view = ctx.dashboard.alerts()
    return ToolResult(data=view.model_dump(mode="json"), source="DashboardService.alerts()")


def _get_strategy_catalog(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    entries = [StrategyCatalogEntry(**entry) for entry in catalog_entries()]
    return ToolResult(
        data={"strategies": [entry.model_dump(mode="json") for entry in entries]},
        source="strategies.catalog_entries()",
    )


def _get_daily_recap(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    brief = ctx.recap.daily()
    return ToolResult(data=brief.model_dump(mode="json"), source="OMS/Paper journal (today)")


def _get_session_recap(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    brief = ctx.recap.session()
    return ToolResult(data=brief.model_dump(mode="json"), source="OMS/Paper journal (this session)")


def _manage_watchlist(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    action = str(args.get("action", "list"))
    symbol = args.get("symbol")
    if action == "add" and symbol:
        snapshot = ctx.watchlist.add(ctx.session_id, str(symbol))
    elif action == "remove" and symbol:
        snapshot = ctx.watchlist.remove(ctx.session_id, str(symbol))
    else:
        snapshot = ctx.watchlist.list(ctx.session_id)
    return ToolResult(
        data=snapshot.model_dump(mode="json"), source="Assistant watchlist (session-local)"
    )


def _get_opportunities(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    data = ctx.opportunities() if ctx.opportunities else {"available": False}
    return ToolResult(data=data, source="Completed equity opportunity scan")


def _get_fundamentals(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    symbol = str(args.get("symbol", "")).strip().upper()
    if not symbol:
        raise LLMToolError("symbol is required")
    data = ctx.fundamentals(symbol) if ctx.fundamentals else {"available": False}
    return ToolResult(data=data, source="Publication-dated imported fundamentals")


TOOL_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "get_portfolio_overview",
        "description": "Top-line portfolio summary: net P&L, drawdown, open orders, fill "
        "ratio, kill switch status, alert count.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_portfolio_detail",
        "description": "Detailed portfolio: buying power, margin used, realized/unrealized/"
        "daily P&L, greeks, exposure by underlying.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_positions",
        "description": "Current open positions with quantity, average price, and direction.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_orders",
        "description": "Recent orders with side, quantity, fill status, and broker.",
        "input_schema": {
            "type": "object",
            "properties": {"page": {"type": "integer", "minimum": 1}},
        },
    },
    {
        "name": "get_market_snapshot",
        "description": "Live market status per underlying: spot, market status, latency, "
        "PCR, ATM strike.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_feature_snapshot",
        "description": "Latest computed feature values (IV rank, PCR, max pain, etc.) and "
        "feature cache statistics.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_risk_decisions",
        "description": "Recent risk engine decisions: approved/rejected, risk score, "
        "violations, warnings.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_oms_status",
        "description": "Order management system status: submission/fill/rejection counts, "
        "latency, kill switch, reconciliation.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_research_leaderboard",
        "description": "Research Lab experiment leaderboard, ranked by risk-adjusted return.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_experiment_detail",
        "description": "Full statistics for one research experiment by id: sharpe, sortino, "
        "calmar, drawdown, win rate, parameters.",
        "input_schema": {
            "type": "object",
            "properties": {"experiment_id": {"type": "string"}},
            "required": ["experiment_id"],
        },
    },
    {
        "name": "get_paper_trading_status",
        "description": "Paper trading engine status: submitted/filled/rejected counts, fill "
        "rate, realized/unrealized P&L.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_alerts",
        "description": "Currently active platform alerts (risk violations, disconnects, "
        "kill switch, reconciliation mismatches).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_strategy_catalog",
        "description": "Registered strategy types available on the platform, with a "
        "description of each.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_daily_recap",
        "description": "Summary of trading activity since midnight IST today.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_session_recap",
        "description": "Summary of trading activity during the current running session.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "manage_watchlist",
        "description": "Add, remove, or list symbols on the user's session-local watchlist. "
        "This never places or affects any order.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add", "remove", "list"]},
                "symbol": {"type": "string"},
            },
        },
    },
)

TOOL_DEFINITIONS += (
    {
        "name": "get_opportunities",
        "description": "Read equity research, baseline lift and adjusted significance.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_fundamentals",
        "description": "Read dated financial statements and accounting checks for a symbol.",
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    },
)

TOOL_DISPATCH: dict[str, ToolFunction] = {
    "get_opportunities": _get_opportunities,
    "get_fundamentals": _get_fundamentals,
    "get_portfolio_overview": _get_portfolio_overview,
    "get_portfolio_detail": _get_portfolio_detail,
    "get_positions": _get_positions,
    "get_orders": _get_orders,
    "get_market_snapshot": _get_market_snapshot,
    "get_feature_snapshot": _get_feature_snapshot,
    "get_risk_decisions": _get_risk_decisions,
    "get_oms_status": _get_oms_status,
    "get_research_leaderboard": _get_research_leaderboard,
    "get_experiment_detail": _get_experiment_detail,
    "get_paper_trading_status": _get_paper_trading_status,
    "get_alerts": _get_alerts,
    "get_strategy_catalog": _get_strategy_catalog,
    "get_daily_recap": _get_daily_recap,
    "get_session_recap": _get_session_recap,
    "manage_watchlist": _manage_watchlist,
}

assert {d["name"] for d in TOOL_DEFINITIONS} == set(
    TOOL_DISPATCH
), "every tool definition must have exactly one dispatch function, and vice versa"


def run_tool(name: str, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    fn = TOOL_DISPATCH.get(name)
    if fn is None:
        raise LLMToolError(f"unknown tool: {name}")
    return fn(ctx, args)
