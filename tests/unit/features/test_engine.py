import pytest

from alphaquant.core.exceptions import ConfigurationError
from alphaquant.features.base import Feature
from alphaquant.features.cache import InMemoryFeatureCache
from alphaquant.features.context import FeatureContext
from alphaquant.features.engine import FeatureEngine, default_validator
from alphaquant.features.models import FeatureScalar
from alphaquant.features.registry import FeatureRegistry
from alphaquant.features.validation import Bounds, FeatureValidationError
from tests.unit.features.conftest import make_chain, make_context


class CountingFeature(Feature):
    name = "counting"

    def __init__(self) -> None:
        self.calls = 0

    def compute(self, ctx: FeatureContext) -> FeatureScalar:
        self.calls += 1
        return 42.0


class BadFeature(Feature):
    name = "bad_rsi"

    def compute(self, ctx: FeatureContext) -> FeatureScalar:
        return 500.0  # out of the [0, 100] bound registered below


class TestComputeAll:
    def test_bundles_all_registry_features(self, full_context: FeatureContext) -> None:
        fs = FeatureEngine().compute_all(full_context)
        assert len(fs.values) == 19
        assert fs.context_fingerprint == full_context.fingerprint
        assert fs.numeric("pcr") is not None
        assert fs.get("market_regime") is not None

    def test_feature_set_version_stable(self, full_context: FeatureContext) -> None:
        a = FeatureEngine().compute_all(full_context)
        b = FeatureEngine().compute_all(full_context)
        assert a.feature_set_version == b.feature_set_version


class TestComputeOnce:
    def test_cache_hit_avoids_recompute(self) -> None:
        registry = FeatureRegistry()
        feature = CountingFeature()
        registry.add(feature)
        cache = InMemoryFeatureCache()
        engine = FeatureEngine(registry=registry, cache=cache, validator=default_validator())
        ctx = make_context(chain=make_chain())

        engine.compute("counting", ctx)
        engine.compute("counting", ctx)
        engine.compute_all(ctx)
        assert feature.calls == 1  # computed exactly once for this context
        assert cache.hits == 2

    def test_new_context_recomputes(self) -> None:
        registry = FeatureRegistry()
        feature = CountingFeature()
        registry.add(feature)
        engine = FeatureEngine(registry=registry, cache=InMemoryFeatureCache())
        engine.compute("counting", make_context(chain=make_chain(spread="1")))
        engine.compute("counting", make_context(chain=make_chain(spread="2")))
        assert feature.calls == 2  # different fingerprints


class TestValidationIntegration:
    def test_invalid_value_raises_through_engine(self) -> None:
        registry = FeatureRegistry()
        registry.add(BadFeature())
        validator = default_validator()
        validator.set_constraint("bad_rsi", Bounds(0.0, 100.0))
        engine = FeatureEngine(registry=registry, validator=validator)
        with pytest.raises(FeatureValidationError):
            engine.compute("bad_rsi", make_context(chain=make_chain()))


class TestErrors:
    def test_compute_unknown_feature(self) -> None:
        with pytest.raises(ConfigurationError):
            FeatureEngine().compute("nope", make_context())

    def test_compute_many_subset(self, full_context: FeatureContext) -> None:
        fs = FeatureEngine().compute_many(["pcr", "rsi_14"], full_context)
        assert set(fs.values) == {"pcr", "rsi_14"}


class TestDefaultValidator:
    def test_constraints_present(self) -> None:
        validator = default_validator()
        for name in ("iv_rank", "rsi_14", "market_regime", "pcr", "time_to_expiry"):
            assert validator.has_constraint(name)
