from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ceremyn.domain import AssetClass, Opportunity, PatternDirection

TS = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)


def make_opportunity(**overrides: object) -> Opportunity:
    defaults: dict[str, object] = {
        "tradingsymbol": "RELIANCE",
        "asset_class": AssetClass.EQUITY,
        "pattern_name": "HAMMER",
        "direction": PatternDirection.BULLISH,
        "detected_at": TS,
        "source": "candlestick",
        "occurrences": 15,
        "hit_rate": 0.6,
        "average_forward_return_pct": 2.0,
        "forward_days": 5,
    }
    defaults.update(overrides)
    return Opportunity.model_validate(defaults)


def test_valid_opportunity() -> None:
    opp = make_opportunity()
    assert opp.tradingsymbol == "RELIANCE"
    assert opp.asset_class is AssetClass.EQUITY


def test_edge_score_is_hit_rate_times_abs_return() -> None:
    opp = make_opportunity(hit_rate=0.6, average_forward_return_pct=-2.5)
    assert opp.edge_score == pytest.approx(0.6 * 2.5)


def test_naive_timestamp_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        make_opportunity(detected_at=datetime(2026, 7, 14, 10, 0))


def test_hit_rate_out_of_range_rejected() -> None:
    with pytest.raises(ValidationError):
        make_opportunity(hit_rate=1.5)


def test_frozen() -> None:
    opp = make_opportunity()
    with pytest.raises(ValidationError):
        opp.tradingsymbol = "OTHER"  # type: ignore[misc]
