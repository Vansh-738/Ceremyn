from alphaquant.config import Settings
from alphaquant.core.calendar import MarketCalendar
from alphaquant.core.container import Container
from alphaquant.core.events import EventBus


def make_container() -> Container:
    return Container(Settings(_env_file=None))  # type: ignore[call-arg]


def test_container_provides_singletons() -> None:
    container = make_container()
    assert container.event_bus is container.event_bus
    assert container.calendar is container.calendar


def test_container_wiring_types() -> None:
    container = make_container()
    assert isinstance(container.event_bus, EventBus)
    assert isinstance(container.calendar, MarketCalendar)


def test_containers_are_isolated() -> None:
    assert make_container().event_bus is not make_container().event_bus
