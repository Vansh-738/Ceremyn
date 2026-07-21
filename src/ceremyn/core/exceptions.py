"""Application-level exception hierarchy.

Domain-rule errors live in `ceremyn.domain.errors` (the domain layer cannot
import this module). Everything here derives from CeremynError so callers
can catch platform errors without swallowing genuine bugs.
"""


class CeremynError(Exception):
    """Base for all application errors."""


class ConfigurationError(CeremynError):
    """Invalid or missing configuration."""


class DataError(CeremynError):
    """Market-data acquisition, parsing, or persistence failure."""


class CalendarError(CeremynError):
    """Market-calendar query outside the covered range, or invalid input."""


class BrokerError(CeremynError):
    """Broker API failure (auth, order placement, data fetch)."""


class RiskViolationError(CeremynError):
    """An order failed a risk-engine check."""

    def __init__(self, rule: str, reason: str) -> None:
        self.rule = rule
        self.reason = reason
        super().__init__(f"risk rule '{rule}' violated: {reason}")


class LiveTradingLockedError(CeremynError):
    """A live-trading action was attempted while any of the three gates is closed."""
