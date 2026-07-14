"""Feature versioning and cache-key derivation.

Every cache key and the FeatureSet's ``feature_set_version`` fold in each feature's
declared ``version``, so bumping a computation's version invalidates only that
feature's cache entries and changes the overall set version deterministically.
"""

import hashlib
from collections.abc import Iterable

from alphaquant.features.base import Feature
from alphaquant.features.context import FeatureContext


def cache_key(feature: Feature, ctx: FeatureContext) -> str:
    """Identity of one feature computation: name, version, and context fingerprint."""
    return f"{feature.name}@{feature.version}:{ctx.fingerprint}"


def feature_set_version(features: Iterable[Feature]) -> str:
    """Deterministic version over a set of features (sorted name@version digest)."""
    parts = sorted(f"{feature.name}@{feature.version}" for feature in features)
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return digest[:16]
