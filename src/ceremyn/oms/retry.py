"""Retry classification and backoff policy."""

from pydantic import BaseModel, ConfigDict, Field

from ceremyn.oms.exceptions import OMSRetryableError


class RetryDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    should_retry: bool
    delay_seconds: float = Field(default=0.0, ge=0)
    reason: str = ""


class RetryPolicy:
    def __init__(self, *, max_attempts: int = 3, base_delay_seconds: float = 0.25) -> None:
        self.max_attempts = max_attempts
        self.base_delay_seconds = base_delay_seconds

    def decide(self, error: Exception, *, attempt: int) -> RetryDecision:
        if not isinstance(error, OMSRetryableError):
            return RetryDecision(should_retry=False, reason=str(error))
        if attempt >= self.max_attempts:
            return RetryDecision(should_retry=False, reason="retry attempts exhausted")
        return RetryDecision(
            should_retry=True,
            delay_seconds=float(self.base_delay_seconds * (2 ** (attempt - 1))),
            reason=str(error),
        )
