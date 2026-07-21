import pytest

from alphaquant.core import logging as logging_module
from alphaquant.core.logging import _capture_to_ring_buffer, recent_log_entries


@pytest.fixture(autouse=True)
def _clear_ring_buffer():
    logging_module._RING_BUFFER.clear()
    yield
    logging_module._RING_BUFFER.clear()


class TestRingBuffer:
    def test_capture_appends_and_passes_through_unchanged(self) -> None:
        event_dict = {
            "event": "signal_submitted",
            "level": "info",
            "timestamp": "2026-07-16T00:00:00Z",
        }
        result = _capture_to_ring_buffer(None, "info", dict(event_dict))
        assert result == event_dict
        assert recent_log_entries(10) == [event_dict]

    def test_recent_log_entries_returns_newest_first(self) -> None:
        for i in range(3):
            _capture_to_ring_buffer(
                None, "info", {"event": f"event-{i}", "level": "info", "timestamp": str(i)}
            )
        entries = recent_log_entries(10)
        assert [e["event"] for e in entries] == ["event-2", "event-1", "event-0"]

    def test_recent_log_entries_respects_limit(self) -> None:
        for i in range(5):
            _capture_to_ring_buffer(
                None, "info", {"event": f"event-{i}", "level": "info", "timestamp": str(i)}
            )
        entries = recent_log_entries(2)
        assert [e["event"] for e in entries] == ["event-4", "event-3"]

    def test_ring_buffer_is_bounded(self) -> None:
        for i in range(1500):
            _capture_to_ring_buffer(
                None, "info", {"event": f"event-{i}", "level": "info", "timestamp": str(i)}
            )
        assert len(logging_module._RING_BUFFER) == 1000
        # Oldest entries fell off the front; the most recent 1000 remain.
        entries = recent_log_entries(1)
        assert entries[0]["event"] == "event-1499"
