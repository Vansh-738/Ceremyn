from ceremyn.features.base import Feature
from ceremyn.features.context import FeatureContext
from ceremyn.features.models import FeatureScalar
from ceremyn.features.versioning import cache_key, feature_set_version
from tests.unit.features.conftest import make_chain, make_context


class _Feat(Feature):
    def __init__(self, name: str, version: str) -> None:
        self.name = name
        self.version = version

    def compute(self, ctx: FeatureContext) -> FeatureScalar:  # pragma: no cover - not called
        return None


class TestCacheKey:
    def test_format(self) -> None:
        ctx = make_context(chain=make_chain())
        key = cache_key(_Feat("pcr", "2"), ctx)
        assert key == f"pcr@2:{ctx.fingerprint}"

    def test_version_changes_key(self) -> None:
        ctx = make_context(chain=make_chain())
        assert cache_key(_Feat("pcr", "1"), ctx) != cache_key(_Feat("pcr", "2"), ctx)


class TestFeatureSetVersion:
    def test_deterministic_and_order_independent(self) -> None:
        a = feature_set_version([_Feat("x", "1"), _Feat("y", "1")])
        b = feature_set_version([_Feat("y", "1"), _Feat("x", "1")])
        assert a == b
        assert len(a) == 16

    def test_changes_with_version_bump(self) -> None:
        base = feature_set_version([_Feat("x", "1")])
        bumped = feature_set_version([_Feat("x", "2")])
        assert base != bumped

    def test_changes_with_membership(self) -> None:
        assert feature_set_version([_Feat("x", "1")]) != feature_set_version(
            [_Feat("x", "1"), _Feat("y", "1")]
        )
