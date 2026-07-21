"""LLM-specific exceptions."""

from ceremyn.core.exceptions import CeremynError


class LLMError(CeremynError):
    """Base error for LLM assistant operations."""


class LLMProviderError(LLMError):
    """The underlying Claude API call failed (auth, network, rate limit)."""


class LLMToolError(LLMError):
    """A tool the model requested could not be resolved or executed."""


class LLMSessionError(LLMError):
    """An operation referenced a conversation session that doesn't exist."""
