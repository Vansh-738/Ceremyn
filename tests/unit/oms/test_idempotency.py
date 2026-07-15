from uuid import uuid4

from alphaquant.oms import InMemoryIdempotencyStore


def test_idempotency_store_suppresses_duplicates() -> None:
    store = InMemoryIdempotencyStore()
    first_id = uuid4()
    second_id = uuid4()

    assert store.reserve("hash", first_id) is None
    assert store.reserve("hash", second_id) == first_id
    assert store.duplicate_count("hash") == 1


def test_seed_prepopulates_reservations_without_overwriting_existing() -> None:
    store = InMemoryIdempotencyStore()
    restored_id = uuid4()
    already_reserved_id = uuid4()
    conflicting_id = uuid4()

    store.reserve("already-reserved", already_reserved_id)
    store.seed([("restored", restored_id), ("already-reserved", conflicting_id)])

    # A newly-seeded hash is now reserved...
    assert store.reserve("restored", uuid4()) == restored_id
    # ...and seeding never clobbers a reservation made before restore ran.
    assert store.reserve("already-reserved", uuid4()) == already_reserved_id
