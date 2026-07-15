"""AlphaQuant LLM Assistant — read-only, analysis/explanation only.

Never places, modifies, or cancels an order. `llm` never imports `alphaquant.risk` or
`alphaquant.execution` (import-linter enforced), and transitively cannot reach `oms`,
`paper`, `live`, `research`, `backtest`, or `dashboard.backend` either — every one of those
packages imports `alphaquant.risk` somewhere. All platform data flows in through the
Protocols in `llm.providers`, satisfied by adapters built at the composition root (`api/`).
"""

from alphaquant.llm.assistant import Assistant, StreamEvent
from alphaquant.llm.client import ClaudeClient
from alphaquant.llm.conversation import (
    ConversationMessage,
    ConversationStore,
    InMemoryConversationStore,
)
from alphaquant.llm.exceptions import LLMError, LLMProviderError, LLMSessionError, LLMToolError
from alphaquant.llm.providers import DashboardReader, ExperimentDetailReader, RecapReader
from alphaquant.llm.snapshots import ExperimentDetailBrief, RecapBrief, StrategyCatalogEntry
from alphaquant.llm.watchlist import InMemoryWatchlistStore, WatchlistSnapshot, WatchlistStore

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
