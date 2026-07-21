from datetime import datetime

import pytest
from pydantic import ValidationError

from ceremyn.features.context import FeatureContext
from tests.unit.features.conftest import make_chain, make_context, trending_closes


class TestFingerprint:
    def test_deterministic(self) -> None:
        a = make_context(chain=make_chain(), iv_history=(0.1, 0.2), closes=trending_closes(10))
        b = make_context(chain=make_chain(), iv_history=(0.1, 0.2), closes=trending_closes(10))
        assert a.fingerprint == b.fingerprint
        assert len(a.fingerprint) == 64

    def test_changes_with_iv_history(self) -> None:
        a = make_context(iv_history=(0.1, 0.2))
        b = make_context(iv_history=(0.1, 0.3))
        assert a.fingerprint != b.fingerprint

    def test_changes_with_chain(self) -> None:
        a = make_context(chain=make_chain(strikes=[(24000, 100, 100, "180")]))
        b = make_context(chain=make_chain(strikes=[(24000, 200, 100, "180")]))
        assert a.fingerprint != b.fingerprint

    def test_changes_with_candles(self) -> None:
        a = make_context(closes=trending_closes(10))
        b = make_context(closes=trending_closes(11))
        assert a.fingerprint != b.fingerprint

    def test_changes_with_rate(self) -> None:
        chain = make_chain()
        a = FeatureContext(
            as_of=make_context().as_of, underlying="NIFTY", chain=chain, risk_free_rate=0.05
        )
        b = FeatureContext(
            as_of=make_context().as_of, underlying="NIFTY", chain=chain, risk_free_rate=0.07
        )
        assert a.fingerprint != b.fingerprint


class TestViews:
    def test_candle_views(self) -> None:
        ctx = make_context(closes=[100.0, 101.0, 102.0])
        assert ctx.candle_count == 3
        assert ctx.closes == [100.0, 101.0, 102.0]
        assert len(ctx.highs) == 3 and len(ctx.lows) == 3 and len(ctx.volumes) == 3

    def test_empty_candles(self) -> None:
        ctx = make_context()
        assert ctx.candle_count == 0
        assert ctx.closes == []


def test_naive_as_of_rejected() -> None:
    with pytest.raises(ValidationError):
        FeatureContext(as_of=datetime(2026, 7, 14, 6, 0), underlying="NIFTY")  # naive
