"""Timezone helpers.

Convention (see CLAUDE.md): market logic in IST, storage/logs in UTC, and every
datetime in the system is timezone-aware — naive datetimes are treated as bugs.
"""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now_utc() -> datetime:
    return datetime.now(UTC)


def now_ist() -> datetime:
    return datetime.now(IST)


def to_ist(value: datetime) -> datetime:
    """Convert an aware datetime to IST; reject naive input."""
    if value.tzinfo is None:
        raise ValueError("naive datetime; all datetimes must be timezone-aware")
    return value.astimezone(IST)
