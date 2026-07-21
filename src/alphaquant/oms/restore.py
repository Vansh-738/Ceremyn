"""Rebuild in-memory OMS state from a durable journal after a restart.

Pure and side-effect-free: reads whatever `JournalStore.entries()` returns and folds
it into the shape `OrderManagementEngine` needs. Never touches a broker or the
filesystem directly — that's the store's job, not this module's.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from alphaquant.domain import Fill, Order
from alphaquant.oms.journal import JournalEntryKind, JournalStore
from alphaquant.oms.orders import OMSOrder


@dataclass(frozen=True)
class RestoredOMSState:
    orders: dict[UUID, OMSOrder] = field(default_factory=dict)
    external_index: dict[str, UUID] = field(default_factory=dict)
    children: dict[UUID, list[UUID]] = field(default_factory=dict)
    idempotency_seed: tuple[tuple[str, UUID], ...] = ()


@dataclass(frozen=True)
class ReplayFill:
    """One historical fill, resolved against the order it belongs to -- everything
    `OMSPortfolio.apply_fill` needs to replay it exactly as it happened live."""

    fill: Fill
    order: Order
    strategy_id: str


def rebuild_portfolio_fills(
    store: JournalStore, orders: dict[UUID, OMSOrder]
) -> tuple[ReplayFill, ...]:
    """Every `FILL` entry, in journal (chronological) order, paired with the order it
    belongs to. The journal only ever appends, so replaying these in file order through
    `OMSPortfolio.apply_fill` reconstructs cash/positions/realized_pnl exactly as they
    stood before a restart -- without this, a restart doesn't just forget order
    bookkeeping, it silently erases every consequence of every fill that ever happened,
    even though the fills themselves were durably journaled all along.
    """
    order_by_domain_id = {oms_order.order.id: oms_order.order for oms_order in orders.values()}
    replays: list[ReplayFill] = []
    for entry in store.entries():
        if entry.kind is not JournalEntryKind.FILL:
            continue
        payload = entry.payload
        order_id = UUID(str(payload["order_id"]))
        order = order_by_domain_id.get(order_id)
        if order is None:  # order itself missing from the restored set; skip defensively
            continue
        replays.append(
            ReplayFill(
                fill=Fill(
                    order_id=order_id,
                    quantity=int(payload["quantity"]),
                    price=Decimal(str(payload["price"])),
                    timestamp=entry.timestamp,
                ),
                order=order,
                strategy_id=str(payload["strategy_id"]),
            )
        )
    return tuple(replays)


def rebuild_oms_state(store: JournalStore) -> RestoredOMSState:
    """Fold every `ORDER_SNAPSHOT` entry into the latest known state per order.

    The journal is append-only, so later entries for the same `oms_order_id`
    supersede earlier ones — a plain last-write-wins fold over file order is correct.
    """
    latest: dict[UUID, OMSOrder] = {}
    for entry in store.entries():
        if entry.kind is not JournalEntryKind.ORDER_SNAPSHOT:
            continue
        order = OMSOrder.model_validate(entry.payload)
        latest[order.oms_order_id] = order

    external_index: dict[str, UUID] = {}
    children: dict[UUID, list[UUID]] = {}
    idempotency_seed: list[tuple[str, UUID]] = []
    for order in latest.values():
        if order.external_order_id is not None:
            external_index[order.external_order_id] = order.oms_order_id
        if order.parent_order_id is not None:
            children.setdefault(order.parent_order_id, []).append(order.oms_order_id)
        idempotency_seed.append((order.request_hash, order.oms_order_id))

    return RestoredOMSState(
        orders=latest,
        external_index=external_index,
        children=children,
        idempotency_seed=tuple(idempotency_seed),
    )
