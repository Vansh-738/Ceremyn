"""Feature cache: the mechanism that computes each feature exactly once.

``FeatureCache`` is the protocol the engine codes against; ``InMemoryFeatureCache``
is the default (a dict keyed by the ``name@version:fingerprint`` cache key). Because
the key is a content fingerprint, an identical context resolves to a cache hit and the
feature is never recomputed. A Redis-backed cache can implement the same protocol later.
"""

from typing import Protocol, runtime_checkable

from alphaquant.features.models import FeatureValue


@runtime_checkable
class FeatureCache(Protocol):
    def get(self, key: str) -> FeatureValue | None: ...

    def set(self, key: str, value: FeatureValue) -> None: ...

    def clear(self) -> None: ...


class InMemoryFeatureCache:
    def __init__(self) -> None:
        self._store: dict[str, FeatureValue] = {}
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> FeatureValue | None:
        found = self._store.get(key)
        if found is None:
            self.misses += 1
        else:
            self.hits += 1
        return found

    def set(self, key: str, value: FeatureValue) -> None:
        self._store[key] = value

    def clear(self) -> None:
        self._store.clear()
        self.hits = 0
        self.misses = 0

    def __len__(self) -> int:
        return len(self._store)
