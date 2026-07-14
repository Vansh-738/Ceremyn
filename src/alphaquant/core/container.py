"""Composition root.

The Container is the single place where the object graph is assembled. Modules
never instantiate each other's collaborators; they receive them from here
(directly, or via FastAPI dependencies that delegate to the container).
Grows as milestones add providers, repositories, engines, and brokers.
"""

from functools import cached_property

from alphaquant.config import Settings
from alphaquant.core.calendar import MarketCalendar
from alphaquant.core.events import EventBus


class Container:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @cached_property
    def event_bus(self) -> EventBus:
        return EventBus()

    @cached_property
    def calendar(self) -> MarketCalendar:
        return MarketCalendar()
