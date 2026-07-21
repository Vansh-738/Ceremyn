from collections.abc import Sequence
from datetime import timedelta

import pytest

from ceremyn.core.events import EventBus
from ceremyn.data.services.chain_analytics import ChainAnalyticsService
from ceremyn.live import LiveMarketDataEngine
from ceremyn.live.events import SnapshotBuilt
from ceremyn.live.stream import StreamTickBatch
from tests.unit.live.conftest import (
    BASE_TS,
    nifty_contracts,
    nifty_definition,
    tick_payload,
)


class FakeClient:
    def __init__(self) -> None:
        self.subscribed: list[list[int]] = []
        self.restored = 0

    def connect(self) -> None:
        return None

    def close(self) -> None:
        return None

    def subscribe(self, instrument_tokens: Sequence[int]) -> None:
        self.subscribed.append(list(instrument_tokens))

    def unsubscribe(self, instrument_tokens: Sequence[int]) -> None:
        return None

    def set_mode(self, mode: str, instrument_tokens: Sequence[int]) -> None:
        return None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_engine_end_to_end_batch_processing() -> None:
    bus = EventBus()
    built: list[SnapshotBuilt] = []
    bus.subscribe(SnapshotBuilt, built.append)
    engine = LiveMarketDataEngine(
        underlyings=(nifty_definition(),),
        contracts=nifty_contracts(),
        analytics=ChainAnalyticsService(risk_free_rate=0.065),
        client=FakeClient(),
        event_bus=bus,
    )

    snapshots = await engine.on_tick_batch(
        StreamTickBatch(
            ticks=(
                tick_payload(256265, last_price="24010"),
                tick_payload(101, last_price="150", bid="149.5", ask="150.5"),
                tick_payload(
                    102,
                    last_price="145",
                    bid="144.5",
                    ask="145.5",
                    timestamp=BASE_TS + timedelta(seconds=1),
                ),
            ),
            received_at=BASE_TS + timedelta(seconds=1),
        )
    )

    assert len(snapshots) == 1
    assert built[0].snapshot == snapshots[0]
    assert engine.latest_metrics(now=BASE_TS + timedelta(seconds=1)).ticks_processed == 3
