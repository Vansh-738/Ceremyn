"""Real `BrokerAdapter` for Zerodha Kite Connect — the live order-placement path.

Symmetric with `data.providers.kite.KiteProvider` (market data): the `kiteconnect` client is
injected for testability; `KiteBroker.from_settings` builds the real one. AlphaQuant's own
`Side`/`OrderType`/`ProductType`/`Exchange` enums already use Kite-native string values, so
mapping a command is direct `.value` translation, not a lookup table.

This class has no awareness of the live-trading gates — it is only ever reached through
`execution.gated_broker.GatedBrokerAdapter`, which decides whether a call should land here at
all. Kite's synchronous SDK is called directly (unlike `KiteProvider`, OMS itself is fully
synchronous, so no `asyncio.to_thread` is needed).
"""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from alphaquant.config import Settings
from alphaquant.core.exceptions import BrokerError
from alphaquant.core.timeutils import IST, now_utc
from alphaquant.oms.broker import (
    BrokerCancelResult,
    BrokerCapabilities,
    BrokerCashSnapshot,
    BrokerExecutionReport,
    BrokerOrderSnapshot,
    BrokerOrderStatus,
    BrokerPositionSnapshot,
    BrokerReplaceResult,
    BrokerSubmissionResult,
)
from alphaquant.oms.exceptions import OMSNonRetryableBrokerError, OMSRetryableError
from alphaquant.oms.orders import CancelOrderCommand, ReplaceOrderCommand, SubmitOrderCommand

_KITE_ORDER_STATUS = {
    "OPEN": BrokerOrderStatus.OPEN,
    "OPEN PENDING": BrokerOrderStatus.OPEN,
    "VALIDATION PENDING": BrokerOrderStatus.OPEN,
    "PUT ORDER REQ RECEIVED": BrokerOrderStatus.OPEN,
    "MODIFY PENDING": BrokerOrderStatus.OPEN,
    "MODIFY VALIDATION PENDING": BrokerOrderStatus.OPEN,
    "TRIGGER PENDING": BrokerOrderStatus.OPEN,
    "COMPLETE": BrokerOrderStatus.FILLED,
    "CANCELLED": BrokerOrderStatus.CANCELLED,
    "CANCELLED AMO": BrokerOrderStatus.CANCELLED,
    "REJECTED": BrokerOrderStatus.REJECTED,
}


def _parse_timestamp(value: Any) -> datetime:
    """Kite returns naive datetimes/strings in IST; storage/domain requires tz-aware."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=IST)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return now_utc()
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=IST)
    return now_utc()


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, "", 0):
        return None
    return Decimal(str(value))


class KiteBroker:
    """Order placement/management via `kiteconnect.KiteConnect`."""

    def __init__(self, kite: Any, *, name: str = "kite", variety: str = "regular") -> None:
        self._kite = kite
        self._name = name
        self._variety = variety

    @classmethod
    def from_settings(cls, settings: Settings) -> "KiteBroker":
        from kiteconnect import KiteConnect

        if not settings.kite.api_key:
            raise BrokerError("ALPHAQUANT_KITE__API_KEY is not configured")
        kite = KiteConnect(api_key=settings.kite.api_key)
        access_token = settings.kite.access_token.get_secret_value()
        if access_token:
            kite.set_access_token(access_token)
        return cls(kite)

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> BrokerCapabilities:
        return BrokerCapabilities(
            supports_replace=True, supports_brackets=False, supports_tags=True
        )

    def submit(self, command: SubmitOrderCommand) -> BrokerSubmissionResult:
        order = command.order
        order_id = self._call(
            self._kite.place_order,
            variety=self._variety,
            exchange=order.contract.exchange.value,
            tradingsymbol=order.contract.tradingsymbol,
            transaction_type=order.side.value,
            quantity=order.quantity,
            product=order.product.value,
            order_type=order.order_type.value,
            price=float(order.limit_price) if order.limit_price is not None else None,
            trigger_price=float(order.trigger_price) if order.trigger_price is not None else None,
            # The tag is the idempotency key, not a label: Kite stores it server-side and
            # returns it on every `orders()` call, so `lookup_order` can recover it from
            # Kite itself even when this process never locally recorded the submission
            # (e.g. the call below raised before returning). Truncated to Kite's ~20-char
            # tag limit — unverified against a live/sandbox account, same caveat class as
            # the rest of this class (see PROJECT_CONTEXT.md).
            tag=command.request_hash[:20],
        )
        external_id = str(order_id)
        return BrokerSubmissionResult(
            external_order_id=external_id, broker_timestamp=command.requested_at
        )

    def cancel(self, command: CancelOrderCommand) -> BrokerCancelResult:
        if command.external_order_id is None:
            return BrokerCancelResult(
                accepted=False,
                broker_timestamp=command.requested_at,
                message="no external order id",
            )
        self._call(
            self._kite.cancel_order, variety=self._variety, order_id=command.external_order_id
        )
        return BrokerCancelResult(accepted=True, broker_timestamp=command.requested_at)

    def replace(self, command: ReplaceOrderCommand) -> BrokerReplaceResult:
        if command.external_order_id is None:
            return BrokerReplaceResult(
                accepted=False,
                broker_timestamp=command.requested_at,
                message="no external order id",
            )
        self._call(
            self._kite.modify_order,
            variety=self._variety,
            order_id=command.external_order_id,
            price=float(command.new_limit_price) if command.new_limit_price is not None else None,
            trigger_price=(
                float(command.new_trigger_price) if command.new_trigger_price is not None else None
            ),
        )
        return BrokerReplaceResult(accepted=True, broker_timestamp=command.requested_at)

    def lookup_order(self, command: SubmitOrderCommand) -> BrokerOrderSnapshot | None:
        # Queries Kite's own order book rather than any local bookkeeping, so this works
        # even when `submit()` raised before this process recorded anything (the exact
        # "timeout after Kite already accepted the order" case retries must detect) and
        # even after a process restart. `request_hash` alone is sufficient: it already
        # incorporates `correlation_id` (see `OrderPlanner.request_hash`), so no separate
        # correlation match is needed.
        for snapshot in self.fetch_orders():
            if snapshot.request_hash == command.request_hash:
                return snapshot
        return None

    def fetch_orders(self) -> Sequence[BrokerOrderSnapshot]:
        return tuple(self._to_snapshot(entry) for entry in self._call(self._kite.orders))

    def fetch_fills(self) -> Sequence[BrokerExecutionReport]:
        return tuple(self._to_report(entry) for entry in self._call(self._kite.trades))

    def fetch_positions(self) -> Sequence[BrokerPositionSnapshot]:
        raw = self._call(self._kite.positions)
        net = raw.get("net", []) if isinstance(raw, dict) else []
        return tuple(
            BrokerPositionSnapshot(
                tradingsymbol=str(entry["tradingsymbol"]),
                quantity=int(entry.get("quantity", 0)),
                realized_pnl=Decimal(str(entry.get("realised", 0))),
                unrealized_pnl=Decimal(str(entry.get("unrealised", 0))),
            )
            for entry in net
        )

    def fetch_cash(self) -> BrokerCashSnapshot:
        raw = self._call(self._kite.margins)
        equity = raw.get("equity", {}) if isinstance(raw, dict) else {}
        available = equity.get("available", {}) if isinstance(equity, dict) else {}
        return BrokerCashSnapshot(available_cash=Decimal(str(available.get("live_balance", 0))))

    # -- internal -------------------------------------------------------------

    def _call(self, fn: Any, **kwargs: Any) -> Any:
        try:
            return fn(**kwargs)
        except Exception as exc:
            raise self._wrap(exc) from exc

    def _wrap(self, exc: Exception) -> Exception:
        from kiteconnect.exceptions import (
            InputException,
            OrderException,
            PermissionException,
            TokenException,
        )

        if isinstance(exc, InputException | OrderException | PermissionException | TokenException):
            return OMSNonRetryableBrokerError(str(exc))
        return OMSRetryableError(str(exc))

    def _to_snapshot(self, entry: dict[str, Any]) -> BrokerOrderSnapshot:
        external_id = str(entry["order_id"])
        return BrokerOrderSnapshot(
            external_order_id=external_id,
            status=_KITE_ORDER_STATUS.get(str(entry.get("status", "")), BrokerOrderStatus.OPEN),
            broker_timestamp=_parse_timestamp(entry.get("order_timestamp")),
            filled_quantity=int(entry.get("filled_quantity") or 0),
            remaining_quantity=int(entry.get("pending_quantity") or 0),
            average_price=_decimal_or_none(entry.get("average_price")),
            # Recovered straight from Kite's own response — no local bookkeeping needed.
            request_hash=str(entry.get("tag") or "") or None,
            message=str(entry.get("status_message") or ""),
        )

    def _to_report(self, entry: dict[str, Any]) -> BrokerExecutionReport:
        trade_id = entry.get("trade_id")
        return BrokerExecutionReport(
            external_order_id=str(entry["order_id"]),
            status=BrokerOrderStatus.FILLED,
            broker_timestamp=_parse_timestamp(entry.get("fill_timestamp")),
            fill_id=str(trade_id) if trade_id else None,
            last_fill_quantity=int(entry.get("quantity") or 0),
            fill_price=_decimal_or_none(entry.get("average_price")),
        )
