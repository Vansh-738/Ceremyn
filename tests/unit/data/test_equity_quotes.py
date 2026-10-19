import asyncio
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from ceremyn.config.settings import EquityQuoteSettings
from ceremyn.core.calendar import MarketCalendar
from ceremyn.core.timeutils import IST
from ceremyn.data.services.equity_quotes import EquityQuoteJob, rank_universe
from ceremyn.domain import Candle, Quote, TimeFrame
from ceremyn.live.cache import LiveDataCache

JobFixture = tuple[EquityQuoteJob, AsyncMock, AsyncMock, LiveDataCache, list[datetime]]

NOW = datetime(2026, 7, 15, 10, tzinfo=IST)


def candle(symbol: str, at: datetime, volume: int) -> Candle:
    return Candle(
        tradingsymbol=symbol,
        timestamp=at,
        timeframe=TimeFrame.DAY,
        open=Decimal(100),
        high=Decimal(100),
        low=Decimal(100),
        close=Decimal(100),
        volume=volume,
    )


@pytest.fixture
def setup_job() -> JobFixture:
    history = {
        symbol: tuple(candle(symbol, NOW - timedelta(days=d), volume) for d in (2, 1))
        for symbol, volume in [("AAA", 20), ("BBB", 10)]
    }
    loader = AsyncMock(return_value=history)
    provider = AsyncMock()
    provider.quotes.return_value = {
        f"NSE:{symbol}": Quote(tradingsymbol=symbol, timestamp=NOW, last_price=Decimal(100))
        for symbol in history
    }
    cache = LiveDataCache()
    clock = [NOW]
    job = EquityQuoteJob(
        provider=provider,
        cache=cache,
        history_loader=loader,
        settings=EquityQuoteSettings(enabled=True, turnover_sessions=2),
        calendar=MarketCalendar(),
        clock=lambda: clock[0],
    )
    return job, provider, loader, cache, clock


def test_rank_excludes_incomplete_history_and_uses_only_completed_sessions() -> None:
    sessions = ((NOW - timedelta(days=2)).date(), (NOW - timedelta(days=1)).date())
    history = {
        "BBB": tuple(candle("BBB", NOW - timedelta(days=d), 10) for d in (2, 1)),
        "AAA": tuple(candle("AAA", NOW - timedelta(days=d), 10) for d in (2, 1)),
        "NEW": (candle("NEW", NOW - timedelta(days=1), 10000),),
        "ZERO": tuple(candle("ZERO", NOW - timedelta(days=d), 0) for d in (2, 1)),
    }
    history["BBB"] += (candle("BBB", NOW, 1000000),)
    assert rank_universe(history, sessions, 400) == ("AAA", "BBB")
    assert rank_universe(history, sessions, 1) == ("AAA",)


async def test_refreshes_shared_cache_and_loads_universe_once_daily(setup_job: JobFixture) -> None:
    job, provider, loader, cache, clock = setup_job
    assert await job.run_once() == 2
    assert cache.latest_quote("AAA") is provider.quotes.return_value["NSE:AAA"]
    provider.quotes.assert_awaited_once_with(["NSE:AAA", "NSE:BBB"])
    assert await job.run_once() == 2
    assert loader.await_count == 1
    clock[0] += timedelta(days=1)
    loader.return_value = {
        "BBB": tuple(candle("BBB", clock[0] - timedelta(days=d), 10) for d in (2, 1))
    }
    provider.quotes.return_value["NSE:BBB"] = Quote(
        tradingsymbol="BBB", timestamp=clock[0], last_price=Decimal(101)
    )
    assert await job.run_once() == 1
    assert job.symbols == ("BBB",)
    assert loader.await_count == 2


@pytest.mark.parametrize("at", [NOW.replace(hour=8), NOW.replace(hour=16), NOW + timedelta(days=3)])
async def test_closed_market_does_no_io(setup_job: JobFixture, at: datetime) -> None:
    job, provider, loader, _, clock = setup_job
    clock[0] = at
    assert await job.run_once() == 0
    loader.assert_not_awaited()
    provider.quotes.assert_not_awaited()


@pytest.mark.parametrize("kind", ["missing", "stale", "future", "wrong_symbol", "zero"])
async def test_partial_response_never_replaces_good_cache_with_invalid_quote(
    setup_job: JobFixture, kind: str
) -> None:
    job, provider, _, cache, _ = setup_job
    await job.run_once()
    old = cache.latest_quote("AAA")
    quote = provider.quotes.return_value["NSE:AAA"]
    updates = {
        "stale": {"timestamp": NOW - timedelta(minutes=6)},
        "future": {"timestamp": NOW + timedelta(seconds=1)},
        "wrong_symbol": {"tradingsymbol": "OTHER"},
        "zero": {"last_price": Decimal(0)},
    }
    if kind == "missing":
        del provider.quotes.return_value["NSE:AAA"]
    else:
        provider.quotes.return_value["NSE:AAA"] = quote.model_copy(update=updates[kind])
    assert await job.run_once() == 1
    assert cache.latest_quote("AAA") is old


async def test_no_valid_quotes_and_incomplete_history_are_failures(setup_job: JobFixture) -> None:
    job, provider, loader, _, _ = setup_job
    loader.return_value = {}
    with pytest.raises(ValueError, match="complete trailing"):
        await job.run_once()
    provider.quotes.assert_not_awaited()
    assert job.last_success_at is None


async def test_empty_quote_response_is_not_success(setup_job: JobFixture) -> None:
    job, provider, _, cache, _ = setup_job
    provider.quotes.return_value = {}
    with pytest.raises(ValueError, match="no fresh"):
        await job.run_once()
    assert job.last_success_at is None and cache.latest_quote("AAA") is None


async def test_history_crossing_close_skips_quote_call(setup_job: JobFixture) -> None:
    job, provider, loader, _, clock = setup_job
    history = loader.return_value

    async def load(start: date, end: date) -> dict[str, tuple[Candle, ...]]:
        clock[0] = NOW.replace(hour=16)
        return history

    loader.side_effect = load
    assert await job.run_once() == 0
    provider.quotes.assert_not_awaited()


async def test_worker_recovers_after_token_or_network_failure(
    setup_job: JobFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    job, provider, _, cache, _ = setup_job
    quotes = provider.quotes.return_value
    provider.quotes.side_effect = [RuntimeError("expired token"), RuntimeError("network"), quotes]
    observed: list[tuple[int, str]] = []

    async def sleep(_: float) -> None:
        observed.append((job.consecutive_failures, job.last_error))
        if len(observed) == 3:
            raise asyncio.CancelledError

    monkeypatch.setattr("ceremyn.data.services.equity_quotes.asyncio.sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await job._run()
    assert observed == [(1, "expired token"), (2, "network"), (0, "")]
    assert job.last_success_at == NOW
    assert cache.latest_quote("AAA") is not None


async def test_start_stop_are_idempotent_and_disabled_is_inert(setup_job: JobFixture) -> None:
    job, provider, _, _, _ = setup_job
    await job.stop()
    job._settings.enabled = False
    await job.start()
    assert job._task is None
    job._settings.enabled = True
    await job.start()
    task = job._task
    await job.start()
    assert job._task is task
    await job.stop()
    await job.stop()
    assert job._task is None
    provider.quotes.assert_not_awaited()
