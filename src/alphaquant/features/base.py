"""The Feature ABC.

A Feature is a named, versioned, deterministic pure function of a FeatureContext.
Subclasses declare their input requirements so the engine can short-circuit to a
null value (rather than raising) when the context lacks the data — a missing input
is a normal condition, not an error.
"""

from abc import ABC, abstractmethod

from alphaquant.features.context import FeatureContext
from alphaquant.features.models import FeatureScalar


class Feature(ABC):
    #: Stable, unique feature name. Parameterized features encode their params
    #: (e.g. "ema_21") so distinct configurations never share a cache slot.
    name: str
    #: Semantic version of the computation; part of every cache key and FeatureSet.
    version: str = "1"
    #: True if the feature needs an option chain in the context.
    needs_chain: bool = False
    #: Minimum number of candles required (0 if the feature does not use candles).
    min_candles: int = 0

    def is_computable(self, ctx: FeatureContext) -> bool:
        if self.needs_chain and ctx.chain is None:
            return False
        return ctx.candle_count >= self.min_candles

    def evaluate(self, ctx: FeatureContext) -> FeatureScalar:
        """Return the feature value, or None when its inputs are unavailable."""
        if not self.is_computable(ctx):
            return None
        return self.compute(ctx)

    @abstractmethod
    def compute(self, ctx: FeatureContext) -> FeatureScalar:
        """Compute the value; called only when `is_computable` is True."""
