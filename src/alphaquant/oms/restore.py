"""Rebuild in-memory OMS state from a durable journal after a restart.

Pure and side-effect-free: reads whatever `JournalStore.entries()` returns and folds
it into the shape `OrderManagementEngine` needs. Never touches a broker or the
filesystem directly — that's the store's job, not this module's.
"""

from dataclasses import dataclass, field
from uuid import UUID

from alphaquant.oms.journal import JournalEntryKind, JournalStore
from alphaquant.oms.orders import OMSOrder


@dataclass(frozen=True)
class RestoredOMSState:
    orders: dict[UUID, OMSOrder] = field(default_factory=dict)
    external_index: dict[str, UUID] = field(default_factory=dict)
    children: dict[UUID, list[UUID]] = field(default_factory=dict)
    idempotency_seed: tuple[tuple[str, UUID], ...] = ()


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
