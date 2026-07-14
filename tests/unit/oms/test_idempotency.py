from uuid import uuid4

from alphaquant.oms import InMemoryIdempotencyStore


def test_idempotency_store_suppresses_duplicates() -> None:
    store = InMemoryIdempotencyStore()
    first_id = uuid4()
    second_id = uuid4()

    assert store.reserve("hash", first_id) is None
    assert store.reserve("hash", second_id) == first_id
    assert store.duplicate_count("hash") == 1
