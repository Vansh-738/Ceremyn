from datetime import UTC, datetime, timedelta

from ceremyn.api.llm_runtime import _ExperimentDetailAdapter, _RecapAdapter, build_assistant
from ceremyn.api.runtime import build_dashboard_sources
from ceremyn.config import Settings
from ceremyn.core.container import Container
from ceremyn.core.timeutils import now_ist
from ceremyn.dashboard.backend import DashboardService
from ceremyn.llm.assistant import Assistant
from ceremyn.oms.journal import JournalEntry as OMSJournalEntry
from ceremyn.oms.journal import JournalEntryKind as OMSJournalEntryKind
from ceremyn.paper.journal import JournalEntry as PaperJournalEntry
from ceremyn.paper.journal import JournalEntryKind as PaperJournalEntryKind
from ceremyn.research.experiment import Experiment
from ceremyn.research.experiment_store import InMemoryExperimentStore
from ceremyn.research.statistics import ExperimentMetrics

NOW = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)


def make_container() -> Container:
    return Container(Settings(_env_file=None, anthropic={"api_key": "demo-key"}))  # type: ignore[call-arg]


def test_build_assistant_returns_a_working_assistant() -> None:
    container = make_container()
    service = DashboardService(build_dashboard_sources(container))
    assistant = build_assistant(container, service)
    assert isinstance(assistant, Assistant)


class TestExperimentDetailAdapter:
    def test_missing_experiment_returns_none(self) -> None:
        adapter = _ExperimentDetailAdapter(make_container())
        assert adapter.detail("does-not-exist") is None

    def test_found_experiment_is_translated(self) -> None:
        container = make_container()
        # Override the default JSONExperimentStore (which writes to the shared
        # data/research/experiments/ directory) so this test never touches disk.
        container.__dict__["experiment_store"] = InMemoryExperimentStore()
        experiment = Experiment(
            experiment_id="e1",
            spec_hash="hash",
            strategy_name="Short Strangle",
            market_data_version="v1",
            timestamp=NOW,
            parameters={"delta": 0.16},
            metrics=ExperimentMetrics(sharpe=1.4, sortino=1.8, trade_count=42),
            notes="test note",
        )
        container.experiment_store.save(experiment)

        adapter = _ExperimentDetailAdapter(container)
        brief = adapter.detail("e1")

        assert brief is not None
        assert brief.experiment_id == "e1"
        assert brief.strategy_name == "Short Strangle"
        assert brief.sharpe == 1.4
        assert brief.sortino == 1.8
        assert brief.trade_count == 42
        assert brief.parameters == {"delta": 0.16}
        assert brief.notes == "test note"


class TestRecapAdapter:
    def test_daily_recap_with_no_activity(self) -> None:
        adapter = _RecapAdapter(make_container())
        brief = adapter.daily()
        assert brief.window_label == "today"
        assert brief.orders_filled == 0
        assert brief.notable_events == ()

    def test_session_recap_with_no_activity(self) -> None:
        adapter = _RecapAdapter(make_container())
        brief = adapter.session()
        assert brief.window_label == "this session"
        assert brief.orders_submitted == 0

    def test_daily_recap_counts_fills_and_signals_from_both_journals(self) -> None:
        container = make_container()
        midnight_ist_today = now_ist().replace(hour=0, minute=0, second=0, microsecond=0)
        today_utc = midnight_ist_today.astimezone(UTC) + timedelta(hours=6)

        container.oms_engine.journal.store.append(
            OMSJournalEntry(
                kind=OMSJournalEntryKind.FILL,
                timestamp=today_utc,
                session_id="s",
                payload={"order_id": "o1"},
            )
        )
        container.paper_engine.journal.store.append(
            PaperJournalEntry(
                kind=PaperJournalEntryKind.SIGNAL,
                timestamp=today_utc,
                session_id="s",
                payload={"strategy_id": "strat"},
            )
        )

        brief = _RecapAdapter(container).daily()
        assert brief.orders_filled == 1
        assert brief.orders_submitted == 1
        assert len(brief.notable_events) == 2

    def test_daily_recap_excludes_entries_before_todays_midnight_ist(self) -> None:
        container = make_container()
        yesterday = now_ist().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        container.oms_engine.journal.store.append(
            OMSJournalEntry(
                kind=OMSJournalEntryKind.FILL,
                timestamp=yesterday.astimezone(UTC),
                session_id="s",
                payload={"order_id": "o1"},
            )
        )

        brief = _RecapAdapter(container).daily()
        assert brief.orders_filled == 0

    def test_daily_recap_counts_rejected_risk_decisions(self) -> None:
        container = make_container()
        today = now_ist().replace(hour=12, minute=0, second=0, microsecond=0).astimezone(UTC)
        container.oms_engine.journal.store.append(
            OMSJournalEntry(
                kind=OMSJournalEntryKind.RISK_DECISION,
                timestamp=today,
                session_id="s",
                payload={"approved": False, "violations": ["margin exceeded", "kill switch"]},
            )
        )

        brief = _RecapAdapter(container).daily()
        assert brief.orders_rejected == 1
        assert brief.risk_violations == 2

    def test_daily_recap_does_not_count_approved_risk_decisions_as_rejected(self) -> None:
        container = make_container()
        today = now_ist().replace(hour=12, minute=0, second=0, microsecond=0).astimezone(UTC)
        container.oms_engine.journal.store.append(
            OMSJournalEntry(
                kind=OMSJournalEntryKind.RISK_DECISION,
                timestamp=today,
                session_id="s",
                payload={"approved": True, "violations": []},
            )
        )

        brief = _RecapAdapter(container).daily()
        assert brief.orders_rejected == 0
