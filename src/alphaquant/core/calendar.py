"""NSE market calendar: trading days, session hours, and expiry rules.

Expiry regime (post-September 2025, per SEBI's one-weekly-expiry-per-exchange
framework): NSE index expiries fall on Tuesday — NIFTY keeps a weekly expiry,
BANKNIFTY is monthly-only (last Tuesday). Rules are data, not code: pass a
different `ExpiryRule` mapping to model other regimes or historical periods.
"""

from datetime import date, datetime, time, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from alphaquant.core.exceptions import CalendarError
from alphaquant.core.nse_holidays import NSE_HOLIDAYS
from alphaquant.core.timeutils import to_ist

TUESDAY = 1  # datetime.weekday() numbering (Monday == 0)


class ExpiryFrequency(StrEnum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class ExpiryRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    weekday: int = Field(ge=0, le=6)
    frequency: ExpiryFrequency


DEFAULT_EXPIRY_RULES: dict[str, ExpiryRule] = {
    "NIFTY": ExpiryRule(weekday=TUESDAY, frequency=ExpiryFrequency.WEEKLY),
    "BANKNIFTY": ExpiryRule(weekday=TUESDAY, frequency=ExpiryFrequency.MONTHLY),
    "FINNIFTY": ExpiryRule(weekday=TUESDAY, frequency=ExpiryFrequency.MONTHLY),
    "MIDCPNIFTY": ExpiryRule(weekday=TUESDAY, frequency=ExpiryFrequency.MONTHLY),
}


class MarketCalendar:
    """Trading-day and expiry arithmetic for NSE."""

    OPEN = time(9, 15)
    CLOSE = time(15, 30)

    def __init__(
        self,
        holidays: dict[int, frozenset[date]] = NSE_HOLIDAYS,
        expiry_rules: dict[str, ExpiryRule] = DEFAULT_EXPIRY_RULES,
    ) -> None:
        self._holidays = holidays
        self._expiry_rules = expiry_rules

    # -- trading days ---------------------------------------------------------

    def is_holiday(self, day: date) -> bool:
        year_holidays = self._holidays.get(day.year)
        if year_holidays is None:
            raise CalendarError(
                f"no holiday data for {day.year}; covered years: "
                f"{sorted(self._holidays)} — refusing to guess"
            )
        return day in year_holidays

    def is_trading_day(self, day: date) -> bool:
        return day.weekday() < 5 and not self.is_holiday(day)

    def next_trading_day(self, day: date) -> date:
        candidate = day + timedelta(days=1)
        while not self.is_trading_day(candidate):
            candidate += timedelta(days=1)
        return candidate

    def previous_trading_day(self, day: date) -> date:
        candidate = day - timedelta(days=1)
        while not self.is_trading_day(candidate):
            candidate -= timedelta(days=1)
        return candidate

    def is_market_open(self, at: datetime) -> bool:
        """True during the regular session (09:15 to 15:30 IST, inclusive)."""
        local = to_ist(at)
        return self.is_trading_day(local.date()) and self.OPEN <= local.time() <= self.CLOSE

    # -- expiries -------------------------------------------------------------

    def expiry_rule(self, underlying: str) -> ExpiryRule:
        try:
            return self._expiry_rules[underlying]
        except KeyError as exc:
            raise CalendarError(f"no expiry rule configured for {underlying!r}") from exc

    def adjust_expiry(self, expiry: date) -> date:
        """Exchange convention: an expiry falling on a holiday moves *earlier*."""
        while not self.is_trading_day(expiry):
            expiry -= timedelta(days=1)
        return expiry

    def next_expiry(self, underlying: str, on_or_after: date) -> date:
        """The nearest expiry date on or after `on_or_after`."""
        rule = self.expiry_rule(underlying)
        if rule.frequency is ExpiryFrequency.WEEKLY:
            return self._next_weekly_expiry(rule.weekday, on_or_after)
        return self._next_monthly_expiry(rule.weekday, on_or_after)

    def monthly_expiry(self, underlying: str, year: int, month: int) -> date:
        """The (holiday-adjusted) monthly expiry: last rule-weekday of the month."""
        rule = self.expiry_rule(underlying)
        return self.adjust_expiry(_last_weekday_of_month(year, month, rule.weekday))

    def _next_weekly_expiry(self, weekday: int, on_or_after: date) -> date:
        candidate = _next_weekday(weekday, on_or_after)
        adjusted = self.adjust_expiry(candidate)
        # A holiday shift can pull the expiry before `on_or_after` (i.e. it has
        # already passed) — in that case the relevant expiry is next week's.
        while adjusted < on_or_after:
            candidate = _next_weekday(weekday, candidate + timedelta(days=1))
            adjusted = self.adjust_expiry(candidate)
        return adjusted

    def _next_monthly_expiry(self, weekday: int, on_or_after: date) -> date:
        year, month = on_or_after.year, on_or_after.month
        while True:
            adjusted = self.adjust_expiry(_last_weekday_of_month(year, month, weekday))
            if adjusted >= on_or_after:
                return adjusted
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def _next_weekday(weekday: int, on_or_after: date) -> date:
    return on_or_after + timedelta(days=(weekday - on_or_after.weekday()) % 7)


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    next_month_first = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    last_day = next_month_first - timedelta(days=1)
    return last_day - timedelta(days=(last_day.weekday() - weekday) % 7)
