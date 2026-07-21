from ceremyn.data.services.chain_analytics import iv_percentile, iv_rank, max_pain
from ceremyn.features.context import FeatureContext
from ceremyn.features.models import FeatureScalar
from ceremyn.features.registry import default_registry
from tests.unit.features.conftest import make_chain, make_context


def value(name: str, ctx: FeatureContext) -> FeatureScalar:
    return default_registry.get(name).evaluate(ctx)


class TestChainReuse:
    def test_pcr_matches_domain(self) -> None:
        chain = make_chain()
        ctx = make_context(chain=chain)
        assert value("pcr", ctx) == chain.pcr

    def test_open_interest_total(self) -> None:
        chain = make_chain()
        ctx = make_context(chain=chain)
        assert value("open_interest", ctx) == chain.total_call_oi + chain.total_put_oi

    def test_max_pain_matches_analytics(self) -> None:
        chain = make_chain()
        ctx = make_context(chain=chain)
        assert value("max_pain", ctx) == float(max_pain(chain))

    def test_features_need_chain_return_none_without_one(self) -> None:
        ctx = make_context(chain=None)
        for name in ("pcr", "open_interest", "max_pain", "expected_move", "liquidity_score"):
            assert value(name, ctx) is None


class TestOIChange:
    def test_delta_vs_previous(self) -> None:
        prev = make_chain(strikes=[(24000, 100, 100, "180")])
        curr = make_chain(strikes=[(24000, 150, 200, "180")])
        ctx = make_context(chain=curr, previous_chain=prev)
        assert value("oi_change", ctx) == (150 + 200) - (100 + 100)

    def test_none_without_previous(self) -> None:
        ctx = make_context(chain=make_chain())
        assert value("oi_change", ctx) is None


class TestIVHistoryFeatures:
    def test_iv_rank_matches_analytics(self) -> None:
        history = tuple(0.10 + 0.01 * i for i in range(10))
        ctx = make_context(iv_history=history)
        assert value("iv_rank", ctx) == iv_rank(history[-1], list(history))

    def test_iv_percentile_matches_analytics(self) -> None:
        history = tuple(0.10 + 0.01 * i for i in range(10))
        ctx = make_context(iv_history=history)
        assert value("iv_percentile", ctx) == iv_percentile(history[-1], list(history))

    def test_none_without_history(self) -> None:
        ctx = make_context(iv_history=())
        assert value("iv_rank", ctx) is None
        assert value("iv_percentile", ctx) is None


class TestExpectedMove:
    def test_positive_with_iv_and_chain(self) -> None:
        ctx = make_context(chain=make_chain(), iv_history=(0.15,))
        move = value("expected_move", ctx)
        assert isinstance(move, float) and move > 0.0

    def test_none_without_iv(self) -> None:
        # Chain present but no IV history and unenriched chain -> no ATM IV.
        ctx = make_context(chain=make_chain(), iv_history=())
        assert value("expected_move", ctx) is None


class TestLiquidityScore:
    def test_bounded_0_100(self) -> None:
        score = value("liquidity_score", make_context(chain=make_chain()))
        assert isinstance(score, float) and 0.0 <= score <= 100.0

    def test_tighter_spread_scores_higher(self) -> None:
        tight = value("liquidity_score", make_context(chain=make_chain(spread="0.5")))
        wide = value("liquidity_score", make_context(chain=make_chain(spread="20")))
        assert isinstance(tight, float) and isinstance(wide, float)
        assert tight > wide


class TestExpiryFeatures:
    def test_days_to_expiry(self) -> None:
        ctx = make_context(chain=make_chain())
        # AS_OF is 2026-07-14, expiry 2026-07-30 -> 16 days.
        assert value("days_to_expiry", ctx) == 16

    def test_time_to_expiry_positive(self) -> None:
        tte = value("time_to_expiry", make_context(chain=make_chain()))
        assert isinstance(tte, float) and tte > 0.0

    def test_time_to_expiry_matches_days_scale(self) -> None:
        tte = value("time_to_expiry", make_context(chain=make_chain()))
        assert isinstance(tte, float)
        # ~16 days to a 15:30 IST expiry -> a little under 16/365 years.
        assert 0.03 < tte < 0.05
