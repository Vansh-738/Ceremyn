from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ceremyn.domain import Pattern, PatternDirection

TS = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)


def test_valid_pattern() -> None:
    pattern = Pattern(
        name="HAMMER",
        tradingsymbol="RELIANCE",
        detected_at=TS,
        direction=PatternDirection.BULLISH,
        source="candlestick",
    )
    assert pattern.name == "HAMMER"
    assert pattern.direction is PatternDirection.BULLISH


def test_naive_timestamp_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        Pattern(
            name="HAMMER",
            tradingsymbol="RELIANCE",
            detected_at=datetime(2026, 7, 14, 10, 0),  # naive
            direction=PatternDirection.BULLISH,
            source="candlestick",
        )


def test_frozen() -> None:
    pattern = Pattern(
        name="HAMMER",
        tradingsymbol="RELIANCE",
        detected_at=TS,
        direction=PatternDirection.BULLISH,
        source="candlestick",
    )
    with pytest.raises(ValidationError):
        pattern.name = "OTHER"  # type: ignore[misc]


def test_empty_name_rejected() -> None:
    with pytest.raises(ValidationError):
        Pattern(
            name="",
            tradingsymbol="RELIANCE",
            detected_at=TS,
            direction=PatternDirection.BULLISH,
            source="candlestick",
        )
