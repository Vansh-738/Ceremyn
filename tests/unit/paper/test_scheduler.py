from datetime import datetime

from alphaquant.core.timeutils import IST
from alphaquant.paper.scheduler import PaperScheduler
from tests.unit.paper.conftest import make_tick


def test_dispatches_when_market_open() -> None:
    scheduler = PaperScheduler()
    received = []
    # 2026-07-14 is a Tuesday trading day; 10:00 IST is inside the session.
    now = datetime(2026, 7, 14, 10, 0, tzinfo=IST)
    ran = scheduler.advance(make_tick(0, "100"), received.append, now=now)
    assert ran is True
    assert len(received) == 1
    assert scheduler.ticks_processed == 1


def test_skips_when_market_closed() -> None:
    scheduler = PaperScheduler()
    received = []
    # After the 15:30 close.
    now = datetime(2026, 7, 14, 16, 0, tzinfo=IST)
    ran = scheduler.advance(make_tick(0, "100"), received.append, now=now)
    assert ran is False
    assert received == []
    assert scheduler.ticks_skipped == 1


def test_skips_on_weekend() -> None:
    scheduler = PaperScheduler()
    received = []
    now = datetime(2026, 7, 18, 10, 0, tzinfo=IST)  # Saturday
    assert scheduler.advance(make_tick(0, "100"), received.append, now=now) is False


def test_uses_tick_timestamp_when_now_omitted() -> None:
    scheduler = PaperScheduler()
    received = []
    # make_tick(0) is at 09:50 IST on a trading day -> open.
    assert scheduler.advance(make_tick(0, "100"), received.append) is True
    assert scheduler.is_open(make_tick(0, "100").as_of) is True
