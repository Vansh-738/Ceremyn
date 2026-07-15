"""`GatedBrokerAdapter`: the only `BrokerAdapter` OMS is ever wired with.

All gate-awareness lives here — `oms/engine.py` and `oms/router.py` never know a gate
exists, and never see more than one broker (`BrokerRouter` always routes to a single fixed
`default_broker`, so dynamic live/fallback switching has to happen inside one adapter, not
at the router). Every call resolves `gate.permits_live_trading(settings)` and delegates to
the real broker or the safe fallback; the real broker is built lazily, exactly once, via
`live_factory` — never touched at all unless routing actually goes live, so a missing Kite
API key never breaks OMS construction in non-live environments.
"""

from collections.abc import Callable, Sequence

from alphaquant.config import Settings
from alphaquant.execution.gate import LiveTradingGate
from alphaquant.oms.broker import (
    BrokerAdapter,
    BrokerCancelResult,
    BrokerCapabilities,
    BrokerCashSnapshot,
    BrokerExecutionReport,
    BrokerOrderSnapshot,
    BrokerPositionSnapshot,
    BrokerReplaceResult,
    BrokerSubmissionResult,
)
from alphaquant.oms.orders import CancelOrderCommand, ReplaceOrderCommand, SubmitOrderCommand


class GatedBrokerAdapter:
    """Routes every call to the live broker (only when all three gates pass) or the
    safe fallback (otherwise). No caller outside this class can tell the difference."""

    def __init__(
        self,
        *,
        live_factory: Callable[[], BrokerAdapter],
        fallback: BrokerAdapter,
        gate: LiveTradingGate,
        settings: Settings,
        name: str = "execution",
    ) -> None:
        self._live_factory = live_factory
        self._live: BrokerAdapter | None = None
        self._fallback = fallback
        self._gate = gate
        self._settings = settings
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> BrokerCapabilities:
        return self._active().capabilities

    def submit(self, command: SubmitOrderCommand) -> BrokerSubmissionResult:
        broker, live = self._resolve()
        self._gate.record_routing(live=live)
        return broker.submit(command)

    def cancel(self, command: CancelOrderCommand) -> BrokerCancelResult:
        return self._active().cancel(command)

    def replace(self, command: ReplaceOrderCommand) -> BrokerReplaceResult:
        return self._active().replace(command)

    def lookup_order(self, command: SubmitOrderCommand) -> BrokerOrderSnapshot | None:
        return self._active().lookup_order(command)

    def fetch_orders(self) -> Sequence[BrokerOrderSnapshot]:
        return self._active().fetch_orders()

    def fetch_fills(self) -> Sequence[BrokerExecutionReport]:
        return self._active().fetch_fills()

    def fetch_positions(self) -> Sequence[BrokerPositionSnapshot]:
        return self._active().fetch_positions()

    def fetch_cash(self) -> BrokerCashSnapshot:
        return self._active().fetch_cash()

    # -- internal -------------------------------------------------------------

    def _resolve(self) -> tuple[BrokerAdapter, bool]:
        if self._gate.permits_live_trading(self._settings):
            return self._live_adapter(), True
        return self._fallback, False

    def _active(self) -> BrokerAdapter:
        return self._resolve()[0]

    def _live_adapter(self) -> BrokerAdapter:
        if self._live is None:
            self._live = self._live_factory()
        return self._live
