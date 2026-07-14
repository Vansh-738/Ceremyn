from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from alphaquant.domain import Candle, TimeFrame
from tests.unit.domain.conftest import make_quote


class TestQuote:
    def test_mid_and_spread(self) -> None:
        quote = make_quote(bid="149.5", ask="150.5")
        assert quote.mid == Decimal(150)
        assert quote.spread == Decimal(1)

    def test_mid_none_when_one_sided(self) -> None:
        assert make_quote(ask=None).mid is None
        assert make_quote(bid=None).spread is None

    def test_naive_timestamp_rejected(self) -> None:
        from alphaquant.domain import Quote

        with pytest.raises(ValidationError, match="timezone-aware"):
            Quote(
                tradingsymbol="X",
                timestamp=datetime(2025, 7, 14, 10, 0),  # naive
                last_price=Decimal(1),
            )


def make_candle(**overrides: object) -> Candle:
    defaults: dict[str, object] = {
        "tradingsymbol": "NIFTY 50",
        "timeframe": TimeFrame.DAY,
        "timestamp": datetime(2025, 7, 14, 9, 15, tzinfo=UTC),
        "open": Decimal(24500),
        "high": Decimal(24600),
        "low": Decimal(24400),
        "close": Decimal(24550),
    }
    defaults.update(overrides)
    return Candle.model_validate(defaults)


class TestCandle:
    def test_valid_candle(self) -> None:
        assert make_candle().close == Decimal(24550)

    def test_high_below_low_rejected(self) -> None:
        with pytest.raises(ValidationError, match="high < low"):
            make_candle(high=Decimal(24300))

    def test_open_outside_range_rejected(self) -> None:
        with pytest.raises(ValidationError, match="open outside"):
            make_candle(open=Decimal(24700))

    def test_close_outside_range_rejected(self) -> None:
        with pytest.raises(ValidationError, match="close outside"):
            make_candle(close=Decimal(24399))
