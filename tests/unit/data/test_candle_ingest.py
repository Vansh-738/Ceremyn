from datetime import datetime
from decimal import Decimal

import pytest

from alphaquant.core.exceptions import DataError
from alphaquant.core.timeutils import IST
from alphaquant.data.services.candle_ingest import CandleIngestService
from alphaquant.domain import Candle, EquityInstrument, Exchange, TimeFrame


class FakeProvider:
    def __init__(self, candles: list[Candle]) -> None:
        self.candles = candles
        self.calls: list[tuple[int, str, TimeFrame, datetime, datetime]] = []

    async def historical_candles(
        self,
        broker_token: int,
        tradingsymbol: str,
        timeframe: TimeFrame,
        start: datetime,
        end: datetime,
        with_oi: bool = True,
    ) -> list[Candle]:
        self.calls.append((broker_token, tradingsymbol, timeframe, start, end))
        return self.candles


class FakeCandleRepo:
    def __init__(self) -> None:
        self.stored: list[Candle] = []

    async def upsert_many(self, candles: list[Candle]) -> int:
        self.stored.extend(candles)
        return len(candles)


def make_candle(tradingsymbol: str = "RELIANCE") -> Candle:
    return Candle(
        tradingsymbol=tradingsymbol,
        timeframe=TimeFrame.DAY,
        timestamp=datetime(2025, 7, 11, tzinfo=IST),
        open=Decimal("1480"),
        high=Decimal("1495"),
        low=Decimal("1470"),
        close=Decimal("1489.25"),
        volume=5_123_456,
    )


class TestCandleIngestService:
    async def test_ingests_and_stores_history(self) -> None:
        provider = FakeProvider([make_candle()])
        repo = FakeCandleRepo()
        service = CandleIngestService(provider, repo)  # type: ignore[arg-type]
        equity = EquityInstrument(
            tradingsymbol="RELIANCE",
            exchange=Exchange.NSE,
            underlying="RELIANCE",
            broker_token=738561,
        )
        start = datetime(2025, 7, 1, tzinfo=IST)
        end = datetime(2025, 7, 11, tzinfo=IST)

        stored = await service.ingest_range(equity, TimeFrame.DAY, start, end)

        assert stored == 1
        assert repo.stored == [make_candle()]
        assert provider.calls == [(738561, "RELIANCE", TimeFrame.DAY, start, end)]

    async def test_raises_without_broker_token(self) -> None:
        provider = FakeProvider([])
        repo = FakeCandleRepo()
        service = CandleIngestService(provider, repo)  # type: ignore[arg-type]
        equity = EquityInstrument(
            tradingsymbol="RELIANCE", exchange=Exchange.NSE, underlying="RELIANCE"
        )

        with pytest.raises(DataError, match="broker_token"):
            await service.ingest_range(
                equity,
                TimeFrame.DAY,
                datetime(2025, 7, 1, tzinfo=IST),
                datetime(2025, 7, 11, tzinfo=IST),
            )
