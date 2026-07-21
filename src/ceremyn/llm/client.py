"""Thin wrapper over the Anthropic SDK — the only place `llm` ever talks to the network.

Symmetric with `execution.kite_broker.KiteBroker` / `data.providers.kite.KiteProvider`: the
underlying SDK client is injected for testability; `ClaudeClient.from_settings` builds the
real one. `Assistant` (the tool-calling loop) never touches the `anthropic` SDK's own types —
only this module's small dataclasses — so the rest of `llm/` stays decoupled from the SDK's
shape.
"""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from ceremyn.config import Settings
from ceremyn.llm.exceptions import LLMProviderError

DEFAULT_MAX_TOKENS = 4096


@dataclass(frozen=True)
class ToolUseRequest:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class CompletionResult:
    text: str
    tool_uses: tuple[ToolUseRequest, ...]
    stop_reason: str | None


class ClaudeStream:
    """Wraps the SDK's stream manager so callers never see `anthropic`'s own types."""

    def __init__(self, sdk_stream: Any) -> None:
        self._sdk_stream = sdk_stream

    async def text_deltas(self) -> AsyncIterator[str]:
        try:
            async for text in self._sdk_stream.text_stream:
                yield text
        except Exception as exc:
            raise LLMProviderError(str(exc)) from exc

    async def final(self) -> CompletionResult:
        try:
            message = await self._sdk_stream.get_final_message()
        except Exception as exc:
            raise LLMProviderError(str(exc)) from exc
        text = "".join(block.text for block in message.content if block.type == "text")
        tool_uses = tuple(
            ToolUseRequest(id=block.id, name=block.name, input=dict(block.input))
            for block in message.content
            if block.type == "tool_use"
        )
        return CompletionResult(text=text, tool_uses=tool_uses, stop_reason=message.stop_reason)


class ClaudeClient:
    """Constructed with an already-configured Anthropic client (real or fake)."""

    def __init__(self, client: Any, *, model: str) -> None:
        self._client = client
        self._model = model

    @classmethod
    def from_settings(cls, settings: Settings) -> "ClaudeClient":
        from anthropic import AsyncAnthropic

        api_key = settings.anthropic.api_key.get_secret_value()
        if not api_key:
            raise LLMProviderError("CEREMYN_ANTHROPIC__API_KEY is not configured")
        return cls(AsyncAnthropic(api_key=api_key), model=settings.anthropic.model)

    @asynccontextmanager
    async def stream(
        self,
        *,
        system: str,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]] = (),
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> AsyncIterator[ClaudeStream]:
        try:
            async with self._client.messages.stream(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                tools=tools,
            ) as sdk_stream:
                yield ClaudeStream(sdk_stream)
        except LLMProviderError:
            raise
        except Exception as exc:
            raise LLMProviderError(str(exc)) from exc
