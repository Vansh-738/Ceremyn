"""Session-scoped conversation memory — never persisted, matching "conversation memory only
within the current session" literally: resets to empty on every process restart, exactly like
`execution.gate.LiveTradingGate`'s armed state. Bounded per-session history plus LRU session
eviction so a long-running process can't grow this unboundedly.
"""

from collections import OrderedDict, deque
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from alphaquant.core.timeutils import now_utc

Role = Literal["user", "assistant"]


class ConversationMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Role
    content: str
    at: datetime = Field(default_factory=now_utc)


class ConversationStore(Protocol):
    def append(self, session_id: str, message: ConversationMessage) -> None: ...
    def history(self, session_id: str) -> tuple[ConversationMessage, ...]: ...
    def clear(self, session_id: str) -> None: ...


class InMemoryConversationStore:
    """Bounded per-session history; oldest session evicted once the session cap is hit."""

    def __init__(self, *, max_messages_per_session: int = 50, max_sessions: int = 500) -> None:
        self._max_messages = max_messages_per_session
        self._max_sessions = max_sessions
        self._sessions: OrderedDict[str, deque[ConversationMessage]] = OrderedDict()

    def append(self, session_id: str, message: ConversationMessage) -> None:
        if session_id not in self._sessions:
            if len(self._sessions) >= self._max_sessions:
                self._sessions.popitem(last=False)  # evict the least-recently-used session
            self._sessions[session_id] = deque(maxlen=self._max_messages)
        else:
            self._sessions.move_to_end(session_id)
        self._sessions[session_id].append(message)

    def history(self, session_id: str) -> tuple[ConversationMessage, ...]:
        return tuple(self._sessions.get(session_id, ()))

    def clear(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
