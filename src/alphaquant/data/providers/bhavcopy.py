"""NSE F&O end-of-day bhavcopy: download and parse (UDiFF common format).

NSE publishes a daily UDiFF bhavcopy zip on its archives host:
    https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_<YYYYMMDD>_F_0000.csv.zip
One row per contract, covering both options and futures. `parse_bhavcopy` keeps
index options (FinInstrmTp == "IDO") for the configured underlyings -- the
primary historical dataset for options backtests. `parse_bhavcopy_futures`
reads the same file for index/stock futures (FinInstrmTp in "IDF"/"STF").
"""

import io
import zipfile
from collections.abc import Iterable
from datetime import date
from decimal import Decimal

import httpx
import polars as pl
import structlog

from alphaquant.core.exceptions import DataError
from alphaquant.data.records import EodFutureRecord, EodOptionRecord

logger = structlog.get_logger(__name__)

ARCHIVE_URL = (
    "https://nsearchives.nseindia.com/content/fo/"
    "BhavCopy_NSE_FO_0_0_0_{date:%Y%m%d}_F_0000.csv.zip"
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


class BhavcopyClient:
    """Downloads raw bhavcopy archives."""

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
