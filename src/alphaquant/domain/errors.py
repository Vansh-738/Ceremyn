"""Domain-level errors.

The domain layer may not import from other alphaquant packages, so the errors
it raises are defined here. Application-level errors live in core.exceptions.
"""


class DomainError(Exception):
    """Base for all domain-rule violations."""


class OrderTransitionError(DomainError):
    """Raised on an illegal order-status transition."""
