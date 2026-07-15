from alphaquant.llm.watchlist import InMemoryWatchlistStore


def test_empty_watchlist_for_unknown_session() -> None:
    store = InMemoryWatchlistStore()
    snapshot = store.list("s1")
    assert snapshot.session_id == "s1"
    assert snapshot.symbols == ()


def test_add_normalizes_and_returns_snapshot() -> None:
    store = InMemoryWatchlistStore()
    snapshot = store.add("s1", " nifty ")
    assert snapshot.symbols == ("NIFTY",)


def test_add_is_idempotent() -> None:
    store = InMemoryWatchlistStore()
    store.add("s1", "NIFTY")
    snapshot = store.add("s1", "nifty")
    assert snapshot.symbols == ("NIFTY",)


def test_add_multiple_symbols_sorted() -> None:
    store = InMemoryWatchlistStore()
    store.add("s1", "BANKNIFTY")
    snapshot = store.add("s1", "NIFTY")
    assert snapshot.symbols == ("BANKNIFTY", "NIFTY")


def test_remove_symbol() -> None:
    store = InMemoryWatchlistStore()
    store.add("s1", "NIFTY")
    store.add("s1", "BANKNIFTY")
    snapshot = store.remove("s1", "nifty")
    assert snapshot.symbols == ("BANKNIFTY",)


def test_remove_unknown_symbol_is_a_no_op() -> None:
    store = InMemoryWatchlistStore()
    store.add("s1", "NIFTY")
    snapshot = store.remove("s1", "FINNIFTY")
    assert snapshot.symbols == ("NIFTY",)


def test_remove_from_unknown_session_is_a_no_op() -> None:
    store = InMemoryWatchlistStore()
    snapshot = store.remove("unknown", "NIFTY")
    assert snapshot.symbols == ()


def test_sessions_are_isolated() -> None:
    store = InMemoryWatchlistStore()
    store.add("s1", "NIFTY")
    assert store.list("s2").symbols == ()
