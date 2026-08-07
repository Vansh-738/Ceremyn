"""NSE end-of-day bhavcopy: download and parse (UDiFF common format).

NSE publishes a daily UDiFF bhavcopy zip per segment on its archives host:
    F&O:    https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_<YYYYMMDD>_F_0000.csv.zip
    Equity: https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_<YYYYMMDD>_F_0000.csv.zip
Same column schema across segments. `parse_bhavcopy` keeps index options
(FinInstrmTp == "IDO") for the configured underlyings -- the primary historical
dataset for options backtests. `parse_bhavcopy_futures` reads the F&O file for
index/stock futures (FinInstrmTp in "IDF"/"STF"). `parse_bhavcopy_equity` reads
the separate CM (cash market) file for plain equities (FinInstrmTp == "STK",
SctySrs == "EQ" -- excludes preference shares/other non-common-equity series).
"""

import io
import zipfile
from collections.abc import Iterable
from datetime import date
from decimal import Decimal

import httpx
import polars as pl
import structlog

from ceremyn.core.exceptions import DataError
from ceremyn.data.records import EodEquityRecord, EodFutureRecord, EodOptionRecord

logger = structlog.get_logger(__name__)

ARCHIVE_URL = (
    "https://nsearchives.nseindia.com/content/fo/"
    "BhavCopy_NSE_FO_0_0_0_{date:%Y%m%d}_F_0000.csv.zip"
)
EQUITY_ARCHIVE_URL = (
    "https://nsearchives.nseindia.com/content/cm/"
    "BhavCopy_NSE_CM_0_0_0_{date:%Y%m%d}_F_0000.csv.zip"
)

_HEADERS = {
    # The archives host serves files directly but rejects default bot agents.
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "*/*",
}

_INDEX_OPTION_TYPE = "IDO"
_FUTURE_TYPES = ("IDF", "STF")  # index futures, stock futures
_EQUITY_INSTRUMENT_TYPE = "STK"
_EQUITY_SERIES = "EQ"  # excludes preference shares and other non-common-equity series


class BhavcopyClient:
    """Downloads raw F&O bhavcopy archives."""

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self._timeout = timeout_seconds

    async def download(self, trade_date: date) -> bytes:
        url = ARCHIVE_URL.format(date=trade_date)
        async with httpx.AsyncClient(timeout=self._timeout, headers=_HEADERS) as client:
            response = await client.get(url)
        if response.status_code == 404:
            raise DataError(f"no bhavcopy published for {trade_date} (404) — holiday?")
        if response.status_code != 200:
            raise DataError(
                f"bhavcopy download failed for {trade_date}: HTTP {response.status_code}"
            )
        return response.content


class EquityBhavcopyClient:
    """Downloads raw cash-market (CM) bhavcopy archives -- same format, separate file
    from the F&O one `BhavcopyClient` downloads."""

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        self._timeout = timeout_seconds

    async def download(self, trade_date: date) -> bytes:
        url = EQUITY_ARCHIVE_URL.format(date=trade_date)
        async with httpx.AsyncClient(timeout=self._timeout, headers=_HEADERS) as client:
            response = await client.get(url)
        if response.status_code == 404:
            raise DataError(f"no equity bhavcopy published for {trade_date} (404) — holiday?")
        if response.status_code != 200:
            raise DataError(
                f"equity bhavcopy download failed for {trade_date}: HTTP {response.status_code}"
            )
        return response.content


def parse_bhavcopy(
    zip_bytes: bytes, underlyings: Iterable[str], trade_date: date
) -> list[EodOptionRecord]:
    """Extract index-option rows for `underlyings` from a bhavcopy zip."""
    frame = _read_csv_from_zip(zip_bytes)
    wanted = set(underlyings)
    filtered = frame.filter(
        (pl.col("FinInstrmTp") == _INDEX_OPTION_TYPE) & pl.col("TckrSymb").is_in(wanted)
    )

    records: list[EodOptionRecord] = []
    for row in filtered.iter_rows(named=True):
        row_date = _as_date(row["TradDt"])
        if row_date != trade_date:
            raise DataError(
                f"bhavcopy trade date mismatch: expected {trade_date}, file has {row_date}"
            )
        records.append(
            EodOptionRecord(
                trade_date=row_date,
                underlying=str(row["TckrSymb"]),
                expiry=_as_date(row["XpryDt"]),
                strike=_as_decimal(row["StrkPric"]) or Decimal(0),
                option_type=str(row["OptnTp"]),
                open=_as_decimal(row["OpnPric"]),
                high=_as_decimal(row["HghPric"]),
                low=_as_decimal(row["LwPric"]),
                close=_as_decimal(row["ClsPric"]),
                settle=_as_decimal(row["SttlmPric"]),
                volume=_as_int(row["TtlTradgVol"]),
                open_interest=_as_int(row["OpnIntrst"]),
                oi_change=_as_int(row["ChngInOpnIntrst"]),
                underlying_close=_as_decimal(row["UndrlygPric"]),
                lot_size=_as_int(row["NewBrdLotQty"]),
            )
        )
    logger.info(
        "bhavcopy_parsed",
        trade_date=str(trade_date),
        total_rows=frame.height,
        kept_rows=len(records),
    )
    return records


def parse_bhavcopy_futures(
    zip_bytes: bytes, underlyings: Iterable[str], trade_date: date
) -> list[EodFutureRecord]:
    """Extract index/stock-future rows for `underlyings` from the same bhavcopy zip
    `parse_bhavcopy` reads options from."""
    frame = _read_csv_from_zip(zip_bytes)
    wanted = set(underlyings)
    filtered = frame.filter(
        pl.col("FinInstrmTp").is_in(_FUTURE_TYPES) & pl.col("TckrSymb").is_in(wanted)
    )

    records: list[EodFutureRecord] = []
    for row in filtered.iter_rows(named=True):
        row_date = _as_date(row["TradDt"])
        if row_date != trade_date:
            raise DataError(
                f"bhavcopy trade date mismatch: expected {trade_date}, file has {row_date}"
            )
        records.append(
            EodFutureRecord(
                trade_date=row_date,
                underlying=str(row["TckrSymb"]),
                expiry=_as_date(row["XpryDt"]),
                open=_as_decimal(row["OpnPric"]),
                high=_as_decimal(row["HghPric"]),
                low=_as_decimal(row["LwPric"]),
                close=_as_decimal(row["ClsPric"]),
                settle=_as_decimal(row["SttlmPric"]),
                volume=_as_int(row["TtlTradgVol"]),
                open_interest=_as_int(row["OpnIntrst"]),
                oi_change=_as_int(row["ChngInOpnIntrst"]),
                underlying_close=_as_decimal(row["UndrlygPric"]),
                lot_size=_as_int(row["NewBrdLotQty"]),
            )
        )
    logger.info(
        "bhavcopy_futures_parsed",
        trade_date=str(trade_date),
        total_rows=frame.height,
        kept_rows=len(records),
    )
    return records


def parse_bhavcopy_equity(
    zip_bytes: bytes, tradingsymbols: Iterable[str] | None, trade_date: date
) -> list[EodEquityRecord]:
    """Extract cash-equity rows for `tradingsymbols` from a CM bhavcopy zip
    (`EquityBhavcopyClient.download`) -- a separate file from the F&O one.

    `tradingsymbols=None` returns every "EQ"-series row in the file (the whole
    day's ~2,400 listed equities) -- for scanning the full market in one pass
    per day, rather than downloading the same file once per symbol wanted.
    """
    frame = _read_csv_from_zip(zip_bytes)
    filtered = frame.filter(
        (pl.col("FinInstrmTp") == _EQUITY_INSTRUMENT_TYPE) & (pl.col("SctySrs") == _EQUITY_SERIES)
    )
    if tradingsymbols is not None:
        wanted = set(tradingsymbols)
        filtered = filtered.filter(pl.col("TckrSymb").is_in(wanted))

    records: list[EodEquityRecord] = []
    for row in filtered.iter_rows(named=True):
        row_date = _as_date(row["TradDt"])
        if row_date != trade_date:
            raise DataError(
                f"bhavcopy trade date mismatch: expected {trade_date}, file has {row_date}"
            )
        isin = row["ISIN"]
        records.append(
            EodEquityRecord(
                trade_date=row_date,
                tradingsymbol=str(row["TckrSymb"]),
                isin=str(isin).strip() or None if isin is not None else None,
                open=_as_decimal(row["OpnPric"]),
                high=_as_decimal(row["HghPric"]),
                low=_as_decimal(row["LwPric"]),
                close=_as_decimal(row["ClsPric"]),
                volume=_as_int(row["TtlTradgVol"]),
            )
        )
    logger.info(
        "bhavcopy_equity_parsed",
        trade_date=str(trade_date),
        total_rows=frame.height,
        kept_rows=len(records),
    )
    return records


def _read_csv_from_zip(zip_bytes: bytes) -> pl.DataFrame:
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            csv_names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
            if not csv_names:
                raise DataError("bhavcopy zip contains no CSV file")
            payload = archive.read(csv_names[0])
    except zipfile.BadZipFile as exc:
        raise DataError("bhavcopy payload is not a valid zip archive") from exc
    # Read everything as text; numeric parsing is done per-field so that empty
    # markers ("-", "") never break the whole file.
    return pl.read_csv(io.BytesIO(payload), infer_schema_length=0)


def _as_date(value: object) -> date:
    return date.fromisoformat(str(value).strip())


def _as_decimal(value: object) -> Decimal | None:
    text = str(value).strip() if value is not None else ""
    if text in ("", "-", "NA", "null"):
        return None
    return Decimal(text)


def _as_int(value: object) -> int:
    decimal_value = _as_decimal(value)
    return int(decimal_value) if decimal_value is not None else 0
