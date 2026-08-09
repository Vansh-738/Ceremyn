from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest

import ceremyn.data.services.equity_history as equity_history_module
from ceremyn.core.exceptions import DataError
from ceremyn.core.timeutils import IST
from ceremyn.data.records import EodEquityRecord
from ceremyn.data.services.equity_history import (
    DEFAULT_TURNOVER_WINDOW,
    fetch_all_equity_candles,
    filter_by_min_avg_turnover,
)
from ceremyn.domain import Candle, TimeFrame

MONDAY = date(2026, 6, 1)  # a real trading day, arbitrary Monday
SATURDAY = MONDAY + timedelta(days=5)


class FakeCalendar:
    def is_trading_day(self, day: date) -> bool:
        return day.weekday() < 5  # Mon-Fri only, matching MONDAY/SATURDAY above


class FakeBhavcopyClient:
    def __init__(self, *, fail_on: set[date] | None = None) -> None:
        self.fail_on = fail_on or set()
        self.downloaded: list[date] = []

    async def download(self, trade_date: date) -> bytes:
        self.downloaded.append(trade_date)
        if trade_date in self.fail_on:
            raise DataError("no bhavcopy for this date")
        return b"fake-zip-bytes"


def _record(symbol: str, trade_date: date, close: float) -> EodEquityRecord:
    return EodEquityRecord(
        trade_date=trade_date,
        tradingsymbol=symbol,
        open=Decimal(str(close - 1)),
        high=Decimal(str(close + 1)),
        low=Decimal(str(close - 2)),
        close=Decimal(str(close)),
        volume=1000,
    )


def _install(monkeypatch: pytest.MonkeyPatch, client: FakeBhavcopyClient, parse_fn: object) -> None:
    monkeypatch.setattr(equity_history_module, "MarketCalendar", FakeCalendar)
    monkeypatch.setattr(equity_history_module, "EquityBhavcopyClient", lambda: client)
    monkeypatch.setattr(equity_history_module, "parse_bhavcopy_equity", parse_fn)


class TestFetchAllEquityCandles:
    async def test_one_download_per_trading_day_not_per_symbol(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = FakeBhavcopyClient()
        _install(
            monkeypatch,
            client,
            lambda payload, symbols, day: [
                _record("RELIANCE", day, 1490.0),
                _record("TCS", day, 3800.0),
            ],
        )
        result = await fetch_all_equity_candles(MONDAY, MONDAY, symbols={"RELIANCE", "TCS"})

        assert client.downloaded == [MONDAY]  # one download total, covering both symbols
        assert set(result) == {"RELIANCE", "TCS"}
        assert len(result["RELIANCE"]) == 1
        assert result["RELIANCE"][0].close == Decimal("1490.0")

    async def test_non_trading_days_are_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = FakeBhavcopyClient()
        _install(
            monkeypatch,
            client,
            lambda payload, symbols, day: [_record("RELIANCE", day, 1490.0)],
        )
        result = await fetch_all_equity_candles(MONDAY, SATURDAY, symbols={"RELIANCE"})

        assert SATURDAY not in client.downloaded
        assert len(result["RELIANCE"]) == 5  # Mon-Fri only

    async def test_missing_bhavcopy_for_a_day_is_skipped_not_raised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = FakeBhavcopyClient(fail_on={MONDAY})
        _install(
            monkeypatch,
            client,
            lambda payload, symbols, day: [_record("RELIANCE", day, 1490.0)],
        )
        result = await fetch_all_equity_candles(MONDAY, MONDAY, symbols={"RELIANCE"})

        assert result == {}

    async def test_zero_or_negative_close_is_excluded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = FakeBhavcopyClient()
        _install(
            monkeypatch,
            client,
            lambda payload, symbols, day: [
                EodEquityRecord(trade_date=day, tradingsymbol="SUSPENDED", close=Decimal(0)),
            ],
        )
        result = await fetch_all_equity_candles(MONDAY, MONDAY, symbols={"SUSPENDED"})

        assert result == {}

    async def test_symbols_none_scans_whole_universe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = FakeBhavcopyClient()
        seen_symbols_arg = []

        def fake_parse(
            payload: bytes, symbols: set[str] | None, day: date
        ) -> list[EodEquityRecord]:
            seen_symbols_arg.append(symbols)
            return [_record("ANY_SYMBOL", day, 100.0)]

        _install(monkeypatch, client, fake_parse)
        result = await fetch_all_equity_candles(MONDAY, MONDAY, symbols=None)

        assert seen_symbols_arg == [None]
        assert "ANY_SYMBOL" in result


def _candle(symbol: str, i: int, close: float, volume: int) -> Candle:
    return Candle(
        tradingsymbol=symbol,
        timeframe=TimeFrame.DAY,
        timestamp=datetime.combine(date(2026, 1, 1) + timedelta(days=i), time(), tzinfo=IST),
        open=Decimal(str(close)),
        high=Decimal(str(close)),
        low=Decimal(str(close)),
        close=Decimal(str(close)),
        volume=volume,
    )


class TestFilterByMinAvgTurnover:
    """`window`-day trailing average, judged bar-by-bar -- never a single
    average over the whole fetched history (see the function's own docstring
    for why that distinction matters: it's what keeps a stock's future
    turnover from justifying scanning its past)."""

    def test_keeps_a_uniformly_liquid_symbol_trimmed_to_the_confirmable_tail(self) -> None:
        # 25 days, all comfortably liquid. The first (window - 1) days can never
        # be confirmed (no full trailing window behind them yet) and are trimmed
        # -- this is the same unavoidable warm-up cost every trailing-window
        # indicator in this codebase has (EMA, RSI, ATR, ...), not a bug.
        candles = tuple(_candle("LIQUID", i, 100.0, 500_000) for i in range(25))  # 5cr/day
        result = filter_by_min_avg_turnover({"LIQUID": candles}, Decimal("10000000"))
        assert "LIQUID" in result
        assert len(result["LIQUID"]) == 25 - (DEFAULT_TURNOVER_WINDOW - 1)
        assert result["LIQUID"] == candles[DEFAULT_TURNOVER_WINDOW - 1 :]

    def test_drops_a_uniformly_thin_symbol_entirely(self) -> None:
        candles = tuple(_candle("THIN", i, 10.0, 100) for i in range(25))  # 1000/day
        result = filter_by_min_avg_turnover({"THIN": candles}, Decimal("10000000"))
        assert "THIN" not in result

    def test_an_early_spike_does_not_carry_an_otherwise_thin_symbol(self) -> None:
        # One huge day, then thin for the rest of the fetched history. The most
        # recent `window`-day average is what's actually checked, so the old
        # single-average bug (a whole-history mean pulled up by one spike) can't
        # resurface here regardless of how far back the spike sits.
        candles = (
            _candle("SPIKY", 0, 20_000.0, 100_000),  # one huge day: 20,000cr
            *(_candle("SPIKY", i, 10.0, 100) for i in range(1, 25)),  # 1000/day after
        )
        result = filter_by_min_avg_turnover({"SPIKY": candles}, Decimal("10000000"))
        assert "SPIKY" not in result

    def test_trims_an_early_illiquid_stretch_instead_of_folding_it_in(self) -> None:
        # The key fix: a symbol thin for its first 30 days, then comfortably
        # liquid for the next 30, must not have its whole 60-day history kept
        # just because it's liquid *now* -- only the confirmed-liquid tail
        # should survive.
        thin = tuple(_candle("GROWN", i, 10.0, 100) for i in range(30))  # 1000/day
        liquid = tuple(_candle("GROWN", 30 + i, 100.0, 500_000) for i in range(30))  # 5cr/day
        result = filter_by_min_avg_turnover({"GROWN": thin + liquid}, Decimal("10000000"))
        assert "GROWN" in result
        kept = result["GROWN"]
        assert len(kept) < 60  # the thin era (and part of the transition) was trimmed away
        assert all(c.close == Decimal("100.0") for c in kept)  # nothing from the thin era survives
        assert kept[0].timestamp > thin[-1].timestamp  # kept history starts after the thin era ends

    def test_exactly_at_the_floor_is_kept(self) -> None:
        candles = tuple(
            _candle("EXACT", i, 100.0, 100) for i in range(DEFAULT_TURNOVER_WINDOW)
        )  # exactly 10,000/day, every day
        result = filter_by_min_avg_turnover({"EXACT": candles}, Decimal("10000"))
        assert "EXACT" in result

    def test_fewer_than_window_days_cannot_be_assessed_and_are_dropped(self) -> None:
        too_short = DEFAULT_TURNOVER_WINDOW - 1
        candles = tuple(_candle("NEW", i, 100.0, 500_000) for i in range(too_short))
        result = filter_by_min_avg_turnover({"NEW": candles}, Decimal("10000000"))
        assert "NEW" not in result

    def test_empty_candle_tuple_is_dropped(self) -> None:
        result = filter_by_min_avg_turnover({"EMPTY": ()}, Decimal("1"))
        assert result == {}
