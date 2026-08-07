from datetime import date, timedelta
from decimal import Decimal

import pytest

import ceremyn.data.services.equity_history as equity_history_module
from ceremyn.core.exceptions import DataError
from ceremyn.data.records import EodEquityRecord
from ceremyn.data.services.equity_history import fetch_all_equity_candles

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
