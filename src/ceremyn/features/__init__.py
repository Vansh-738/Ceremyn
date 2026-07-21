"""Ceremyn Feature Store.

The one place every reusable market feature is computed — exactly once, cached,
versioned, deterministic, and reusable. Raw option chains and underlying candles go
in via a ``FeatureContext``; an immutable ``FeatureSet`` comes out. Downstream
consumers (research, backtest, paper, live) read Features rather than recomputing
analytics ad hoc.

This package is self-contained and additive: it reuses the existing chain analytics
and pricing kernels but modifies no other module. Importing it registers the 19
default features.
"""

from ceremyn.features import chain_features, price_features  # noqa: F401  (register defaults)
from ceremyn.features.base import Feature
from ceremyn.features.cache import FeatureCache, InMemoryFeatureCache
from ceremyn.features.context import FeatureContext
from ceremyn.features.engine import FeatureEngine
from ceremyn.features.models import FeatureSet, FeatureValue
from ceremyn.features.price_features import MarketRegime
from ceremyn.features.registry import FeatureRegistry, default_registry, register
from ceremyn.features.validation import FeatureValidationError, FeatureValidator
from ceremyn.features.versioning import cache_key, feature_set_version

__all__ = [
    "Feature",
    "FeatureCache",
    "FeatureContext",
    "FeatureEngine",
    "FeatureRegistry",
    "FeatureSet",
    "FeatureValidationError",
    "FeatureValidator",
    "FeatureValue",
    "InMemoryFeatureCache",
    "MarketRegime",
    "cache_key",
    "default_registry",
    "feature_set_version",
    "register",
]
