"""Composition-edge adapters for the LLM assistant — same shape as `api/runtime.py`'s
dashboard adapters, translating `Container` engines into the two small provider Protocols
`llm/providers.py` defines beyond `DashboardReader` (which the real `DashboardService`
already satisfies directly, so no adapter is needed for it at all).
"""

from datetime import UTC, datetime

from alphaquant.core.container import Container
from alphaquant.core.timeutils import now_ist, now_utc
from alphaquant.dashboard.backend import DashboardService
from alphaquant.llm.assistant import Assistant
from alphaquant.llm.snapshots import ExperimentDetailBrief, RecapBrief
from alphaquant.oms.journal import JournalEntry as OMSJournalEntry
from alphaquant.paper.journal import JournalEntry as PaperJournalEntry

_JournalEntry = OMSJournalEntry | PaperJournalEntry


class _ExperimentDetailAdapter:
    def __init__(self, container: Container) -> None:
        self._container = container

    def detail(self, experiment_id: str) -> ExperimentDetailBrief | None:
        experiment = self._container.experiment_store.get(experiment_id)
        if experiment is None:
            return None
        metrics = experiment.metrics
        return ExperimentDetailBrief(
            experiment_id=experiment.experiment_id,
            strategy_name=experiment.strategy_name,
            strategy_version=experiment.strategy_version,
            parameters=experiment.parameters,
            timestamp=experiment.timestamp,
            total_return=metrics.total_return,
            sharpe=metrics.sharpe,
            sortino=metrics.sortino,
            calmar=metrics.calmar,
            profit_factor=metrics.profit_factor,
            max_drawdown=metrics.max_drawdown,
            cagr=metrics.cagr,
            win_rate=metrics.win_rate,
            trade_count=metrics.trade_count,
            notes=experiment.notes,
        )


def _midnight_ist_today() -> datetime:
    ist_now = now_ist()
    ist_midnight = ist_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return ist_midnight.astimezone(UTC)


class _RecapAdapter:
    """Best-effort narrative summaries over the OMS/Paper journals — a research aid, not a
    ledger (the tools that seed exact figures, e.g. `get_oms_status`, are always fetched
    alongside these; see `llm.assistant.Assistant.daily_recap`/`.session_recap`)."""

    def __init__(self, container: Container) -> None:
        self._container = container

    def daily(self) -> RecapBrief:
        return self._build_from_journal("today", _midnight_ist_today())

    def session(self) -> RecapBrief:
        # OMS/paper metrics are already cumulative since this process's engines were
        # constructed, so "this session" needs no journal filtering.
        oms_metrics = self._container.oms_engine.metrics_snapshot()
        paper_monitor = self._container.paper_engine.monitor.snapshot()
        portfolio = self._container.oms_engine.portfolio.snapshot()
        now = now_utc()
        decisions = self._container.risk_engine.recent_decisions()
        violations = sum(len(d.violations) for d in decisions)
        return RecapBrief(
            window_label="this session",
            window_start=now,
            window_end=now,
            orders_submitted=oms_metrics.orders_submitted + paper_monitor.submitted,
            orders_filled=oms_metrics.orders_filled + paper_monitor.filled,
            orders_rejected=oms_metrics.rejections + paper_monitor.rejected,
            net_pnl=float(portfolio.realized_pnl + portfolio.unrealized_pnl),
            risk_violations=violations,
        )

    def _build_from_journal(self, label: str, since: datetime) -> RecapBrief:
        now = now_utc()
        entries: list[_JournalEntry] = [
            *self._container.oms_engine.journal.store.entries(),
            *self._container.paper_engine.journal.entries(),
        ]
        window = [entry for entry in entries if entry.timestamp >= since]
        fills = [entry for entry in window if entry.kind.value == "fill"]
        submissions = [
            entry
            for entry in window
            if entry.kind.value == "signal"
            or (entry.kind.value == "command" and "order" in entry.payload)
        ]
        risk_decisions = [entry for entry in window if entry.kind.value == "risk_decision"]
        rejections = [entry for entry in risk_decisions if entry.payload.get("approved") is False]
        violations = sum(len(entry.payload.get("violations", ())) for entry in risk_decisions)
        portfolio = self._container.oms_engine.portfolio.snapshot()
        notable = tuple(
            f"{entry.kind.value} at {entry.timestamp.isoformat()}" for entry in window[-5:]
        )
        return RecapBrief(
            window_label=label,
            window_start=since,
            window_end=now,
            orders_submitted=len(submissions),
            orders_filled=len(fills),
            orders_rejected=len(rejections),
            net_pnl=float(portfolio.realized_pnl + portfolio.unrealized_pnl),
            risk_violations=violations,
            notable_events=notable,
        )


def build_assistant(container: Container, dashboard_service: DashboardService) -> Assistant:
    """The composition edge: wraps `container`'s engines (plus the already-built
    `dashboard_service`) into the `Assistant`'s read-only dependencies. `container.llm_client`
    is never touched here — only the first time a turn actually needs it — so a missing
    Anthropic API key never breaks building the assistant itself."""
    return Assistant(
        client_factory=lambda: container.llm_client,
        dashboard=dashboard_service,
        experiments=_ExperimentDetailAdapter(container),
        recap=_RecapAdapter(container),
        watchlist=container.watchlist_store,
        conversation=container.conversation_store,
        event_bus=container.event_bus,
    )
