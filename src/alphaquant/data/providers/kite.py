"""Zerodha Kite Connect adapter (market data only).

Order placement does NOT live here — that's the execution layer's KiteBroker
(M10), behind the live-trading gates. The kiteconnect SDK is synchronous, so
every call is pushed off the event loop with asyncio.to_thread.

The underlying client object is injected to keep this adapter fully testable;
`KiteProvider.from_settings` builds the real one.
"""

import asyncio
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import structlog

from alphaquant.config import Settings
from alphaquant.core.exceptions import BrokerError
from alphaquant.core.timeutils import IST, now_utc
from alphaquant.domain import (
    Candle,
    EquityInstrument,
    ETFInstrument,
    Exchange,
    FutureContract,
    OptionContract,
    OptionType,
    Quote,
    TimeFrame,
)

logger = structlog.get_logger(__name__)

SPOT_SYMBOLS = {
    "NIFTY": "NSE:NIFTY 50",
    "BANKNIFTY": "NSE:NIFTY BANK",
    "FINNIFTY": "NSE:NIFTY FIN SERVICE",
    "MIDCPNIFTY": "NSE:NIFTY MID SELECT",
}

_QUOTE_BATCH = 400  # Kite's quote endpoint caps around 500 symbols per call


class KiteProvider:
    def __init__(self, kite: Any) -> None:
        self._kite = kite

    @classmethod
    def from_settings(cls, settings: Settings) -> "KiteProvider":
        from kiteconnect import KiteConnect

        if not settings.kite.api_key:
            raise BrokerError("ALPHAQUANT_KITE__API_KEY is not configured")
        kite = KiteConnect(api_key=settings.kite.api_key)
        access_token = settings.kite.access_token.get_secret_value()
        if access_token:
            kite.set_access_token(access_token)
        return cls(kite)

    # -- auth -------------------------------------------------------------

    def login_url(self) -> str:
        return str(self._kite.login_url())

    async def authenticate(self, request_token: str, api_secret: str) -> str:
        """Exchange the login redirect's request token for an access token."""
        try:
            session = await asyncio.to_thread(
                self._kite.generate_session, request_token, api_secret=api_secret
            )
            access_token = str(session["access_token"])
            self._kite.set_access_token(access_token)
            return access_token
        except Exception as exc:
            raise BrokerError(f"Kite session exchange failed: {exc}") from exc

    def set_access_token(self, access_token: str) -> None:
        self._kite.set_access_token(access_token)

    # -- instruments --------------------------------------------------------

    async def _fetch_instrument_dump(self, exchange: str) -> list[dict[str, Any]]:
        try:
            dump: list[dict[str, Any]] = await asyncio.to_thread(self._kite.instruments, exchange)
        except Exception as exc:
            raise BrokerError(f"Kite instrument dump failed: {exc}") from exc
        return dump

    async def fetch_option_contracts(self, underlyings: Sequence[str]) -> list[OptionContract]:
        """All NFO option contracts for the given index underlyings."""
        dump = await self._fetch_instrument_dump("NFO")
        wanted = set(underlyings)
        contracts = [
            _instrument_to_contract(entry)
            for entry in dump
            if entry.get("name") in wanted and entry.get("instrument_type") in ("CE", "PE")
        ]
        logger.info("kite_contracts_fetched", count=len(contracts))
        return contracts

    async def fetch_future_contracts(self, underlyings: Sequence[str]) -> list[FutureContract]:
        """All NFO future contracts for the given index/stock underlyings."""
        dump = await self._fetch_instrument_dump("NFO")
        wanted = set(underlyings)
        contracts = [
            _instrument_to_future(entry)
            for entry in dump
            if entry.get("name") in wanted and entry.get("instrument_type") == "FUT"
        ]
        logger.info("kite_future_contracts_fetched", count=len(contracts))
        return contracts

    async def _fetch_cash_instrument_dump(
        self, tradingsymbols: Sequence[str]
    ) -> list[dict[str, Any]]:
        """Raw NSE cash-segment entries for the given tradingsymbols. Equities and
        ETFs share the same `instrument_type` ("EQ") in Kite's dump -- there is no
        structural field to tell them apart; callers must already know which
        tradingsymbols they want classified as which."""
        dump = await self._fetch_instrument_dump("NSE")
        wanted = set(tradingsymbols)
        return [
            entry
            for entry in dump
            if entry.get("tradingsymbol") in wanted and entry.get("instrument_type") == "EQ"
        ]

    async def fetch_equity_instruments(
        self, tradingsymbols: Sequence[str]
    ) -> list[EquityInstrument]:
        """Equity instruments for the given NSE tradingsymbols."""
        entries = await self._fetch_cash_instrument_dump(tradingsymbols)
        instruments = [_instrument_to_equity(entry) for entry in entries]
        logger.info("kite_equity_instruments_fetched", count=len(instruments))
        return instruments

    async def fetch_etf_instruments(self, tradingsymbols: Sequence[str]) -> list[ETFInstrument]:
        """ETF instruments for the given NSE tradingsymbols."""
        entries = await self._fetch_cash_instrument_dump(tradingsymbols)
        instruments = [_instrument_to_etf(entry) for entry in entries]
        logger.info("kite_etf_instruments_fetched", count=len(instruments))
        return instruments

    # -- quotes ---------------------------------------------------------------

    async def quotes(self, symbols: Sequence[str]) -> dict[str, Quote]:
        """Full quotes keyed by 'EXCHANGE:TRADINGSYMBOL'."""
        result: dict[str, Quote] = {}
        for start in range(0, len(symbols), _QUOTE_BATCH):
            batch = list(symbols[start : start + _QUOTE_BATCH])
            try:
                raw: dict[str, Any] = await asyncio.to_thread(self._kite.quote, batch)
            except Exception as exc:
                raise BrokerError(f"Kite quote fetch failed: {exc}") from exc
            for key, payload in raw.items():
                result[key] = _payload_to_quote(key, payload)
        return result

    async def spot_price(self, underlying: str) -> Decimal:
        symbol = SPOT_SYMBOLS.get(underlying)
        if symbol is None:
            raise BrokerError(f"no spot symbol mapping for underlying {underlying!r}")
        try:
            raw: dict[str, Any] = await asyncio.to_thread(self._kite.ltp, [symbol])
        except Exception as exc:
            raise BrokerError(f"Kite LTP fetch failed: {exc}") from exc
        return Decimal(str(raw[symbol]["last_price"]))

    # -- history --------------------------------------------------------------

    async def historical_candles(
        self,
        broker_token: int,
        tradingsymbol: str,
        timeframe: TimeFrame,
        start: datetime,
        end: datetime,
        with_oi: bool = True,
    ) -> list[Candle]:
        try:
            raw: list[dict[str, Any]] = await asyncio.to_thread(
                self._kite.historical_data,
                broker_token,
                start,
                end,
                timeframe.value,
                oi=with_oi,
            )
        except Exception as exc:
            raise BrokerError(f"Kite historical fetch failed: {exc}") from exc
        return [
            Candle(
                tradingsymbol=tradingsymbol,
                timeframe=timeframe,
                timestamp=_ensure_ist(bar["date"]),
                open=Decimal(str(bar["open"])),
                high=Decimal(str(bar["high"])),
                low=Decimal(str(bar["low"])),
                close=Decimal(str(bar["close"])),
                volume=int(bar.get("volume", 0)),
                open_interest=int(bar.get("oi", 0)),
            )
            for bar in raw
        ]


def _instrument_to_contract(entry: dict[str, Any]) -> OptionContract:
    return OptionContract(
        tradingsymbol=str(entry["tradingsymbol"]),
        exchange=Exchange.NFO,
        tick_size=Decimal(str(entry.get("tick_size", "0.05"))),
        broker_token=int(entry["instrument_token"]),
        underlying=str(entry["name"]),
        expiry=_ensure_date(entry["expiry"]),
        strike=Decimal(str(entry["strike"])),
        option_type=OptionType(entry["instrument_type"]),
        lot_size=int(entry["lot_size"]),
    )


def _instrument_to_future(entry: dict[str, Any]) -> FutureContract:
    return FutureContract(
        tradingsymbol=str(entry["tradingsymbol"]),
        exchange=Exchange.NFO,
        tick_size=Decimal(str(entry.get("tick_size", "0.05"))),
        broker_token=int(entry["instrument_token"]),
        underlying=str(entry["name"]),
        expiry=_ensure_date(entry["expiry"]),
        lot_size=int(entry["lot_size"]),
    )


def _cash_instrument_kwargs(entry: dict[str, Any]) -> dict[str, Any]:
    """Fields shared by every NSE cash-segment instrument (equity or ETF)."""
    tradingsymbol = str(entry["tradingsymbol"])
    return {
        "tradingsymbol": tradingsymbol,
        "exchange": Exchange.NSE,
        "tick_size": Decimal(str(entry.get("tick_size", "0.05"))),
        "broker_token": int(entry["instrument_token"]),
        "underlying": tradingsymbol,
        "isin": str(entry["isin"]) if entry.get("isin") else None,
    }


def _instrument_to_equity(entry: dict[str, Any]) -> EquityInstrument:
    return EquityInstrument(**_cash_instrument_kwargs(entry))


def _instrument_to_etf(entry: dict[str, Any]) -> ETFInstrument:
    return ETFInstrument(**_cash_instrument_kwargs(entry))


def _payload_to_quote(key: str, payload: dict[str, Any]) -> Quote:
    tradingsymbol = key.split(":", 1)[-1]
    depth = payload.get("depth") or {}
    bids = depth.get("buy") or []
    asks = depth.get("sell") or []
    bid = Decimal(str(bids[0]["price"])) if bids and bids[0]["price"] else None
    ask = Decimal(str(asks[0]["price"])) if asks and asks[0]["price"] else None
    raw_ts = payload.get("timestamp") or payload.get("last_trade_time")
    timestamp = _ensure_ist(raw_ts) if isinstance(raw_ts, datetime) else now_utc()
    return Quote(
        tradingsymbol=tradingsymbol,
        timestamp=timestamp,
        last_price=Decimal(str(payload.get("last_price", 0))),
        bid=bid,
        ask=ask,
        volume=int(payload.get("volume", 0) or 0),
        open_interest=int(payload.get("oi", 0) or 0),
    )


def _ensure_ist(value: datetime) -> datetime:
    """Kite returns naive IST datetimes; make them explicit."""
    return value.replace(tzinfo=IST) if value.tzinfo is None else value


def _ensure_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))
