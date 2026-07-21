"""FeatureEngine: compute features exactly once, cached, validated, and versioned.

The engine resolves a feature from the registry, checks the cache by
``name@version:context_fingerprint``, and only computes on a miss — so within a
context every feature is computed at most once. Every value is validated against its
declared constraint before it is cached or returned. ``compute_all`` bundles the whole
registry into an immutable ``FeatureSet``.
"""

import structlog

from ceremyn.features.base import Feature
from ceremyn.features.cache import FeatureCache, InMemoryFeatureCache
from ceremyn.features.context import FeatureContext
from ceremyn.features.models import FeatureSet, FeatureValue
from ceremyn.features.registry import FeatureRegistry, default_registry
from ceremyn.features.validation import Bounds, Categorical, FeatureValidator
from ceremyn.features.versioning import cache_key, feature_set_version

logger = structlog.get_logger(__name__)


def default_validator() -> FeatureValidator:
    """Output constraints for the built-in features."""
    from ceremyn.features.price_features import MarketRegime

    validator = FeatureValidator()
    percent = Bounds(0.0, 100.0)
    non_negative = Bounds(low=0.0)
    for name in (
        "iv_rank",
        "iv_percentile",
        "rsi_14",
        "adx_14",
        "liquidity_score",
        "trend_strength",
    ):
        validator.set_constraint(name, percent)
    for name in (
        "pcr",
        "open_interest",
        "max_pain",
        "expected_move",
        "vwap",
        "atr_14",
        "ema_21",
        "historical_volatility_20",
        "realized_volatility_20",
        "time_to_expiry",
    ):
        validator.set_constraint(name, non_negative)
    validator.set_constraint("market_regime", Categorical(m.value for m in MarketRegime))
    return validator


class FeatureEngine:
    def __init__(
        self,
        registry: FeatureRegistry | None = None,
        cache: FeatureCache | None = None,
        validator: FeatureValidator | None = None,
    ) -> None:
        # Use `is not None` (not `or`): an empty InMemoryFeatureCache is falsy
        # because it defines __len__, so `cache or ...` would silently discard it.
        self.registry = registry if registry is not None else default_registry
        self.cache = cache if cache is not None else InMemoryFeatureCache()
        self.validator = validator if validator is not None else default_validator()

    def compute(self, name: str, ctx: FeatureContext) -> FeatureValue:
        feature = self.registry.get(name)
        return self._compute_feature(feature, ctx)

    def compute_many(self, names: list[str], ctx: FeatureContext) -> FeatureSet:
        features = [self.registry.get(name) for name in names]
        return self._bundle(features, ctx)

    def compute_all(self, ctx: FeatureContext) -> FeatureSet:
        return self._bundle(list(self.registry.all_features()), ctx)

    def _compute_feature(self, feature: Feature, ctx: FeatureContext) -> FeatureValue:
        key = cache_key(feature, ctx)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        raw = feature.evaluate(ctx)
        value = FeatureValue(
            name=feature.name,
            version=feature.version,
            value=raw,
            as_of=ctx.as_of,
        )
        self.validator.validate(value)
        self.cache.set(key, value)
        return value

    def _bundle(self, features: list[Feature], ctx: FeatureContext) -> FeatureSet:
        values = {feature.name: self._compute_feature(feature, ctx) for feature in features}
        return FeatureSet(
            as_of=ctx.as_of,
            underlying=ctx.underlying,
            feature_set_version=feature_set_version(features),
            context_fingerprint=ctx.fingerprint,
            values=values,
        )
