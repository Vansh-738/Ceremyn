"""Shared domain enumerations."""

from enum import StrEnum


class Exchange(StrEnum):
    NSE = "NSE"  # cash / index spot
    NFO = "NFO"  # NSE futures & options
    BSE = "BSE"
    BFO = "BFO"  # BSE futures & options
    MCX = "MCX"  # commodity futures (crude oil, gold, silver, copper, ...)


class OptionType(StrEnum):
    CALL = "CE"
    PUT = "PE"


class AssetClass(StrEnum):
    """What kind of instrument a tradable `Instrument` represents."""

    EQUITY = "EQUITY"
    FUTURES = "FUTURES"
    ETF = "ETF"
    OPTION = "OPTION"
    COMMODITY = "COMMODITY"
    CURRENCY_FUTURES = "CURRENCY_FUTURES"


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class ProductType(StrEnum):
    """Broker product type (Kite semantics)."""

    NRML = "NRML"  # overnight / carry-forward
    MIS = "MIS"  # intraday, auto square-off


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL_LIMIT = "SL"  # stop-loss with limit
    SL_MARKET = "SL-M"  # stop-loss market


class OrderStatus(StrEnum):
    CREATED = "CREATED"  # constructed by the OMS, not yet risk-checked
    VALIDATED = "VALIDATED"  # passed the risk engine
    SUBMITTED = "SUBMITTED"  # sent to the broker
    OPEN = "OPEN"  # acknowledged, resting at the exchange
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"  # by the risk engine, broker, or exchange


TERMINAL_ORDER_STATUSES = frozenset(
    {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED}
)


class SignalAction(StrEnum):
    ENTER = "ENTER"
    EXIT = "EXIT"
    ADJUST = "ADJUST"


class KillSwitchState(StrEnum):
    DISARMED = "DISARMED"
    ARMED = "ARMED"
    TRIGGERED = "TRIGGERED"


class TimeFrame(StrEnum):
    MINUTE = "minute"
    FIVE_MINUTE = "5minute"
    FIFTEEN_MINUTE = "15minute"
    HOUR = "60minute"
    DAY = "day"


class PatternDirection(StrEnum):
    """What a detected `Pattern` implies about near-term price direction."""

    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
