"""OMS-specific exceptions."""

from alphaquant.core.exceptions import AlphaQuantError


class OMSError(AlphaQuantError):
    """Base error for OMS operations."""


class OMSValidationError(OMSError):
    """A command, intent, or plan failed validation."""


class OMSStateError(OMSError):
    """An event would produce an illegal OMS state transition."""


class OMSDuplicateRequestError(OMSError):
    """A duplicate order request was suppressed."""


class OMSRiskRejectedError(OMSError):
    """The risk engine rejected the signal before OMS routing."""


class OMSKillSwitchActiveError(OMSError):
    """New order submissions are blocked by the OMS kill switch."""


class OMSBrokerCapabilityError(OMSError):
    """The selected broker cannot support the requested execution behavior."""


class OMSRetryableError(OMSError):
    """A retryable broker or transport failure."""


class OMSNonRetryableBrokerError(OMSError):
    """A non-retryable broker failure."""
