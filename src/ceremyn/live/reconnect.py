"""Reconnect policy and state."""

from pydantic import BaseModel, ConfigDict, Field

from ceremyn.live.exceptions import ReconnectFailedError


class ReconnectState(BaseModel):
    model_config = ConfigDict(frozen=True)

    attempts: int = Field(default=0, ge=0)
    is_reconnecting: bool = False


class ReconnectManager:
    def __init__(self, *, max_attempts: int = 5, base_delay_seconds: float = 1.0) -> None:
        self._max_attempts = max_attempts
        self._base_delay_seconds = base_delay_seconds
        self._state = ReconnectState()

    @property
    def state(self) -> ReconnectState:
        return self._state

    def begin(self) -> ReconnectState:
        attempts = self._state.attempts + 1
        if attempts > self._max_attempts:
            raise ReconnectFailedError("reconnect attempts exhausted")
        self._state = ReconnectState(attempts=attempts, is_reconnecting=True)
        return self._state

    def succeed(self) -> ReconnectState:
        self._state = ReconnectState()
        return self._state

    def fail(self) -> ReconnectState:
        if self._state.attempts >= self._max_attempts:
            raise ReconnectFailedError("reconnect attempts exhausted")
        self._state = ReconnectState(
            attempts=self._state.attempts,
            is_reconnecting=True,
        )
        return self._state

    def backoff_seconds(self) -> float:
        attempts = max(1, self._state.attempts)
        return float(self._base_delay_seconds * (2 ** (attempts - 1)))
