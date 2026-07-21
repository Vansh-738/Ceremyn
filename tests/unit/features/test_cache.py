from datetime import UTC, datetime

from ceremyn.features.cache import FeatureCache, InMemoryFeatureCache
from ceremyn.features.models import FeatureValue

AS_OF = datetime(2026, 7, 14, 6, 0, tzinfo=UTC)


def value(name: str = "pcr") -> FeatureValue:
    return FeatureValue(name=name, version="1", value=1.0, as_of=AS_OF)


class TestInMemoryCache:
    def test_set_get_roundtrip(self) -> None:
        cache = InMemoryFeatureCache()
        cache.set("k", value())
        assert cache.get("k") is not None
        assert cache.hits == 1

    def test_miss_counts(self) -> None:
        cache = InMemoryFeatureCache()
        assert cache.get("absent") is None
        assert cache.misses == 1
        assert cache.hits == 0

    def test_len_and_clear(self) -> None:
        cache = InMemoryFeatureCache()
        cache.set("a", value("a"))
        cache.set("b", value("b"))
        assert len(cache) == 2
        cache.clear()
        assert len(cache) == 0
        assert cache.hits == 0 and cache.misses == 0

    def test_satisfies_protocol(self) -> None:
        cache: FeatureCache = InMemoryFeatureCache()
        assert isinstance(cache, FeatureCache)
