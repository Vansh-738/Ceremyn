"""Application-level exception hierarchy.

Domain-rule errors live in `alphaquant.domain.errors` (the domain layer cannot
import this module). Everything here derives from AlphaQuantError so callers
can catch platform errors without swallowing genuine bugs.
"""


class AlphaQuantError(Exception):
    """Base for all application errors."""


class ConfigurationError(AlphaQuantError):
    """Invalid or missing configuration."""


class DataError(AlphaQuantError):
    """Market-data acquisition, parsing, or persistence failure."""


class CalendarError(AlphaQuantError):
    """Market-calendar query outside the covered range, or invalid input."""


class BrokerError(AlphaQuantError):
    """Broker API failure (auth, order placement, data fetch)."""


class RiskViolationError(AlphaQuantError):
    """An order failed a risk-engine check."""

    def __init__(self, rule: str, reason: str) -> None:
        self.rule = rule
        self.reason = reason
        super().__init__(f"risk rule '{rule}' violated: {reason}")


class LiveTradingLockedError(AlphaQuantError):
    """A live-trading action was attempted while any of the three gates is closed."""
