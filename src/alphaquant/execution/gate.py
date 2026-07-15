"""Gate #3 of live trading: a runtime arming token, submitted after startup.

Gates #1 (`ALPHAQUANT_TRADING_MODE=live`) and #2 (`ALPHAQUANT_LIVE_TRADING_ENABLED=true`)
live in `Settings`/env vars (see `Settings.effective_mode`). Gate #3 is deliberately kept out
of configuration entirely: `LiveTradingGate` holds only in-memory, runtime state that resets
to disarmed on every process restart, so a restart is always a return to the safe state.

Arming itself requires gates #1-#2 to already be open — arming is the last, deliberate step,
not a way to bypass the other two (`arm()` raises the existing `LiveTradingLockedError`
otherwise). A bounded audit trail records every arm/disarm/routing decision.
"""

from collections import deque
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from alphaquant.config import Settings, TradingMode
from alphaquant.core.exceptions import LiveTradingLockedError
from alphaquant.core.timeutils import now_utc

GateEventKind = Literal["armed", "disarmed", "routed_live", "routed_fallback"]


class GateEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: GateEventKind
    at: datetime
    reason: str = ""


class LiveTradingGate:
    """Runtime-only armed state plus a bounded audit trail. Never touches `Settings`
    for its own state — only reads it to validate gates #1-#2 when asked to arm."""

    def __init__(self, *, history_size: int = 200) -> None:
        self._armed = False
        self._armed_at: datetime | None = None
        self._reason = ""
        self._history: deque[GateEvent] = deque(maxlen=history_size)

    @property
    def is_armed(self) -> bool:
        return self._armed

    @property
    def armed_at(self) -> datetime | None:
        return self._armed_at

    @property
    def reason(self) -> str:
        return self._reason

    def arm(self, *, settings: Settings, reason: str, at: datetime | None = None) -> None:
        """Set gate #3. Requires gates #1-#2 already open; never a way to skip them."""
        if not (settings.trading_mode is TradingMode.LIVE and settings.live_trading_enabled):
            raise LiveTradingLockedError(
                "cannot arm: ALPHAQUANT_TRADING_MODE=live and "
                "ALPHAQUANT_LIVE_TRADING_ENABLED=true must already be set"
            )
        moment = at or now_utc()
        self._armed = True
        self._armed_at = moment
        self._reason = reason
        self._history.append(GateEvent(kind="armed", at=moment, reason=reason))

    def disarm(self, *, reason: str = "", at: datetime | None = None) -> None:
        """Always succeeds — making the system safer is never gated."""
        moment = at or now_utc()
        self._armed = False
        self._armed_at = None
        self._reason = ""
        self._history.append(GateEvent(kind="disarmed", at=moment, reason=reason))

    def permits_live_trading(self, settings: Settings) -> bool:
        """All three gates: mode=live, the config flag, and this runtime arm state."""
        return (
            settings.effective_mode is TradingMode.LIVE
            and settings.live_trading_enabled
            and self._armed
        )

    def record_routing(self, *, live: bool, at: datetime | None = None) -> None:
        kind: GateEventKind = "routed_live" if live else "routed_fallback"
        self._history.append(GateEvent(kind=kind, at=at or now_utc()))

    def history(self) -> tuple[GateEvent, ...]:
        return tuple(self._history)
