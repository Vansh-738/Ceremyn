import pytest

from ceremyn.core.exceptions import ConfigurationError
from ceremyn.features.base import Feature
from ceremyn.features.context import FeatureContext
from ceremyn.features.models import FeatureScalar
from ceremyn.features.registry import FeatureRegistry, default_registry

EXPECTED_FEATURES = {
    "pcr",
    "open_interest",
    "oi_change",
    "max_pain",
    "iv_rank",
    "iv_percentile",
    "expected_move",
    "liquidity_score",
    "days_to_expiry",
    "time_to_expiry",
    "vwap",
    "atr_14",
    "ema_21",
    "rsi_14",
    "adx_14",
    "historical_volatility_20",
    "realized_volatility_20",
    "trend_strength",
    "market_regime",
}


class _Dummy(Feature):
    name = "dummy_feature"

    def compute(self, ctx: FeatureContext) -> FeatureScalar:
        return 1.0


class TestDefaultRegistry:
    def test_all_nineteen_features_registered(self) -> None:
        assert set(default_registry.available()) == EXPECTED_FEATURES
        assert len(EXPECTED_FEATURES) == 19

    def test_get_returns_feature(self) -> None:
        assert default_registry.get("pcr").name == "pcr"

    def test_unknown_feature_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="unknown feature"):
            default_registry.get("does_not_exist")


class TestFeatureRegistry:
    def test_add_and_get(self) -> None:
        registry = FeatureRegistry()
        registry.add(_Dummy())
        assert registry.get("dummy_feature").name == "dummy_feature"
        assert registry.available() == ("dummy_feature",)

    def test_duplicate_raises(self) -> None:
        registry = FeatureRegistry()
        registry.add(_Dummy())
        with pytest.raises(ConfigurationError, match="already registered"):
            registry.add(_Dummy())

    def test_all_features_sorted(self) -> None:
        registry = FeatureRegistry()

        class _A(Feature):
            name = "a_feature"

            def compute(self, ctx: FeatureContext) -> FeatureScalar:
                return 1.0

        registry.add(_Dummy())
        registry.add(_A())
        assert [f.name for f in registry.all_features()] == ["a_feature", "dummy_feature"]
