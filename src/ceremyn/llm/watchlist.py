"""Session-scoped watchlist — a simple list of symbols the user cares about, remembered for
the assistant's own reference. Not a trading concept: adding or removing a symbol here never
touches an order, position, or broker — same risk level as conversation history. Same lifetime
discipline too (session-only, in-memory, resets on restart).
"""

from typing import Protocol

from pydantic import BaseModel, ConfigDict


class WatchlistSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    symbols: tuple[str, ...] = ()


class WatchlistStore(Protocol):
    def add(self, session_id: str, symbol: str) -> WatchlistSnapshot: ...
    def remove(self, session_id: str, symbol: str) -> WatchlistSnapshot: ...
    def list(self, session_id: str) -> WatchlistSnapshot: ...


class InMemoryWatchlistStore:
    def __init__(self) -> None:
        self._symbols: dict[str, set[str]] = {}

    def add(self, session_id: str, symbol: str) -> WatchlistSnapshot:
        normalized = symbol.strip().upper()
        self._symbols.setdefault(session_id, set()).add(normalized)
        return self.list(session_id)

    def remove(self, session_id: str, symbol: str) -> WatchlistSnapshot:
        normalized = symbol.strip().upper()
        self._symbols.get(session_id, set()).discard(normalized)
        return self.list(session_id)

    def list(self, session_id: str) -> WatchlistSnapshot:
        symbols = tuple(sorted(self._symbols.get(session_id, ())))
        return WatchlistSnapshot(session_id=session_id, symbols=symbols)
