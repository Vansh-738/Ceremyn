"""Minimal in-process event bus.

Events are plain objects dispatched by exact type. Handlers may be sync or
async. A failing handler does not prevent the remaining handlers from running;
failures are logged and re-raised together after dispatch so bugs stay loud.
"""

import inspect
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import structlog

E = TypeVar("E")

Handler = Callable[[Any], Awaitable[None] | None]

logger = structlog.get_logger(__name__)


class EventBus:
    def __init__(self) -> None:
        self._handlers: defaultdict[type[Any], list[Handler]] = defaultdict(list)

    def subscribe(
        self, event_type: type[E], handler: Callable[[E], Awaitable[None] | None]
    ) -> None:
        self._handlers[event_type].append(handler)

    def unsubscribe(
        self, event_type: type[E], handler: Callable[[E], Awaitable[None] | None]
    ) -> None:
        self._handlers[event_type].remove(handler)

    async def publish(self, event: object) -> None:
        errors: list[Exception] = []
        for handler in list(self._handlers.get(type(event), [])):
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:  # isolate handlers; re-raised as a group below
                logger.error(
                    "event_handler_failed",
                    event_type=type(event).__name__,
                    handler=getattr(handler, "__qualname__", repr(handler)),
                    exc_info=exc,
                )
                errors.append(exc)
        if errors:
            raise ExceptionGroup("event handler failure(s)", errors)
