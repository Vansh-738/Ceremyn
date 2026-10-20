"""The tool-calling engine: one Claude conversation loop implements all twelve capabilities.

Open-ended chat lets the model decide which tools to call. The "batch" capabilities (recaps,
reports, comparisons) seed the same loop with pre-fetched, deterministic tool results so they
don't depend on the model guessing which tool to reach for — same underlying loop, same
citation and streaming mechanics, no duplicated logic.
"""

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Literal

from ceremyn.core.events import EventBus
from ceremyn.core.timeutils import now_utc
from ceremyn.llm.client import ClaudeClient
from ceremyn.llm.conversation import ConversationMessage, ConversationStore
from ceremyn.llm.events import AssistantReportGenerated
from ceremyn.llm.exceptions import LLMError
from ceremyn.llm.prompts import (
    CHAT_SYSTEM_PROMPT,
    COMPARISON_SYSTEM_PROMPT,
    DAILY_RECAP_SYSTEM_PROMPT,
    REPORT_SYSTEM_PROMPT,
    SESSION_RECAP_SYSTEM_PROMPT,
)
from ceremyn.llm.providers import DashboardReader, ExperimentDetailReader, RecapReader
from ceremyn.llm.tools import TOOL_DEFINITIONS, ToolContext, run_tool
from ceremyn.llm.watchlist import WatchlistStore

StreamEventType = Literal["text_delta", "tool_call", "done", "error"]

MAX_TOOL_ITERATIONS = 5


@dataclass(frozen=True)
class StreamEvent:
    type: StreamEventType
    text: str | None = None
    name: str | None = None
    source: str | None = None
    citations: tuple[str, ...] = ()
    message: str | None = None


class Assistant:
    def __init__(
        self,
        *,
        client_factory: Callable[[], ClaudeClient],
        dashboard: DashboardReader,
        experiments: ExperimentDetailReader,
        recap: RecapReader,
        watchlist: WatchlistStore,
        conversation: ConversationStore,
        event_bus: EventBus | None = None,
        max_tool_iterations: int = MAX_TOOL_ITERATIONS,
        opportunities: Callable[[], dict[str, Any]] | None = None,
        fundamentals: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        # `client_factory` is called (and cached) only the first time a turn actually needs
        # to reach Claude — never at construction — so a missing Anthropic API key never
        # breaks building the assistant itself, same as `execution.gated_broker
        # .GatedBrokerAdapter`'s lazy `live_factory`.
        self._opportunities = opportunities
        self._fundamentals = fundamentals
        self._client_factory = client_factory
        self._client: ClaudeClient | None = None
        self._dashboard = dashboard
        self._experiments = experiments
        self._recap = recap
        self._watchlist = watchlist
        self._conversation = conversation
        self._event_bus = event_bus
        self._max_tool_iterations = max_tool_iterations

    def _resolve_client(self) -> ClaudeClient:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    async def chat(self, session_id: str, message: str) -> AsyncIterator[StreamEvent]:
        """Open-ended Q&A / explanations. The model decides which tools to call."""
        self._conversation.append(session_id, ConversationMessage(role="user", content=message))
        messages = self._history_messages(session_id)
        text_parts: list[str] = []
        async for event in self._run(CHAT_SYSTEM_PROMPT, messages, session_id):
            if event.type == "text_delta" and event.text:
                text_parts.append(event.text)
            yield event
        if text_parts:
            self._conversation.append(
                session_id, ConversationMessage(role="assistant", content="".join(text_parts))
            )

    async def daily_recap(self, session_id: str) -> AsyncIterator[StreamEvent]:
        async for event in self._run_seeded(
            DAILY_RECAP_SYSTEM_PROMPT,
            session_id,
            seed_calls=[
                ("get_daily_recap", {}),
                ("get_portfolio_overview", {}),
                ("get_risk_decisions", {}),
            ],
            instruction="Generate today's recap.",
            kind="daily_recap",
        ):
            yield event

    async def session_recap(self, session_id: str) -> AsyncIterator[StreamEvent]:
        async for event in self._run_seeded(
            SESSION_RECAP_SYSTEM_PROMPT,
            session_id,
            seed_calls=[
                ("get_session_recap", {}),
                ("get_portfolio_overview", {}),
                ("get_risk_decisions", {}),
            ],
            instruction="Generate a recap of the current session.",
            kind="session_recap",
        ):
            yield event

    async def generate_report(self, session_id: str, topic: str) -> AsyncIterator[StreamEvent]:
        """Open-ended structured report — the model decides which tools support `topic`."""
        messages: list[dict[str, Any]] = [{"role": "user", "content": topic}]
        citations: list[str] = []
        async for event in self._run(REPORT_SYSTEM_PROMPT, messages, session_id):
            if event.type == "tool_call" and event.source:
                citations.append(event.source)
            yield event
        await self._publish(session_id, "report", tuple(dict.fromkeys(citations)))

    async def compare_experiments(
        self, session_id: str, experiment_ids: list[str]
    ) -> AsyncIterator[StreamEvent]:
        async for event in self._run_seeded(
            COMPARISON_SYSTEM_PROMPT,
            session_id,
            seed_calls=[
                ("get_experiment_detail", {"experiment_id": eid}) for eid in experiment_ids
            ],
            instruction=f"Compare these experiments: {', '.join(experiment_ids)}.",
            kind="comparison",
        ):
            yield event

    # -- internal -------------------------------------------------------------

    def _history_messages(self, session_id: str) -> list[dict[str, Any]]:
        return [
            {"role": message.role, "content": message.content}
            for message in self._conversation.history(session_id)
        ]

    def _tool_context(self, session_id: str) -> ToolContext:
        return ToolContext(
            dashboard=self._dashboard,
            experiments=self._experiments,
            recap=self._recap,
            watchlist=self._watchlist,
            session_id=session_id,
            opportunities=self._opportunities,
            fundamentals=self._fundamentals,
        )

    async def _run_seeded(
        self,
        system: str,
        session_id: str,
        *,
        seed_calls: list[tuple[str, dict[str, Any]]],
        instruction: str,
        kind: str,
    ) -> AsyncIterator[StreamEvent]:
        """Runs the named tools directly (deterministic, no model round-trip needed to
        discover them), seeds their results into the first user turn, then lets the model
        write the narrative — still free to call further tools if it wants more detail."""
        ctx = self._tool_context(session_id)
        seed_citations: list[str] = []
        seed_lines: list[str] = []
        for name, args in seed_calls:
            result = run_tool(name, args, ctx)
            seed_citations.append(result.source)
            seed_lines.append(f"[{name}] (source: {result.source})\n{json.dumps(result.data)}")
            yield StreamEvent(type="tool_call", name=name, source=result.source)

        seed_text = "\n\n".join(seed_lines)
        content = (
            f"{instruction}\n\nData already fetched:\n{seed_text}" if seed_lines else instruction
        )
        messages: list[dict[str, Any]] = [{"role": "user", "content": content}]

        all_citations = list(seed_citations)
        async for event in self._run(system, messages, session_id):
            if event.type == "tool_call" and event.source:
                all_citations.append(event.source)
            elif event.type == "done":
                event = StreamEvent(type="done", citations=tuple(dict.fromkeys(all_citations)))
            yield event
        await self._publish(session_id, kind, tuple(dict.fromkeys(all_citations)))

    async def _run(
        self, system: str, messages: list[dict[str, Any]], session_id: str
    ) -> AsyncIterator[StreamEvent]:
        ctx = self._tool_context(session_id)
        citations: list[str] = []
        try:
            client = self._resolve_client()
            for _ in range(self._max_tool_iterations):
                async with client.stream(
                    system=system, messages=messages, tools=list(TOOL_DEFINITIONS)
                ) as stream:
                    async for delta in stream.text_deltas():
                        yield StreamEvent(type="text_delta", text=delta)
                    result = await stream.final()

                assistant_content: list[dict[str, Any]] = []
                if result.text:
                    assistant_content.append({"type": "text", "text": result.text})
                for tool_use in result.tool_uses:
                    assistant_content.append(
                        {
                            "type": "tool_use",
                            "id": tool_use.id,
                            "name": tool_use.name,
                            "input": tool_use.input,
                        }
                    )
                messages.append({"role": "assistant", "content": assistant_content})

                if not result.tool_uses:
                    yield StreamEvent(type="done", citations=tuple(dict.fromkeys(citations)))
                    return

                tool_result_blocks: list[dict[str, Any]] = []
                for tool_use in result.tool_uses:
                    tool_result = run_tool(tool_use.name, tool_use.input, ctx)
                    citations.append(tool_result.source)
                    yield StreamEvent(
                        type="tool_call", name=tool_use.name, source=tool_result.source
                    )
                    tool_result_blocks.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": json.dumps(tool_result.data),
                        }
                    )
                messages.append({"role": "user", "content": tool_result_blocks})

            yield StreamEvent(type="done", citations=tuple(dict.fromkeys(citations)))
        except LLMError as exc:
            yield StreamEvent(type="error", message=str(exc))

    async def _publish(self, session_id: str, kind: str, citations: tuple[str, ...]) -> None:
        if self._event_bus is None:
            return
        await self._event_bus.publish(
            AssistantReportGenerated(
                occurred_at=now_utc(), session_id=session_id, kind=kind, citations=citations
            )
        )
