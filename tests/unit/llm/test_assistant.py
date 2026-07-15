from datetime import UTC, datetime

from alphaquant.core.events import EventBus
from alphaquant.dashboard.backend import DashboardService, DashboardSources
from alphaquant.llm.assistant import Assistant
from alphaquant.llm.client import ClaudeClient
from alphaquant.llm.conversation import InMemoryConversationStore
from alphaquant.llm.events import AssistantReportGenerated
from alphaquant.llm.exceptions import LLMProviderError
from alphaquant.llm.snapshots import ExperimentDetailBrief, RecapBrief
from alphaquant.llm.watchlist import InMemoryWatchlistStore
from tests.unit.llm.conftest import FakeAnthropic, FakeContentBlock, FakeMessage, FakeSDKStream

NOW = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)


class FakeExperiments:
    def __init__(self, known: dict[str, ExperimentDetailBrief] | None = None) -> None:
        self._known = known or {}

    def detail(self, experiment_id: str) -> ExperimentDetailBrief | None:
        return self._known.get(experiment_id)


class FakeRecap:
    def daily(self) -> RecapBrief:
        return RecapBrief(
            window_label="today", window_start=NOW, window_end=NOW, orders_submitted=3
        )

    def session(self) -> RecapBrief:
        return RecapBrief(window_label="this session", window_start=NOW, window_end=NOW)


def text_only(text: str) -> FakeSDKStream:
    return FakeSDKStream([text], FakeMessage(content=[FakeContentBlock(type="text", text=text)]))


def tool_call(tool_name: str, tool_input: dict, *, text: str = "") -> FakeSDKStream:
    blocks = []
    if text:
        blocks.append(FakeContentBlock(type="text", text=text))
    blocks.append(FakeContentBlock(type="tool_use", id="t1", name=tool_name, input=tool_input))
    return FakeSDKStream(
        [text] if text else [], FakeMessage(content=blocks, stop_reason="tool_use")
    )


def make_assistant(
    *,
    turns: list[FakeSDKStream] | None = None,
    event_bus: EventBus | None = None,
    max_tool_iterations: int = 5,
    experiments: FakeExperiments | None = None,
) -> tuple[Assistant, FakeAnthropic]:
    fake = FakeAnthropic(turns or [])
    client = ClaudeClient(fake, model="claude-sonnet-5")
    assistant = Assistant(
        client_factory=lambda: client,
        dashboard=DashboardService(DashboardSources()),
        experiments=experiments or FakeExperiments(),
        recap=FakeRecap(),
        watchlist=InMemoryWatchlistStore(),
        conversation=InMemoryConversationStore(),
        event_bus=event_bus,
        max_tool_iterations=max_tool_iterations,
    )
    return assistant, fake


async def test_client_factory_is_never_called_until_a_turn_needs_it() -> None:
    built: list[int] = []

    def factory() -> ClaudeClient:
        built.append(1)
        fake = FakeAnthropic([text_only("hi"), text_only("hi again")])
        return ClaudeClient(fake, model="claude-sonnet-5")

    assistant = Assistant(
        client_factory=factory,
        dashboard=DashboardService(DashboardSources()),
        experiments=FakeExperiments(),
        recap=FakeRecap(),
        watchlist=InMemoryWatchlistStore(),
        conversation=InMemoryConversationStore(),
    )
    assert built == []  # constructing the Assistant must never touch the factory

    async for _ in assistant.chat("s1", "hello"):
        pass
    assert built == [1]

    async for _ in assistant.chat("s1", "hello again"):
        pass
    assert built == [1]  # cached, not rebuilt on the second turn


async def test_chat_streams_text_and_ends_with_done() -> None:
    assistant, _ = make_assistant(turns=[text_only("hello there")])
    events = [event async for event in assistant.chat("s1", "hi")]

    assert events[0].type == "text_delta"
    assert events[0].text == "hello there"
    assert events[-1].type == "done"
    assert events[-1].citations == ()


async def test_chat_saves_conversation_history() -> None:
    assistant, _ = make_assistant(turns=[text_only("hello there")])
    async for _ in assistant.chat("s1", "hi"):
        pass

    history = assistant._conversation.history("s1")
    assert [m.role for m in history] == ["user", "assistant"]
    assert history[0].content == "hi"
    assert history[1].content == "hello there"


async def test_chat_second_turn_includes_prior_history() -> None:
    assistant, fake = make_assistant(turns=[text_only("first"), text_only("second")])
    async for _ in assistant.chat("s1", "question one"):
        pass
    async for _ in assistant.chat("s1", "question two"):
        pass

    second_call_messages = fake.messages.calls[1]["messages"]
    contents = [m["content"] for m in second_call_messages]
    assert "question one" in contents
    assert "first" in contents
    assert "question two" in contents


async def test_chat_dispatches_a_tool_call_and_continues() -> None:
    assistant, _ = make_assistant(
        turns=[
            tool_call("get_risk_decisions", {}, text="checking..."),
            text_only("all clear"),
        ]
    )
    events = [event async for event in assistant.chat("s1", "how's my risk?")]

    tool_events = [e for e in events if e.type == "tool_call"]
    assert len(tool_events) == 1
    assert tool_events[0].name == "get_risk_decisions"
    assert tool_events[0].source is not None

    done = events[-1]
    assert done.type == "done"
    assert done.citations == (tool_events[0].source,)


async def test_chat_tool_result_is_sent_back_to_the_model() -> None:
    assistant, fake = make_assistant(turns=[tool_call("get_risk_decisions", {}), text_only("done")])
    async for _ in assistant.chat("s1", "risk?"):
        pass

    second_call_messages = fake.messages.calls[1]["messages"]
    tool_result_turn = second_call_messages[-1]
    assert tool_result_turn["role"] == "user"
    assert tool_result_turn["content"][0]["type"] == "tool_result"
    assert tool_result_turn["content"][0]["tool_use_id"] == "t1"


async def test_chat_stops_after_max_tool_iterations() -> None:
    # The model asks for a tool every single turn, forever - the loop must still terminate.
    turns = [tool_call("get_risk_decisions", {}) for _ in range(10)]
    assistant, fake = make_assistant(turns=turns, max_tool_iterations=3)
    events = [event async for event in assistant.chat("s1", "risk?")]

    assert len(fake.messages.calls) == 3
    assert events[-1].type == "done"


async def test_chat_emits_error_event_on_provider_failure() -> None:
    assistant, fake = make_assistant()
    fake.messages.fail_next(RuntimeError("api down"))
    events = [event async for event in assistant.chat("s1", "hi")]

    assert events[-1].type == "error"
    assert "api down" in (events[-1].message or "")


async def test_chat_emits_error_event_when_client_factory_fails() -> None:
    def factory() -> ClaudeClient:
        raise LLMProviderError("ALPHAQUANT_ANTHROPIC__API_KEY is not configured")

    assistant = Assistant(
        client_factory=factory,
        dashboard=DashboardService(DashboardSources()),
        experiments=FakeExperiments(),
        recap=FakeRecap(),
        watchlist=InMemoryWatchlistStore(),
        conversation=InMemoryConversationStore(),
    )
    events = [event async for event in assistant.chat("s1", "hi")]

    assert events[-1].type == "error"
    assert "API_KEY" in (events[-1].message or "")


async def test_chat_does_not_save_history_when_the_turn_errors() -> None:
    assistant, fake = make_assistant()
    fake.messages.fail_next(RuntimeError("api down"))
    async for _ in assistant.chat("s1", "hi"):
        pass

    history = assistant._conversation.history("s1")
    assert [m.role for m in history] == ["user"]  # only the user's message, no assistant reply


async def test_chat_never_publishes_to_the_event_bus() -> None:
    received: list[AssistantReportGenerated] = []
    bus = EventBus()
    bus.subscribe(AssistantReportGenerated, lambda e: received.append(e))
    assistant, _ = make_assistant(turns=[text_only("hi")], event_bus=bus)

    async for _ in assistant.chat("s1", "hi"):
        pass

    assert received == []


async def test_daily_recap_seeds_pre_fetched_tools() -> None:
    assistant, fake = make_assistant(turns=[text_only("quiet day")])
    events = [event async for event in assistant.daily_recap("s1")]

    seeded_names = [e.name for e in events if e.type == "tool_call"]
    assert seeded_names == ["get_daily_recap", "get_portfolio_overview", "get_risk_decisions"]

    sent_content = fake.messages.calls[0]["messages"][0]["content"]
    assert "orders_submitted" in sent_content


async def test_daily_recap_publishes_event_with_citations() -> None:
    received: list[AssistantReportGenerated] = []
    bus = EventBus()
    bus.subscribe(AssistantReportGenerated, lambda e: received.append(e))
    assistant, _ = make_assistant(turns=[text_only("quiet day")], event_bus=bus)

    async for _ in assistant.daily_recap("s1"):
        pass

    assert len(received) == 1
    assert received[0].kind == "daily_recap"
    assert received[0].session_id == "s1"
    assert len(received[0].citations) == 3


async def test_daily_recap_model_can_request_additional_tools() -> None:
    assistant, _ = make_assistant(
        turns=[
            tool_call("get_alerts", {}, text="let me also check alerts"),
            text_only("all quiet, no alerts"),
        ]
    )
    events = [event async for event in assistant.daily_recap("s1")]

    tool_names = [e.name for e in events if e.type == "tool_call"]
    assert tool_names == [
        "get_daily_recap",
        "get_portfolio_overview",
        "get_risk_decisions",
        "get_alerts",
    ]

    done = events[-1]
    assert done.type == "done"
    assert "DashboardService.alerts()" in done.citations


async def test_session_recap_seeds_session_tool() -> None:
    assistant, fake = make_assistant(turns=[text_only("session summary")])
    events = [event async for event in assistant.session_recap("s1")]

    seeded_names = [e.name for e in events if e.type == "tool_call"]
    assert seeded_names[0] == "get_session_recap"


async def test_generate_report_uses_the_topic_as_the_message() -> None:
    assistant, fake = make_assistant(turns=[text_only("report text")])
    async for _ in assistant.generate_report("s1", "summarize this week's research"):
        pass

    assert fake.messages.calls[0]["messages"][0]["content"] == "summarize this week's research"


async def test_generate_report_collects_citations_from_tool_calls() -> None:
    assistant, _ = make_assistant(
        turns=[
            tool_call("get_research_leaderboard", {}),
            text_only("here is the report"),
        ]
    )
    events = [event async for event in assistant.generate_report("s1", "summarize research")]
    done = events[-1]
    assert done.type == "done"
    assert done.citations == ("DashboardService.research()",)


async def test_generate_report_publishes_event() -> None:
    received: list[AssistantReportGenerated] = []
    bus = EventBus()
    bus.subscribe(AssistantReportGenerated, lambda e: received.append(e))
    assistant, _ = make_assistant(turns=[text_only("report")], event_bus=bus)

    async for _ in assistant.generate_report("s1", "topic"):
        pass

    assert received[0].kind == "report"


async def test_compare_experiments_seeds_one_call_per_experiment() -> None:
    experiments = FakeExperiments(
        {
            "e1": ExperimentDetailBrief(experiment_id="e1", strategy_name="A", timestamp=NOW),
            "e2": ExperimentDetailBrief(experiment_id="e2", strategy_name="B", timestamp=NOW),
        }
    )
    assistant, fake = make_assistant(turns=[text_only("comparison")], experiments=experiments)
    events = [event async for event in assistant.compare_experiments("s1", ["e1", "e2"])]

    seeded_names = [e.name for e in events if e.type == "tool_call"]
    assert seeded_names == ["get_experiment_detail", "get_experiment_detail"]


async def test_compare_experiments_publishes_comparison_kind() -> None:
    received: list[AssistantReportGenerated] = []
    bus = EventBus()
    bus.subscribe(AssistantReportGenerated, lambda e: received.append(e))
    assistant, _ = make_assistant(turns=[text_only("comparison")], event_bus=bus)

    async for _ in assistant.compare_experiments("s1", ["e1"]):
        pass

    assert received[0].kind == "comparison"


async def test_assistant_without_event_bus_does_not_raise_on_recap() -> None:
    assistant, _ = make_assistant(turns=[text_only("ok")], event_bus=None)
    events = [event async for event in assistant.daily_recap("s1")]
    assert events[-1].type in ("done", "text_delta") or any(e.type == "done" for e in events)


async def test_manage_watchlist_tool_is_reachable_via_chat() -> None:
    assistant, _ = make_assistant(
        turns=[
            tool_call("manage_watchlist", {"action": "add", "symbol": "NIFTY"}),
            text_only("added NIFTY to your watchlist"),
        ]
    )
    events = [event async for event in assistant.chat("s1", "add nifty to my watchlist")]
    tool_events = [e for e in events if e.type == "tool_call"]
    assert tool_events[0].name == "manage_watchlist"
