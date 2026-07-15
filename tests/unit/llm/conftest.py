"""Shared fakes for the llm test suite — mirrors tests/unit/dashboard/conftest.py's shape.

`FakeAnthropic` mimics just enough of the `anthropic` SDK's async streaming surface
(`client.messages.stream(...)` as an async context manager exposing `.text_stream` and
`.get_final_message()`) for `ClaudeClient`/`Assistant` tests to run with zero network calls.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeContentBlock:
    type: str
    text: str = ""
    id: str = ""
    name: str = ""
    input: dict[str, Any] = field(default_factory=dict)


@dataclass
class FakeMessage:
    content: list[FakeContentBlock]
    stop_reason: str | None = "end_turn"


class FakeSDKStream:
    def __init__(
        self,
        deltas: list[str],
        final_message: FakeMessage,
        *,
        fail_mid_stream: Exception | None = None,
        fail_final: Exception | None = None,
    ) -> None:
        self._deltas = deltas
        self._final_message = final_message
        self._fail_mid_stream = fail_mid_stream
        self._fail_final = fail_final

    @property
    async def text_stream(self) -> AsyncIterator[str]:
        for delta in self._deltas:
            yield delta
        if self._fail_mid_stream is not None:
            raise self._fail_mid_stream

    async def get_final_message(self) -> FakeMessage:
        if self._fail_final is not None:
            raise self._fail_final
        return self._final_message


class FakeStreamManager:
    def __init__(self, stream: FakeSDKStream) -> None:
        self._stream = stream

    async def __aenter__(self) -> FakeSDKStream:
        return self._stream

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


class FailingStreamManager:
    """Raises on entry — simulates an SDK-level failure (auth, network, etc.)."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def __aenter__(self) -> FakeSDKStream:
        raise self._error

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


def simple_turn(deltas: list[str], final_message: FakeMessage) -> FakeSDKStream:
    return FakeSDKStream(deltas, final_message)


class FakeMessages:
    """Yields the next scripted turn on each call to `.stream(...)`, in order."""

    def __init__(self, turns: list[FakeSDKStream] | None = None) -> None:
        self._turns = list(turns or [])
        self.calls: list[dict[str, Any]] = []
        self._error: Exception | None = None

    def fail_next(self, error: Exception) -> None:
        self._error = error

    def stream(self, **kwargs: Any) -> Any:
        # `messages` is a mutable list the caller keeps appending to across the whole
        # tool-calling loop; snapshot it now so `self.calls[n]` reflects what was actually
        # sent at call time, not whatever it's mutated into by the time a test inspects it.
        snapshot = dict(kwargs)
        if "messages" in snapshot:
            snapshot["messages"] = list(snapshot["messages"])
        self.calls.append(snapshot)
        if self._error is not None:
            error, self._error = self._error, None
            return FailingStreamManager(error)
        return FakeStreamManager(self._turns.pop(0))


class FakeAnthropic:
    def __init__(self, turns: list[FakeSDKStream] | None = None) -> None:
        self.messages = FakeMessages(turns)
