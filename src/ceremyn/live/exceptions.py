"""Live market-data exception hierarchy."""

from ceremyn.core.exceptions import ConfigurationError, DataError


class LiveDataError(DataError):
    """Base error for the live market-data engine."""


class LiveConfigurationError(ConfigurationError):
    """Invalid live-market-data configuration."""


class SubscriptionError(LiveDataError):
    """A subscription or resubscription action failed."""


class TickValidationError(LiveDataError):
    """A raw market tick failed validation."""


class HeartbeatTimeoutError(LiveDataError):
    """The data stream stopped heartbeating within the configured timeout."""


class ReconnectFailedError(LiveDataError):
    """Reconnect attempts were exhausted without a healthy stream."""
