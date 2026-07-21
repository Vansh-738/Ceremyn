"""Ceremyn LLM Assistant — read-only, analysis/explanation only.

Never places, modifies, or cancels an order. `llm` never imports `ceremyn.risk` or
`ceremyn.execution` (import-linter enforced), and transitively cannot reach `oms`,
`paper`, `live`, `research`, `backtest`, or `dashboard.backend` either — every one of those
packages imports `ceremyn.risk` somewhere. All platform data flows in through the
Protocols in `llm.providers`, satisfied by adapters built at the composition root (`api/`).
"""

from ceremyn.llm.assistant import Assistant, StreamEvent
from ceremyn.llm.client import ClaudeClient
from ceremyn.llm.conversation import (
    ConversationMessage,
    ConversationStore,
    InMemoryConversationStore,
)
from ceremyn.llm.exceptions import LLMError, LLMProviderError, LLMSessionError, LLMToolError
from ceremyn.llm.providers import DashboardReader, ExperimentDetailReader, RecapReader
from ceremyn.llm.snapshots import ExperimentDetailBrief, RecapBrief, StrategyCatalogEntry
from ceremyn.llm.watchlist import InMemoryWatchlistStore, WatchlistSnapshot, WatchlistStore

__all__ = [
    "Assistant",
    "ClaudeClient",
    "ConversationMessage",
    "ConversationStore",
    "DashboardReader",
    "ExperimentDetailBrief",
    "ExperimentDetailReader",
    "InMemoryConversationStore",
    "InMemoryWatchlistStore",
    "LLMError",
    "LLMProviderError",
    "LLMSessionError",
    "LLMToolError",
    "RecapBrief",
    "RecapReader",
    "StrategyCatalogEntry",
    "StreamEvent",
    "WatchlistSnapshot",
    "WatchlistStore",
]
