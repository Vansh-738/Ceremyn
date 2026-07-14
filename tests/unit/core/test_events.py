from dataclasses import dataclass

import pytest

from alphaquant.core.events import EventBus


@dataclass
class OrderFilled:
    order_id: str


@dataclass
class Unrelated:
    pass


async def test_sync_and_async_handlers_both_receive() -> None:
    bus = EventBus()
    received: list[str] = []

    def sync_handler(event: OrderFilled) -> None:
        received.append(f"sync:{event.order_id}")

    async def async_handler(event: OrderFilled) -> None:
        received.append(f"async:{event.order_id}")

    bus.subscribe(OrderFilled, sync_handler)
    bus.subscribe(OrderFilled, async_handler)
    await bus.publish(OrderFilled(order_id="o1"))

    assert received == ["sync:o1", "async:o1"]


async def test_dispatch_is_type_scoped() -> None:
    bus = EventBus()
    received: list[object] = []
    bus.subscribe(OrderFilled, received.append)

    await bus.publish(Unrelated())
    assert received == []


async def test_failing_handler_does_not_starve_others() -> None:
    bus = EventBus()
    received: list[str] = []

    def broken(event: OrderFilled) -> None:
        raise RuntimeError("boom")

    bus.subscribe(OrderFilled, broken)
    bus.subscribe(OrderFilled, lambda e: received.append(e.order_id))

    with pytest.raises(ExceptionGroup) as exc_info:
        await bus.publish(OrderFilled(order_id="o2"))

    assert received == ["o2"]  # second handler still ran
    assert len(exc_info.value.exceptions) == 1


async def test_unsubscribe() -> None:
    bus = EventBus()
    received: list[object] = []
    bus.subscribe(OrderFilled, received.append)
    bus.unsubscribe(OrderFilled, received.append)

    await bus.publish(OrderFilled(order_id="o3"))
    assert received == []
