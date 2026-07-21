"""Composition-root-only read accessors over completed engine modules.

Each class here fully delegates to its superclass and adds a pure, side-effect-free way to
read state the dashboard needs — no algorithm changes. This lives outside `live`/`risk` so
those completed milestone packages stay untouched.
"""

from collections import deque
from datetime import datetime

from ceremyn.config import RiskSettings, Settings
from ceremyn.domain import PortfolioSnapshot, Signal
from ceremyn.live.heartbeat import HeartbeatMonitor, HeartbeatState
from ceremyn.risk import RiskDecision, RiskEngine
from ceremyn.risk.rules import RiskRule


class ReadableHeartbeatMonitor(HeartbeatMonitor):
    """Adds a `.state` read accessor, mirroring `ReconnectManager.state`."""

    @property
    def state(self) -> HeartbeatState:
        return self._state


class ObservableRiskEngine(RiskEngine):
    """Records every `RiskDecision` it evaluates, bounded to the most recent entries."""

    def __init__(
        self,
        configuration: RiskSettings | Settings,
        *,
        rules: tuple[RiskRule, ...] | None = None,
        history_size: int = 50,
    ) -> None:
        super().__init__(configuration, rules=rules)
        self._history: deque[RiskDecision] = deque(maxlen=history_size)

    def evaluate(
        self,
        portfolio: PortfolioSnapshot,
        signal: Signal,
        *,
        evaluated_at: datetime | None = None,
    ) -> RiskDecision:
        decision = super().evaluate(portfolio, signal, evaluated_at=evaluated_at)
        self._history.append(decision)
        return decision

    def recent_decisions(self) -> tuple[RiskDecision, ...]:
        return tuple(self._history)
