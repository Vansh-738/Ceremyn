import io
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from alphaquant.core.calendar import MarketCalendar
from alphaquant.core.exceptions import DataError
from alphaquant.data.providers.bhavcopy import parse_bhavcopy, parse_bhavcopy_futures
from alphaquant.data.records import EodFutureRecord, EodOptionRecord
from alphaquant.data.services.ingest import BhavcopyIngestService

FIXTURE = Path(__file__).parents[2] / "fixtures" / "bhavcopy_sample.csv"
TRADE_DATE = date(2025, 7, 11)
UNDERLYINGS = ("NIFTY", "BANKNIFTY")


def fixture_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("BhavCopy_NSE_FO_0_0_0_20250711_F_0000.csv", FIXTURE.read_bytes())
    return buffer.getvalue()


class TestParser:
    def test_keeps_only_index_options_for_wanted_underlyings(self) -> None:
        records = parse_bhavcopy(fixture_zip(), UNDERLYINGS, TRADE_DATE)
        # Fixture: 3 NIFTY IDO + 1 BANKNIFTY IDO; FINNIFTY, stock option, future excluded.
        assert len(records) == 4
        assert {r.underlying for r in records} == {"NIFTY", "BANKNIFTY"}

    def test_field_mapping(self) -> None:
        records = parse_bhavcopy(fixture_zip(), UNDERLYINGS, TRADE_DATE)
        call = next(r for r in records if r.strike == Decimal(24500) and r.option_type == "CE")
        assert call.trade_date == TRADE_DATE
        assert call.expiry == date(2025, 7, 15)
        assert call.close == Decimal("180.5")
        assert call.settle == Decimal("180.5")
        assert call.open_interest == 4_521_300
        assert call.oi_change == 352_500
        assert call.volume == 8_956_234
        assert call.underlying_close == Decimal("24502.15")
        assert call.lot_size == 75

    def test_lot_size_varies_by_underlying_not_hardcoded(self) -> None:
        # NSE sets lot size per underlying (and revises it periodically) -- a single
        # hardcoded constant across underlyings, or across a multi-year backtest
        # window, silently misprices every rupee figure that depends on it.
        records = parse_bhavcopy(fixture_zip(), UNDERLYINGS, TRADE_DATE)
        nifty = next(r for r in records if r.underlying == "NIFTY")
        bank = next(r for r in records if r.underlying == "BANKNIFTY")
        assert nifty.lot_size == 75
        assert bank.lot_size == 30

    def test_negative_oi_change_preserved(self) -> None:
        records = parse_bhavcopy(fixture_zip(), UNDERLYINGS, TRADE_DATE)
        put = next(r for r in records if r.option_type == "PE")
        assert put.oi_change == -125_300

    def test_trade_date_mismatch_raises(self) -> None:
        with pytest.raises(DataError, match="mismatch"):
            parse_bhavcopy(fixture_zip(), UNDERLYINGS, date(2025, 7, 10))

    def test_invalid_zip_raises(self) -> None:
        with pytest.raises(DataError, match="zip"):
            parse_bhavcopy(b"not a zip", UNDERLYINGS, TRADE_DATE)


class TestFutureParser:
    def test_keeps_only_futures_for_wanted_underlyings(self) -> None:
        records = parse_bhavcopy_futures(fixture_zip(), UNDERLYINGS, TRADE_DATE)
        # Fixture: 1 NIFTY IDF; options and the stock future (RELIANCE, unwanted) excluded.
        assert len(records) == 1
        assert records[0].underlying == "NIFTY"

    def test_field_mapping(self) -> None:
        (record,) = parse_bhavcopy_futures(fixture_zip(), UNDERLYINGS, TRADE_DATE)
        assert record.trade_date == TRADE_DATE
        assert record.expiry == date(2025, 7, 31)
        assert record.close == Decimal("24580.25")
        assert record.settle == Decimal("24580.25")
        assert record.open_interest == 12_456_300
        assert record.oi_change == 235_600
        assert record.volume == 15_478_236
        assert record.underlying_close == Decimal("24502.15")

    def test_trade_date_mismatch_raises(self) -> None:
        with pytest.raises(DataError, match="mismatch"):
            parse_bhavcopy_futures(fixture_zip(), UNDERLYINGS, date(2025, 7, 10))

    def test_invalid_zip_raises(self) -> None:
        with pytest.raises(DataError, match="zip"):
            parse_bhavcopy_futures(b"not a zip", UNDERLYINGS, TRADE_DATE)


class FakeClient:
    """Bhavcopy client stub: canned payloads per date, 404s otherwise."""

    def __init__(self, available: dict[date, bytes]) -> None:
        self.available = available
        self.requested: list[date] = []

    async def download(self, trade_date: date) -> bytes:
        self.requested.append(trade_date)
        if trade_date not in self.available:
            raise DataError(f"no bhavcopy published for {trade_date} (404)")
        return self.available[trade_date]


class FakeRepo:
    def __init__(self) -> None:
        self.stored: list[EodOptionRecord] = []

    async def upsert_many(self, records: list[EodOptionRecord]) -> int:
        self.stored.extend(records)
        return len(records)


def make_service(client: FakeClient, repo: FakeRepo) -> BhavcopyIngestService:
    return BhavcopyIngestService(client, repo, MarketCalendar(), UNDERLYINGS)  # type: ignore[arg-type]


class TestIngestService:
    async def test_ingests_trading_days_only(self) -> None:
        client = FakeClient({TRADE_DATE: fixture_zip()})
        repo = FakeRepo()
        # Fri Jul 11 .. Mon Jul 14: weekend must not even be requested.
        results = await make_service(client, repo).ingest_range(TRADE_DATE, date(2025, 7, 14))
        assert client.requested == [TRADE_DATE, date(2025, 7, 14)]
        assert results == {TRADE_DATE: 4}
        assert len(repo.stored) == 4

    async def test_missing_file_is_skipped_not_fatal(self) -> None:
        client = FakeClient({})
        repo = FakeRepo()
        results = await make_service(client, repo).ingest_range(TRADE_DATE, TRADE_DATE)
        assert results == {}
        assert repo.stored == []

    async def test_rejects_inverted_range(self) -> None:
        service = make_service(FakeClient({}), FakeRepo())
        with pytest.raises(ValueError, match="end date"):
            await service.ingest_range(date(2025, 7, 14), date(2025, 7, 11))


class FakeFutureRepo:
    def __init__(self) -> None:
        self.stored: list[EodFutureRecord] = []

    async def upsert_many(self, records: list[EodFutureRecord]) -> int:
        self.stored.extend(records)
        return len(records)


class TestFutureIngestService:
    """Same `BhavcopyIngestService`, driven with `parse_bhavcopy_futures` instead of
    the (default) options parser -- no duplicated day-iteration/calendar logic."""

    async def test_ingests_futures_via_the_same_service(self) -> None:
        client = FakeClient({TRADE_DATE: fixture_zip()})
        repo = FakeFutureRepo()
        service = BhavcopyIngestService(
            client, repo, MarketCalendar(), UNDERLYINGS, parse=parse_bhavcopy_futures
        )  # type: ignore[arg-type]

        results = await service.ingest_range(TRADE_DATE, TRADE_DATE)

        assert results == {TRADE_DATE: 1}
        assert len(repo.stored) == 1
        assert repo.stored[0].underlying == "NIFTY"
