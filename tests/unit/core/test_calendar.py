from datetime import date, datetime

import pytest

from alphaquant.core.calendar import DEFAULT_EXPIRY_RULES, ExpiryFrequency, MarketCalendar
from alphaquant.core.exceptions import CalendarError
from alphaquant.core.timeutils import IST


@pytest.fixture
def cal() -> MarketCalendar:
    return MarketCalendar()


class TestTradingDays:
    def test_regular_weekday(self, cal: MarketCalendar) -> None:
        assert cal.is_trading_day(date(2025, 7, 14))  # Monday, no holiday

    def test_weekend(self, cal: MarketCalendar) -> None:
        assert not cal.is_trading_day(date(2025, 7, 12))  # Saturday
        assert not cal.is_trading_day(date(2025, 7, 13))  # Sunday

    def test_holiday(self, cal: MarketCalendar) -> None:
        assert not cal.is_trading_day(date(2025, 8, 15))  # Independence Day (Friday)

    def test_next_trading_day_skips_weekend_and_holiday(self, cal: MarketCalendar) -> None:
        # Thu Aug 14 -> Fri 15 is a holiday, Sat/Sun weekend -> Mon Aug 18.
        assert cal.next_trading_day(date(2025, 8, 14)) == date(2025, 8, 18)

    def test_previous_trading_day(self, cal: MarketCalendar) -> None:
        assert cal.previous_trading_day(date(2025, 8, 18)) == date(2025, 8, 14)

    def test_uncovered_year_raises_instead_of_guessing(self, cal: MarketCalendar) -> None:
        with pytest.raises(CalendarError, match="2023"):
            cal.is_trading_day(date(2023, 6, 1))


class TestMarketHours:
    def test_open_during_session(self, cal: MarketCalendar) -> None:
        assert cal.is_market_open(datetime(2025, 7, 14, 10, 0, tzinfo=IST))

    def test_session_boundaries(self, cal: MarketCalendar) -> None:
        assert cal.is_market_open(datetime(2025, 7, 14, 9, 15, tzinfo=IST))
        assert cal.is_market_open(datetime(2025, 7, 14, 15, 30, tzinfo=IST))
        assert not cal.is_market_open(datetime(2025, 7, 14, 9, 14, tzinfo=IST))
        assert not cal.is_market_open(datetime(2025, 7, 14, 15, 31, tzinfo=IST))

    def test_closed_on_holiday_even_during_hours(self, cal: MarketCalendar) -> None:
        assert not cal.is_market_open(datetime(2025, 8, 15, 10, 0, tzinfo=IST))

    def test_naive_datetime_rejected(self, cal: MarketCalendar) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            cal.is_market_open(datetime(2025, 7, 14, 10, 0))


class TestExpiries:
    def test_default_rules(self) -> None:
        assert DEFAULT_EXPIRY_RULES["NIFTY"].frequency is ExpiryFrequency.WEEKLY
        assert DEFAULT_EXPIRY_RULES["BANKNIFTY"].frequency is ExpiryFrequency.MONTHLY
        assert DEFAULT_EXPIRY_RULES["FINNIFTY"].frequency is ExpiryFrequency.MONTHLY
        assert DEFAULT_EXPIRY_RULES["MIDCPNIFTY"].frequency is ExpiryFrequency.MONTHLY

    def test_next_weekly_expiry_is_tuesday(self, cal: MarketCalendar) -> None:
        # From Wednesday Jul 9 2025, next NIFTY weekly expiry: Tue Jul 15.
        assert cal.next_expiry("NIFTY", date(2025, 7, 9)) == date(2025, 7, 15)

    def test_expiry_on_same_day(self, cal: MarketCalendar) -> None:
        assert cal.next_expiry("NIFTY", date(2025, 7, 15)) == date(2025, 7, 15)

    def test_holiday_expiry_moves_earlier(self, cal: MarketCalendar) -> None:
        # Tue Oct 21 2025 is Diwali Laxmi Pujan; that week's expiry is Mon Oct 20.
        assert cal.next_expiry("NIFTY", date(2025, 10, 18)) == date(2025, 10, 20)

    def test_passed_adjusted_expiry_rolls_to_next_week(self, cal: MarketCalendar) -> None:
        # On Tue Oct 21 the (adjusted) Oct 20 expiry is already gone -> Oct 28.
        assert cal.next_expiry("NIFTY", date(2025, 10, 21)) == date(2025, 10, 28)

    def test_monthly_expiry_last_tuesday(self, cal: MarketCalendar) -> None:
        assert cal.monthly_expiry("BANKNIFTY", 2025, 7) == date(2025, 7, 29)
        assert cal.monthly_expiry("BANKNIFTY", 2025, 12) == date(2025, 12, 30)

    def test_next_monthly_expiry_rolls_over_month(self, cal: MarketCalendar) -> None:
        # After October's monthly expiry (Oct 28), next is November's (Nov 25).
        assert cal.next_expiry("BANKNIFTY", date(2025, 10, 29)) == date(2025, 11, 25)

    def test_unknown_underlying_raises(self, cal: MarketCalendar) -> None:
        with pytest.raises(CalendarError, match="NIFTYNXT50"):
            cal.next_expiry("NIFTYNXT50", date(2025, 7, 14))
