"""Option-chain features.

These reuse the existing chain analytics and pricing kernels — PCR and OI totals from
the ``OptionChainSnapshot`` domain model, and ``iv_rank`` / ``iv_percentile`` /
``max_pain`` from ``data.services.chain_analytics`` — so the maths lives in one place.
"""

import math

from ceremyn.core.timeutils import to_ist
from ceremyn.data.services.chain_analytics import (
    ChainAnalyticsService,
    expiry_moment,
    iv_percentile,
    iv_rank,
    max_pain,
)
from ceremyn.data.services.pricing import time_to_expiry_years
from ceremyn.features.base import Feature
from ceremyn.features.context import FeatureContext
from ceremyn.features.models import FeatureScalar
from ceremyn.features.registry import register


def _current_atm_iv(ctx: FeatureContext) -> float | None:
    """Latest ATM IV: prefer the supplied history, else derive from an enriched chain."""
    if ctx.iv_history:
        return ctx.iv_history[-1]
    if ctx.chain is not None:
        return ChainAnalyticsService(ctx.risk_free_rate).atm_iv(ctx.chain)
    return None


@register
class PutCallRatio(Feature):
    name = "pcr"
    needs_chain = True

    def compute(self, ctx: FeatureContext) -> FeatureScalar:
        assert ctx.chain is not None
        return ctx.chain.pcr


@register
class OpenInterestTotal(Feature):
    name = "open_interest"
    needs_chain = True

    def compute(self, ctx: FeatureContext) -> FeatureScalar:
        assert ctx.chain is not None
        return ctx.chain.total_call_oi + ctx.chain.total_put_oi


@register
class OpenInterestChange(Feature):
    name = "oi_change"
    needs_chain = True

    def compute(self, ctx: FeatureContext) -> FeatureScalar:
        assert ctx.chain is not None
        if ctx.previous_chain is None:
            return None
        current = ctx.chain.total_call_oi + ctx.chain.total_put_oi
        previous = ctx.previous_chain.total_call_oi + ctx.previous_chain.total_put_oi
        return current - previous


@register
class MaxPainStrike(Feature):
    name = "max_pain"
    needs_chain = True

    def compute(self, ctx: FeatureContext) -> FeatureScalar:
        assert ctx.chain is not None
        return float(max_pain(ctx.chain))


@register
class IVRank(Feature):
    name = "iv_rank"

    def compute(self, ctx: FeatureContext) -> FeatureScalar:
        if not ctx.iv_history:
            return None
        return iv_rank(ctx.iv_history[-1], list(ctx.iv_history))


@register
class IVPercentile(Feature):
    name = "iv_percentile"

    def compute(self, ctx: FeatureContext) -> FeatureScalar:
        if not ctx.iv_history:
            return None
        return iv_percentile(ctx.iv_history[-1], list(ctx.iv_history))


@register
class ExpectedMove(Feature):
    name = "expected_move"
    needs_chain = True

    def compute(self, ctx: FeatureContext) -> FeatureScalar:
        assert ctx.chain is not None
        atm_iv = _current_atm_iv(ctx)
        if atm_iv is None:
            return None
        tte = time_to_expiry_years((expiry_moment(ctx.chain) - ctx.as_of).total_seconds())
        if tte <= 0:
            return 0.0
        return float(ctx.chain.spot) * atm_iv * math.sqrt(tte)


@register
class LiquidityScore(Feature):
    """Blended 0..100 liquidity from spread tightness, open interest, and volume."""

    name = "liquidity_score"
    needs_chain = True

    SPREAD_CAP = 0.5  # relative spread at/above which spread score is 0
    OI_REFERENCE = 1_000_000.0
    VOLUME_REFERENCE = 100_000.0

    def compute(self, ctx: FeatureContext) -> FeatureScalar:
        assert ctx.chain is not None
        chain = ctx.chain
        spreads: list[float] = []
        total_volume = 0.0
        for entry in chain.entries:
            quote = entry.quote
            if quote is None:
                continue
            total_volume += quote.volume
            mid = quote.mid
            if mid is not None and mid > 0 and quote.spread is not None:
                spreads.append(float(quote.spread) / float(mid))
        avg_spread = sum(spreads) / len(spreads) if spreads else self.SPREAD_CAP
        spread_score = max(0.0, 1.0 - avg_spread / self.SPREAD_CAP)
        total_oi = chain.total_call_oi + chain.total_put_oi
        depth_score = min(1.0, total_oi / self.OI_REFERENCE)
        volume_score = min(1.0, total_volume / self.VOLUME_REFERENCE)
        return round(100.0 * (0.5 * spread_score + 0.25 * depth_score + 0.25 * volume_score), 4)


@register
class DaysToExpiry(Feature):
    name = "days_to_expiry"
    needs_chain = True

    def compute(self, ctx: FeatureContext) -> FeatureScalar:
        assert ctx.chain is not None
        return (ctx.chain.expiry - to_ist(ctx.as_of).date()).days


@register
class TimeToExpiry(Feature):
    """Time to expiry in years (ACT/365)."""

    name = "time_to_expiry"
    needs_chain = True

    def compute(self, ctx: FeatureContext) -> FeatureScalar:
        assert ctx.chain is not None
        return time_to_expiry_years((expiry_moment(ctx.chain) - ctx.as_of).total_seconds())
